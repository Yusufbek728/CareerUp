import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils.translation import gettext_lazy as _

from . import services
from .broadcast import (
    abroadcast_message,
    abroadcast_read,
    build_message_event,
    chat_group,
    user_group,
)
from .exceptions import ChatError

logger = logging.getLogger(__name__)

# A text message is at most a few KB (2000 characters, up to 4 bytes each, plus JSON).
MAX_FRAME_BYTES = 16 * 1024


def _is_authenticated(scope):
    user = scope.get('user')
    return bool(user and user.is_authenticated)


@database_sync_to_async
def _load_conversation_state(user, conversation_id):
    """None if the user is not a participant, else the state sent to the client on connect."""
    conversation = services.get_conversation_for_user(user, conversation_id)
    if conversation is None:
        return None
    other = conversation.other_user(user)
    return {
        'blocked_by_me': services.has_blocked(user, other),
        'can_send': not services.users_blocked(user, other),
    }


@database_sync_to_async
def _store_message(user, conversation_id, text):
    conversation = services.get_conversation_for_user(user, conversation_id)
    if conversation is None:
        raise ChatError('forbidden', _('You are not a participant of this conversation.'))
    message = services.send_message(conversation, user, text)
    return build_message_event(message)


@database_sync_to_async
def _mark_read(user, conversation_id):
    conversation = services.get_conversation_for_user(user, conversation_id)
    if conversation is None:
        raise ChatError('forbidden', _('You are not a participant of this conversation.'))
    ids = services.mark_read(conversation, user)
    return ids, services.unread_count(user)


@database_sync_to_async
def _unread_count(user):
    return services.unread_count(user)


class JsonFrameMixin:
    """Parses incoming text frames as a JSON object, with a size cap."""

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return await self.send_error('invalid', 'Text frames only.')
        if len(text_data) > MAX_FRAME_BYTES:
            return await self.send_error('too_long', 'Frame too large.')
        try:
            content = json.loads(text_data)
        except ValueError:
            return await self.send_error('invalid', 'Malformed JSON.')
        if not isinstance(content, dict):
            return await self.send_error('invalid', 'Expected a JSON object.')
        await self.receive_json(content)

    async def send_json(self, content):
        await self.send(text_data=json.dumps(content))

    async def send_error(self, code, detail=''):
        await self.send_json({'type': 'error', 'code': code, 'detail': str(detail)})


class ChatConsumer(JsonFrameMixin, AsyncWebsocketConsumer):
    """/ws/chat/<conversation_id>/ - live messages and read receipts of one dialog."""

    group_name = None

    async def connect(self):
        # Closing before accept() rejects the handshake with HTTP 403.
        if not _is_authenticated(self.scope):
            await self.close()
            return
        self.user = self.scope['user']
        self.conversation_id = int(self.scope['url_route']['kwargs']['conversation_id'])
        state = await _load_conversation_state(self.user, self.conversation_id)
        if state is None:
            await self.close()
            return
        self.group_name = chat_group(self.conversation_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({'type': 'ready', **state})

    async def disconnect(self, code):
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content):
        kind = content.get('type')
        if kind == 'message':
            await self.handle_message(content)
        elif kind == 'read':
            await self.handle_read()
        else:
            await self.send_error('invalid', 'Unknown message type.')

    async def handle_message(self, content):
        try:
            event = await _store_message(self.user, self.conversation_id, content.get('text'))
        except ChatError as exc:
            await self.send_error(exc.code, exc.message)
            return
        try:
            await abroadcast_message(event)
        except Exception:
            # The message is stored; a dead channel layer must not drop the connection.
            logger.exception('Could not broadcast chat message')
            await self.send_error('server_error', 'Message saved but could not be delivered live.')

    async def handle_read(self):
        try:
            ids, unread = await _mark_read(self.user, self.conversation_id)
        except ChatError as exc:
            await self.send_error(exc.code, exc.message)
            return
        try:
            await abroadcast_read(self.conversation_id, self.user.pk, ids, unread)
        except Exception:
            logger.exception('Could not broadcast read receipt')

    # ---- group event handlers (names derive from the "type" of group_send events)
    async def chat_message(self, event):
        await self.send_json({'type': 'message', 'message': event['message']})

    async def chat_read(self, event):
        await self.send_json({
            'type': 'read',
            'reader_id': event['reader_id'],
            'message_ids': event['message_ids'],
        })


class NotificationConsumer(JsonFrameMixin, AsyncWebsocketConsumer):
    """/ws/notifications/ - personal group: unread counter for the header and the inbox."""

    group_name = None

    async def connect(self):
        if not _is_authenticated(self.scope):
            await self.close()
            return
        self.user = self.scope['user']
        self.group_name = user_group(self.user.pk)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({'type': 'unread', 'unread': await _unread_count(self.user)})

    async def disconnect(self, code):
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content):
        if content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})
        else:
            await self.send_error('invalid', 'Unknown message type.')

    async def notify_unread(self, event):
        await self.send_json({'type': 'unread', 'unread': event['unread']})

    async def notify_message(self, event):
        await self.send_json({
            'type': 'new_message',
            'unread': event['unread'],
            'conversation_id': event['conversation_id'],
            'preview': event['preview'],
            'sender_name': event['sender_name'],
            'created_at': event['created_at'],
        })
