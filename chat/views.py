from django.conf import settings
from django.contrib import messages as django_messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import services
from .attachments import ALLOWED_EXTENSIONS
from .broadcast import broadcast_message, broadcast_read
from .exceptions import ChatError
from .files import attachment_response
from .models import Message

DEFAULT_MESSAGES_LIMIT = 100
MAX_MESSAGES_LIMIT = 1000


def _is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _conversation_or_404(user, pk):
    conversation = services.get_conversation_for_user(user, pk)
    if conversation is None:
        # 404 rather than 403: do not reveal that somebody else's dialog exists.
        raise Http404
    return conversation


@login_required
@require_POST
def start_conversation(request, listing_type, pk):
    """The "Write" button on a listing: open (or create) a dialog with its owner."""
    try:
        listing = services.resolve_listing(listing_type, pk)
        conversation, _created = services.get_or_create_conversation(request.user, listing)
    except ChatError as exc:
        if exc.code in ('not_found', 'bad_request'):
            raise Http404(str(exc.message))
        return HttpResponse(str(exc.message), status=exc.http_status, content_type='text/plain; charset=utf-8')
    return redirect('chat:conversation', pk=conversation.pk)


@login_required
def inbox(request):
    user = request.user
    page = Paginator(services.inbox_queryset(user), 20).get_page(request.GET.get('page'))
    conversations = services.attach_last_messages(list(page.object_list))
    rows = []
    for conversation in conversations:
        last = conversation.last_message
        rows.append({
            'conversation': conversation,
            'other_name': services.display_name(conversation.other_user(user)),
            'last': last,
            'last_is_mine': bool(last and last.sender_id == user.pk),
            'last_preview': (last.text if last and last.text else (last.attachment_name if last else '')),
            'unread': conversation.unread,
        })
    return render(request, 'chat/inbox.html', {
        'rows': rows,
        'page_obj': page,
    })


@login_required
def conversation_detail(request, pk):
    user = request.user
    conversation = _conversation_or_404(user, pk)

    # Opening the dialog marks the other side's messages as read; tell open pages.
    broadcast_read(conversation, user, services.mark_read(conversation, user))

    try:
        limit = int(request.GET.get('limit', DEFAULT_MESSAGES_LIMIT))
    except ValueError:
        limit = DEFAULT_MESSAGES_LIMIT
    limit = max(1, min(limit, MAX_MESSAGES_LIMIT))
    total = conversation.messages.count()
    latest = conversation.messages.select_related('sender__account_profile').order_by('-created_at', '-pk')[:limit]
    chat_messages = list(reversed(list(latest)))
    for message in chat_messages:
        message.is_mine = message.sender_id == user.pk
        message.sender_display = services.display_name(message.sender)

    other = conversation.other_user(user)
    blocked_by_me = services.has_blocked(user, other)
    can_send = not blocked_by_me and not services.users_blocked(user, other)

    config = {
        'conversationId': conversation.pk,
        'userId': user.pk,
        'wsPath': f'/ws/chat/{conversation.pk}/',
        'sendUrl': reverse('chat:send', args=[conversation.pk]),
        'reportUrlTemplate': reverse('chat:report', args=[0]).replace('/0/', '/{id}/'),
        'attachmentUrlTemplate': reverse('chat:attachment', args=[0]).replace('/0/', '/{id}/'),
        'canSend': can_send,
        'maxLength': settings.CHAT_MESSAGE_MAX_LENGTH,
        'maxBytes': settings.CHAT_ATTACHMENT_MAX_BYTES,
        'allowedExtensions': list(ALLOWED_EXTENSIONS),
        'i18n': {
            'connecting': _('Connecting...'),
            'connected': _('Connected'),
            'reconnecting': _('Connection lost. Reconnecting...'),
            'report': _('Report'),
            'send_failed': _('The message could not be sent.'),
            'blockedNotice': _('Sending messages in this conversation is not possible.'),
            'fileTooLarge': _('The file is too large.'),
            'fileTypeNotAllowed': _('This file type is not allowed.'),
            'read': _('Read'),
            'errors': {
                'empty': _('The message is empty.'),
                'too_long': _('The message is too long.'),
                'rate_limited': _('You are sending messages too fast. Please wait a moment.'),
                'blocked': _('Sending messages in this conversation is not possible.'),
                'muted': _('You are muted by a moderator and cannot send messages.'),
                'forbidden': _('You are not a participant of this conversation.'),
                'bad_attachment': _('The attachment was rejected.'),
                'server_error': _('Message saved but could not be delivered live.'),
            },
        },
    }
    return render(request, 'chat/conversation.html', {
        'conversation': conversation,
        'other_name': services.display_name(other),
        'chat_messages': chat_messages,
        'total_messages': total,
        'has_more': total > len(chat_messages),
        'next_limit': min(limit + DEFAULT_MESSAGES_LIMIT, MAX_MESSAGES_LIMIT),
        'blocked_by_me': blocked_by_me,
        'can_send': can_send,
        'chat_config': config,
        'max_length': settings.CHAT_MESSAGE_MAX_LENGTH,
        'max_mb': settings.CHAT_ATTACHMENT_MAX_BYTES // (1024 * 1024),
        'allowed_extensions': ', '.join(ALLOWED_EXTENSIONS),
        'accept_attr': ','.join(f'.{ext}' for ext in ALLOWED_EXTENSIONS),
        'report_reason_max': settings.CHAT_REPORT_REASON_MAX_LENGTH,
    })


@login_required
@require_POST
def send_message(request, pk):
    """HTTP sending: attachments (multipart) and the no-JavaScript fallback for text."""
    ajax = _is_ajax(request)
    conversation = services.get_conversation_for_user(request.user, pk)
    if conversation is None:
        raise Http404
    try:
        message = services.send_message(
            conversation,
            request.user,
            request.POST.get('text', ''),
            request.FILES.get('attachment'),
        )
    except ChatError as exc:
        if ajax:
            return JsonResponse(
                {'error': exc.code, 'detail': str(exc.message)}, status=exc.http_status,
            )
        django_messages.error(request, exc.message)
        return redirect('chat:conversation', pk=conversation.pk)
    broadcast_message(message)
    if ajax:
        return JsonResponse({'message': services.serialize_message(message)}, status=201)
    return redirect('chat:conversation', pk=conversation.pk)


@login_required
@require_POST
def block_user(request, pk):
    conversation = _conversation_or_404(request.user, pk)
    other = conversation.other_user(request.user)
    services.block_user(request.user, other)
    django_messages.success(request, _('User blocked. You will not exchange messages with them.'))
    return redirect('chat:conversation', pk=conversation.pk)


@login_required
@require_POST
def unblock_user(request, pk):
    conversation = _conversation_or_404(request.user, pk)
    services.unblock_user(request.user, conversation.other_user(request.user))
    django_messages.success(request, _('User unblocked.'))
    return redirect('chat:conversation', pk=conversation.pk)


@login_required
@require_POST
def report_message(request, message_id):
    message = get_object_or_404(Message.objects.select_related('conversation'), pk=message_id)
    if not message.conversation.is_participant(request.user):
        raise Http404
    try:
        _report, created = services.report_message(request.user, message, request.POST.get('reason', ''))
    except ChatError as exc:
        django_messages.error(request, exc.message)
    else:
        if created:
            django_messages.success(request, _('Thank you. Your report has been sent to the moderators.'))
        else:
            django_messages.info(request, _('You have already reported this message.'))
    return redirect('chat:conversation', pk=message.conversation_id)


@login_required
def attachment_download(request, message_id):
    message = get_object_or_404(Message.objects.select_related('conversation'), pk=message_id)
    if not message.conversation.is_participant(request.user):
        raise Http404
    return attachment_response(message)
