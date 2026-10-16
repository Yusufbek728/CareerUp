"""Business logic shared by the HTML views, the DRF API and the WebSocket consumers.

Everything here is synchronous (ORM); consumers call it through database_sync_to_async.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .attachments import validate_attachment
from .exceptions import ChatError
from .models import LISTING_MODELS, Block, Conversation, Message, Report


# --------------------------------------------------------------------------- helpers

def display_name(user):
    profile = getattr(user, 'account_profile', None)
    return (profile.display_name if profile and profile.display_name else '') or user.get_username()


def conversations_for(user):
    return Conversation.objects.filter(Q(initiator=user) | Q(recipient=user))


def get_conversation_for_user(user, pk):
    """Conversation `pk` if `user` takes part in it, otherwise None."""
    if not getattr(user, 'is_authenticated', False):
        return None
    return (
        conversations_for(user)
        .select_related('initiator', 'recipient', 'content_type')
        .filter(pk=pk)
        .first()
    )


def unread_count(user):
    if not getattr(user, 'is_authenticated', False):
        return 0
    return (
        Message.objects
        .filter(read_at__isnull=True)
        .filter(Q(conversation__initiator=user) | Q(conversation__recipient=user))
        .exclude(sender=user)
        .count()
    )


def users_blocked(user_a, user_b):
    """True if either side has blocked the other."""
    return Block.objects.filter(
        Q(blocker=user_a, blocked=user_b) | Q(blocker=user_b, blocked=user_a)
    ).exists()


def share_conversation(user_a, user_b):
    return Conversation.objects.filter(
        Q(initiator=user_a, recipient=user_b) | Q(initiator=user_b, recipient=user_a)
    ).exists()


def has_blocked(blocker, blocked):
    return Block.objects.filter(blocker=blocker, blocked=blocked).exists()


# --------------------------------------------------------------------------- conversations

def resolve_listing(listing_type, listing_id):
    model = LISTING_MODELS.get(listing_type)
    if model is None:
        raise ChatError('bad_request', _('Unknown listing type.'))
    try:
        return model.objects.select_related('owner').get(pk=int(listing_id))
    except (model.DoesNotExist, TypeError, ValueError):
        raise ChatError('not_found', _('Listing not found.'))


def get_or_create_conversation(user, listing):
    """Open (or create) the dialog between `user` and the owner of `listing`."""
    if not getattr(user, 'is_authenticated', False):
        raise ChatError('forbidden', _('Log in to send messages.'))
    owner = listing.owner
    if owner is None:
        raise ChatError('bad_request', _('This listing has no owner to write to.'))
    if owner.pk == user.pk:
        raise ChatError('forbidden', _('You cannot write to yourself.'))
    content_type = ContentType.objects.get_for_model(listing, for_concrete_model=False)
    lookup = dict(content_type=content_type, object_id=listing.pk, initiator=user, recipient=owner)
    try:
        with transaction.atomic():
            return Conversation.objects.get_or_create(**lookup)
    except IntegrityError:  # lost a creation race: the row exists now
        return Conversation.objects.get(**lookup), False


def inbox_queryset(user):
    """User's conversations with annotations for the inbox page.

    Conversations started by someone else only show up once they contain a message, so a
    stranger cannot litter the inbox with empty dialogs."""
    last_message = Message.objects.filter(conversation=OuterRef('pk')).order_by('-created_at', '-pk')
    return (
        conversations_for(user)
        .annotate(
            has_messages=Exists(Message.objects.filter(conversation=OuterRef('pk'))),
            last_message_id=Subquery(last_message.values('pk')[:1]),
            unread=Count(
                'messages',
                filter=Q(messages__read_at__isnull=True) & ~Q(messages__sender=user),
            ),
        )
        .filter(Q(initiator=user) | Q(has_messages=True))
        .select_related('initiator__account_profile', 'recipient__account_profile', 'content_type')
        .prefetch_related('listing')
        .order_by('-updated_at', '-pk')
    )


def attach_last_messages(conversations):
    """Set `.last_message` on a list of conversations produced by inbox_queryset (one query)."""
    ids = [c.last_message_id for c in conversations if c.last_message_id]
    by_id = Message.objects.in_bulk(ids)
    for conversation in conversations:
        conversation.last_message = by_id.get(conversation.last_message_id)
    return conversations


# --------------------------------------------------------------------------- messages

def normalize_text(text):
    if text is None:
        return ''
    if not isinstance(text, str):
        raise ChatError('invalid', _('The message must be text.'))
    return text.strip()


def check_rate_limit(user):
    limit = settings.CHAT_RATE_LIMIT_COUNT
    since = timezone.now() - timedelta(seconds=settings.CHAT_RATE_LIMIT_WINDOW)
    recent = Message.objects.filter(sender=user, created_at__gte=since).count()
    if recent >= limit:
        raise ChatError('rate_limited', _('You are sending messages too fast. Please wait a moment.'))


def check_can_send(conversation, sender):
    """Raise unless `sender` may write to `conversation` (membership + blocks)."""
    if not conversation.is_participant(sender):
        raise ChatError('forbidden', _('You are not a participant of this conversation.'))
    other = conversation.other_user(sender)
    if users_blocked(sender, other):
        raise ChatError('blocked', _('Sending messages in this conversation is not possible.'))


def send_message(conversation, sender, text='', attachment=None):
    """Validate and store a message. Raises ChatError. Does NOT broadcast (see broadcast.py)."""
    check_can_send(conversation, sender)
    text = normalize_text(text)
    if len(text) > settings.CHAT_MESSAGE_MAX_LENGTH:
        raise ChatError('too_long', _('The message is too long (maximum %(n)s characters).') % {
            'n': settings.CHAT_MESSAGE_MAX_LENGTH,
        })
    if not text and attachment is None:
        raise ChatError('empty', _('The message is empty.'))
    valid = validate_attachment(attachment) if attachment is not None else None
    check_rate_limit(sender)

    now = timezone.now()
    with transaction.atomic():
        message = Message(conversation=conversation, sender=sender, text=text, created_at=now)
        if valid is not None:
            message.attachment.save(valid.name, attachment, save=False)
            message.attachment_name = valid.name
            message.attachment_size = valid.size
        message.save()
        Conversation.objects.filter(pk=conversation.pk).update(updated_at=now)
    return message


def mark_read(conversation, user):
    """Mark the other participant's unread messages as read. Returns the list of message ids."""
    if not conversation.is_participant(user):
        raise ChatError('forbidden', _('You are not a participant of this conversation.'))
    unread = Message.objects.filter(
        conversation=conversation, read_at__isnull=True,
    ).exclude(sender=user)
    ids = list(unread.values_list('pk', flat=True))
    if ids:
        Message.objects.filter(pk__in=ids, read_at__isnull=True).update(read_at=timezone.now())
    return ids


def serialize_message(message):
    """JSON-able representation used on the WebSocket (the API uses its own serializer)."""
    attachment = None
    if message.attachment:
        attachment = {
            'name': message.attachment_name,
            'size': message.attachment_size,
            'is_image': message.attachment_is_image,
            'url': reverse('chat:attachment', args=[message.pk]),
        }
    return {
        'id': message.pk,
        'conversation_id': message.conversation_id,
        'sender_id': message.sender_id,
        'sender_name': display_name(message.sender),
        'text': message.text,
        'attachment': attachment,
        'created_at': message.created_at.isoformat(),
        'read_at': message.read_at.isoformat() if message.read_at else None,
    }


# --------------------------------------------------------------------------- blocks / reports

def block_user(blocker, blocked):
    """Returns (block, created)."""
    if blocker.pk == blocked.pk:
        raise ChatError('forbidden', _('You cannot block yourself.'))
    return Block.objects.get_or_create(blocker=blocker, blocked=blocked)


def unblock_user(blocker, blocked):
    deleted, _unused = Block.objects.filter(blocker=blocker, blocked=blocked).delete()
    return bool(deleted)


def report_message(reporter, message, reason):
    """Create a report. Only a participant may report, and not their own message."""
    if not message.conversation.is_participant(reporter):
        raise ChatError('not_found', _('Message not found.'))
    if message.sender_id == reporter.pk:
        raise ChatError('forbidden', _('You cannot report your own message.'))
    reason = (reason or '').strip()
    if not reason:
        raise ChatError('empty', _('Please describe the reason.'))
    if len(reason) > settings.CHAT_REPORT_REASON_MAX_LENGTH:
        raise ChatError('too_long', _('The reason is too long (maximum %(n)s characters).') % {
            'n': settings.CHAT_REPORT_REASON_MAX_LENGTH,
        })
    report, created = Report.objects.get_or_create(
        reporter=reporter, message=message, defaults={'reason': reason},
    )
    return report, created
