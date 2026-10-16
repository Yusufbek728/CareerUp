"""Pushing events to WebSocket groups through the channel layer.

Groups:
  chat_<conversation id>  - both participants while they have the dialog open
  user_<user id>          - every open page of one user (header unread badge, inbox)
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from . import services

logger = logging.getLogger(__name__)

PREVIEW_LENGTH = 80


def chat_group(conversation_id):
    return f'chat_{int(conversation_id)}'


def user_group(user_id):
    return f'user_{int(user_id)}'


def preview_of(message):
    if message.text:
        text = message.text.replace('\n', ' ')
        return text if len(text) <= PREVIEW_LENGTH else text[:PREVIEW_LENGTH - 1] + '…'
    return message.attachment_name


def build_message_event(message):
    """Collect (synchronously, with ORM access) everything needed to announce `message`."""
    conversation = message.conversation
    recipient = conversation.other_user(message.sender)
    return {
        'conversation_id': conversation.pk,
        'message': services.serialize_message(message),
        'recipient_id': recipient.pk,
        'recipient_unread': services.unread_count(recipient),
        'preview': preview_of(message),
        'sender_name': services.display_name(message.sender),
        'created_at': message.created_at.isoformat(),
    }


async def abroadcast_message(event):
    layer = get_channel_layer()
    if layer is None:
        return
    await layer.group_send(
        chat_group(event['conversation_id']),
        {'type': 'chat.message', 'message': event['message']},
    )
    await layer.group_send(
        user_group(event['recipient_id']),
        {
            'type': 'notify.message',
            'unread': event['recipient_unread'],
            'conversation_id': event['conversation_id'],
            'preview': event['preview'],
            'sender_name': event['sender_name'],
            'created_at': event['created_at'],
        },
    )


async def abroadcast_read(conversation_id, reader_id, message_ids, reader_unread):
    layer = get_channel_layer()
    if layer is None or not message_ids:
        return
    await layer.group_send(
        chat_group(conversation_id),
        {'type': 'chat.read', 'reader_id': reader_id, 'message_ids': list(message_ids)},
    )
    await layer.group_send(user_group(reader_id), {'type': 'notify.unread', 'unread': reader_unread})


# ---- synchronous wrappers for HTTP views / DRF. A broken channel layer (e.g. Redis down)
# ---- must never turn an already stored message into a 500.

def broadcast_message(message):
    try:
        async_to_sync(abroadcast_message)(build_message_event(message))
    except Exception:
        logger.exception('Could not broadcast chat message %s', message.pk)


def broadcast_read(conversation, user, message_ids):
    if not message_ids:
        return
    try:
        async_to_sync(abroadcast_read)(
            conversation.pk, user.pk, message_ids, services.unread_count(user),
        )
    except Exception:
        logger.exception('Could not broadcast read receipt for conversation %s', conversation.pk)
