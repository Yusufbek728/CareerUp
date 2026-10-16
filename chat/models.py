import os
import re
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from mainapp.models import Internship, Job, Resume

# URL/API name of a listing type -> model.
LISTING_MODELS = {
    'job': Job,
    'internship': Internship,
    'resume': Resume,
}
LISTING_DETAIL_ROUTES = {
    'job': 'job_detail',
    'internship': 'internship_detail',
    'resume': 'resume_detail',
}


def attachment_storage():
    """Chat attachments are documents as well as images, so with Cloudinary they must go to
    the "raw" resource type (the default image storage rejects .docx/.txt)."""
    if os.getenv('CLOUDINARY_URL'):
        from cloudinary_storage.storage import RawMediaCloudinaryStorage
        return RawMediaCloudinaryStorage()
    return default_storage


def attachment_upload_to(instance, filename):
    """Never trust the client's file name: a random name plus a sanitised extension."""
    ext = os.path.splitext(filename or '')[1].lower()
    if not re.fullmatch(r'\.[a-z0-9]{1,5}', ext):
        ext = ''
    return f'chat_attachments/{uuid.uuid4().hex}{ext}'


class Conversation(models.Model):
    """A private dialog between a listing's owner (recipient) and an interested user (initiator)."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    listing = GenericForeignKey('content_type', 'object_id')
    initiator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='initiated_conversations',
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_conversations',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-updated_at', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=('content_type', 'object_id', 'initiator', 'recipient'),
                name='unique_conversation_per_listing_pair',
            ),
            models.CheckConstraint(
                condition=~Q(initiator=F('recipient')),
                name='conversation_not_with_self',
            ),
        ]
        indexes = [
            models.Index(fields=['initiator', '-updated_at'], name='chat_conv_initiator_idx'),
            models.Index(fields=['recipient', '-updated_at'], name='chat_conv_recipient_idx'),
            models.Index(fields=['content_type', 'object_id'], name='chat_conv_listing_idx'),
        ]

    def __str__(self):
        return f'#{self.pk} {self.initiator_id} <-> {self.recipient_id}'

    def is_participant(self, user):
        return user.is_authenticated and user.pk in (self.initiator_id, self.recipient_id)

    def other_user(self, user):
        return self.recipient if user.pk == self.initiator_id else self.initiator

    @property
    def listing_type(self):
        return self.content_type.model

    @property
    def listing_title(self):
        item = self.listing
        if item is None:
            return ''
        if isinstance(item, Resume):
            return f'{item.name} {item.surname}'
        return item.job_title

    @property
    def listing_url(self):
        if self.listing is None:
            return ''
        return reverse(LISTING_DETAIL_ROUTES[self.listing_type], args=[self.object_id])


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_messages',
    )
    text = models.TextField(blank=True)
    attachment = models.FileField(
        upload_to=attachment_upload_to,
        storage=attachment_storage,
        blank=True,
        null=True,
        max_length=255,
    )
    attachment_name = models.CharField(max_length=255, blank=True)
    attachment_size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at', 'pk']
        indexes = [
            models.Index(fields=['conversation', 'created_at'], name='chat_msg_conv_created_idx'),
            models.Index(fields=['conversation', 'read_at'], name='chat_msg_conv_read_idx'),
            models.Index(fields=['sender', 'created_at'], name='chat_msg_sender_created_idx'),
        ]

    def __str__(self):
        return f'#{self.pk} from {self.sender_id}'

    @property
    def has_attachment(self):
        return bool(self.attachment)

    @property
    def attachment_is_image(self):
        ext = os.path.splitext(self.attachment_name or '')[1].lower()
        return ext in ('.jpg', '.jpeg', '.png', '.webp')


class Block(models.Model):
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_blocks_made',
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_blocks_received',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [
            models.UniqueConstraint(fields=('blocker', 'blocked'), name='unique_chat_block'),
            models.CheckConstraint(condition=~Q(blocker=F('blocked')), name='chat_block_not_self'),
        ]
        indexes = [
            models.Index(fields=['blocked', 'blocker'], name='chat_block_reverse_idx'),
        ]

    def __str__(self):
        return f'{self.blocker_id} blocked {self.blocked_id}'


class Report(models.Model):
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_reports',
    )
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='reports')
    reason = models.CharField(max_length=500, verbose_name=_('Reason'))
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [
            models.UniqueConstraint(fields=('reporter', 'message'), name='unique_chat_report_per_message'),
        ]
        indexes = [
            models.Index(fields=['resolved', '-created_at'], name='chat_report_resolved_idx'),
        ]

    def __str__(self):
        return f'Report #{self.pk} on message {self.message_id}'
