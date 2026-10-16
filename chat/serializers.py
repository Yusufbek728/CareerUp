from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import serializers

from . import services
from .models import LISTING_MODELS, Block, Conversation, Message, Report


class UserBriefSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'display_name')
        read_only_fields = fields

    def get_display_name(self, obj):
        return services.display_name(obj)


class MessageSerializer(serializers.ModelSerializer):
    sender = UserBriefSerializer(read_only=True)
    attachment = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ('id', 'conversation', 'sender', 'text', 'attachment', 'created_at', 'read_at')
        read_only_fields = fields

    def get_attachment(self, obj):
        if not obj.attachment:
            return None
        url = reverse('chat:api-message-attachment', args=[obj.pk])
        request = self.context.get('request')
        return {
            'name': obj.attachment_name,
            'size': obj.attachment_size,
            'is_image': obj.attachment_is_image,
            'url': request.build_absolute_uri(url) if request else url,
        }


class MessageCreateSerializer(serializers.Serializer):
    """Input only; the real validation (length, blocks, file checks, rate limit) lives in services."""
    text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    attachment = serializers.FileField(required=False, allow_empty_file=True)


class ConversationSerializer(serializers.ModelSerializer):
    listing = serializers.SerializerMethodField()
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    blocked_by_me = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = (
            'id', 'listing', 'other_user', 'last_message', 'unread_count',
            'blocked_by_me', 'created_at', 'updated_at',
        )
        read_only_fields = fields

    def _user(self):
        return self.context['request'].user

    def get_listing(self, obj):
        item = obj.listing
        return {
            'type': obj.listing_type,
            'id': obj.object_id,
            'title': obj.listing_title,
            'exists': item is not None,
        }

    def get_other_user(self, obj):
        return UserBriefSerializer(obj.other_user(self._user())).data

    def get_last_message(self, obj):
        if hasattr(obj, 'last_message'):
            last = obj.last_message
        else:
            last = obj.messages.select_related('sender').order_by('-created_at', '-pk').first()
        if last is None:
            return None
        return MessageSerializer(last, context=self.context).data

    def get_unread_count(self, obj):
        if hasattr(obj, 'unread'):
            return obj.unread
        return obj.messages.filter(read_at__isnull=True).exclude(sender=self._user()).count()

    def get_blocked_by_me(self, obj):
        return services.has_blocked(self._user(), obj.other_user(self._user()))


class ConversationCreateSerializer(serializers.Serializer):
    listing_type = serializers.ChoiceField(choices=sorted(LISTING_MODELS))
    listing_id = serializers.IntegerField(min_value=1)


class BlockSerializer(serializers.ModelSerializer):
    blocked = UserBriefSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True, min_value=1)

    class Meta:
        model = Block
        fields = ('id', 'blocked', 'user_id', 'created_at')
        read_only_fields = ('id', 'blocked', 'created_at')


class ReportSerializer(serializers.ModelSerializer):
    message = serializers.IntegerField(source='message_id', read_only=True)

    class Meta:
        model = Report
        fields = ('id', 'message', 'reason', 'resolved', 'created_at')
        read_only_fields = fields


class ReportCreateSerializer(serializers.Serializer):
    message_id = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(trim_whitespace=False)
