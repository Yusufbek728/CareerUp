from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Block, Conversation, Message, Report


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'initiator', 'recipient', 'content_type', 'object_id', 'created_at', 'updated_at')
    list_filter = ('content_type', 'created_at')
    search_fields = ('initiator__username', 'recipient__username')
    raw_id_fields = ('initiator', 'recipient')
    date_hierarchy = 'created_at'


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Read-only for moderation: staff can review and delete messages, not forge them."""

    list_display = ('id', 'conversation', 'sender', 'short_text', 'attachment_name', 'created_at', 'read_at')
    list_filter = ('created_at',)
    search_fields = ('text', 'sender__username', 'attachment_name')
    raw_id_fields = ('conversation', 'sender')
    readonly_fields = (
        'conversation', 'sender', 'text', 'attachment', 'attachment_name',
        'attachment_size', 'created_at', 'read_at',
    )

    @admin.display(description=_('Text'))
    def short_text(self, obj):
        return obj.text[:60]

    def has_add_permission(self, request):
        return False


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ('id', 'blocker', 'blocked', 'created_at')
    search_fields = ('blocker__username', 'blocked__username')
    raw_id_fields = ('blocker', 'blocked')


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'reporter', 'reported_user', 'message_preview', 'reason', 'resolved', 'created_at')
    list_filter = ('resolved', 'created_at')
    search_fields = ('reason', 'reporter__username', 'message__text', 'message__sender__username')
    raw_id_fields = ('reporter', 'message')
    readonly_fields = ('reporter', 'message', 'reason', 'created_at')
    list_select_related = ('reporter', 'message__sender')
    actions = ('mark_resolved', 'mark_unresolved')

    @admin.display(description=_('Reported user'))
    def reported_user(self, obj):
        return obj.message.sender

    @admin.display(description=_('Message'))
    def message_preview(self, obj):
        return obj.message.text[:60] or obj.message.attachment_name

    @admin.action(description=_('Mark selected reports as resolved'))
    def mark_resolved(self, request, queryset):
        queryset.update(resolved=True)

    @admin.action(description=_('Mark selected reports as unresolved'))
    def mark_unresolved(self, request, queryset):
        queryset.update(resolved=False)

    def has_add_permission(self, request):
        return False
