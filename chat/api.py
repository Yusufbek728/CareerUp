"""DRF API of the chat (JWT or session auth, like the rest of /api/). HTTP only - WebSocket
authentication with JWT is out of scope."""
from django.contrib.auth.models import User
from rest_framework import generics, permissions, status
from rest_framework.exceptions import APIException, ErrorDetail, NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .broadcast import broadcast_message, broadcast_read
from .exceptions import ChatError
from .files import attachment_response
from .models import Block, Conversation, Message, Report
from .serializers import (
    BlockSerializer,
    ConversationCreateSerializer,
    ConversationSerializer,
    MessageCreateSerializer,
    MessageSerializer,
    ReportCreateSerializer,
    ReportSerializer,
)
from .throttling import ChatReadThrottle, ChatWriteThrottle


class ChatAPIException(APIException):
    """Maps a ChatError to an HTTP error with a stable machine readable `code`."""

    def __init__(self, exc):
        self.status_code = exc.http_status
        self.detail = {
            'detail': ErrorDetail(str(exc.message), code=exc.code),
            'code': exc.code,
        }


class ChatAPIMixin:
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ChatReadThrottle, ChatWriteThrottle]

    def get_conversation(self, pk):
        conversation = services.get_conversation_for_user(self.request.user, pk)
        if conversation is None:
            # 404, not 403: do not reveal that somebody else's dialog exists.
            raise NotFound()
        return conversation

    def is_swagger(self):
        return getattr(self, 'swagger_fake_view', False)


class MessagePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100


class ConversationListCreateView(ChatAPIMixin, generics.GenericAPIView):
    """GET: my conversations (newest activity first).
    POST {listing_type, listing_id}: open or create the dialog with the listing's owner
    (201 when created, 200 when it already existed)."""

    serializer_class = ConversationSerializer

    def get_queryset(self):
        if self.is_swagger():
            return Conversation.objects.none()
        return services.inbox_queryset(self.request.user)

    def get(self, request):
        page = self.paginate_queryset(self.get_queryset())
        conversations = services.attach_last_messages(list(page))
        return self.get_paginated_response(self.get_serializer(conversations, many=True).data)

    def post(self, request):
        data = ConversationCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            listing = services.resolve_listing(
                data.validated_data['listing_type'], data.validated_data['listing_id'],
            )
            conversation, created = services.get_or_create_conversation(request.user, listing)
        except ChatError as exc:
            raise ChatAPIException(exc)
        body = self.get_serializer(conversation).data
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ConversationDetailView(ChatAPIMixin, generics.RetrieveAPIView):
    serializer_class = ConversationSerializer

    def get_queryset(self):
        if self.is_swagger():
            return Conversation.objects.none()
        return services.conversations_for(self.request.user).select_related(
            'initiator__account_profile', 'recipient__account_profile', 'content_type',
        )


class ConversationMessagesView(ChatAPIMixin, generics.GenericAPIView):
    """GET: messages of a dialog, newest first, paginated.
    POST (JSON or multipart): `text` and/or `attachment`."""

    serializer_class = MessageSerializer
    pagination_class = MessagePagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        if self.is_swagger():
            return Message.objects.none()
        conversation = self.get_conversation(self.kwargs['pk'])
        return conversation.messages.select_related('sender__account_profile').order_by('-created_at', '-pk')

    def get(self, request, pk):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def post(self, request, pk):
        conversation = self.get_conversation(pk)
        data = MessageCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            message = services.send_message(
                conversation,
                request.user,
                data.validated_data.get('text', ''),
                data.validated_data.get('attachment'),
            )
        except ChatError as exc:
            raise ChatAPIException(exc)
        broadcast_message(message)
        return Response(self.get_serializer(message).data, status=status.HTTP_201_CREATED)


class ConversationReadView(ChatAPIMixin, APIView):
    """POST: mark the other participant's messages as read."""

    def post(self, request, pk):
        conversation = self.get_conversation(pk)
        ids = services.mark_read(conversation, request.user)
        broadcast_read(conversation, request.user, ids)
        return Response({'marked_read': len(ids)})


class MessageAttachmentView(ChatAPIMixin, APIView):
    """GET: download an attachment (JWT-friendly counterpart of the session-based page URL)."""

    def get(self, request, pk):
        message = Message.objects.select_related('conversation').filter(pk=pk).first()
        if message is None or not message.conversation.is_participant(request.user):
            raise NotFound()
        return attachment_response(message)


class BlockListCreateView(ChatAPIMixin, generics.GenericAPIView):
    """GET: users I blocked. POST {user_id}: block a user I have a conversation with."""

    serializer_class = BlockSerializer

    def get_queryset(self):
        if self.is_swagger():
            return Block.objects.none()
        return Block.objects.filter(blocker=self.request.user).select_related('blocked__account_profile')

    def get(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def post(self, request):
        data = BlockSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        # Only users I share a dialog with can be blocked; anything else looks like "not found",
        # so the endpoint cannot be used to probe which user ids exist.
        target = User.objects.filter(pk=data.validated_data['user_id']).first()
        if target is None or not services.share_conversation(request.user, target):
            raise NotFound()
        try:
            block, created = services.block_user(request.user, target)
        except ChatError as exc:
            raise ChatAPIException(exc)
        body = BlockSerializer(block, context=self.get_serializer_context()).data
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class BlockDeleteView(ChatAPIMixin, generics.DestroyAPIView):
    """DELETE /api/blocks/<id>/: unblock."""

    serializer_class = BlockSerializer

    def get_queryset(self):
        if self.is_swagger():
            return Block.objects.none()
        return Block.objects.filter(blocker=self.request.user)


class ReportListCreateView(ChatAPIMixin, generics.GenericAPIView):
    """GET: my reports. POST {message_id, reason}: report a message of a dialog I take part in."""

    serializer_class = ReportSerializer

    def get_queryset(self):
        if self.is_swagger():
            return Report.objects.none()
        return Report.objects.filter(reporter=self.request.user)

    def get(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def post(self, request):
        data = ReportCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        message = Message.objects.select_related('conversation').filter(
            pk=data.validated_data['message_id'],
        ).first()
        if message is None or not message.conversation.is_participant(request.user):
            raise NotFound()
        try:
            report, created = services.report_message(
                request.user, message, data.validated_data['reason'],
            )
        except ChatError as exc:
            raise ChatAPIException(exc)
        body = ReportSerializer(report, context=self.get_serializer_context()).data
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
