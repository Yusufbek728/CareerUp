import io
import json
import os
import tempfile
import zipfile

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from mainapp.models import AccountProfile, Internship, Job, Resume

from . import services
from .consumers import ChatConsumer, NotificationConsumer
from .models import Block, Conversation, Message, Report


# --------------------------------------------------------------------------- fixtures

def make_user(username, role=None):
    user = User.objects.create_user(username=username)  # no password: skips slow hashing; tests use force_login
    if role:
        AccountProfile.objects.create(user=user, role=role, display_name=username.title())
    return user


def make_job(owner):
    return Job.objects.create(
        owner=owner, company_name='Example', phone_number='+998901234567', salary=1000,
        required_experience=1, work_time=8, job_title='Developer', requirements_of_job='Python',
    )


def make_internship(owner):
    return Internship.objects.create(
        owner=owner, company_name='Example', phone_number='+998901234567',
        work_time=8, work_duration=12, job_title='Intern',
    )


def make_resume(owner):
    return Resume.objects.create(
        owner=owner, name='Candidate', surname='Example', email='c@example.com',
        phone_number='+998901234567', experience=2, wanted_salary=900, wanted_work_time=8,
    )


def image_bytes(fmt='PNG'):
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), 'red').save(buffer, fmt)
    return buffer.getvalue()


def docx_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', '<document/>')
    return buffer.getvalue()


PDF_BYTES = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n'
DOC_BYTES = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 600


def upload(name, content, content_type='application/octet-stream'):
    return SimpleUploadedFile(name, content, content_type=content_type)


class ChatFixtureMixin:
    """alice owns the job (recipient), bob is interested (initiator), carol is a stranger."""

    def make_fixtures(self):
        self.alice = make_user('alice', 'company')
        self.bob = make_user('bob', 'worker')
        self.carol = make_user('carol')  # no profile at all
        self.job = make_job(self.alice)
        self.conversation, _ = services.get_or_create_conversation(self.bob, self.job)

    def add_message(self, sender, text='hello', **kwargs):
        return Message.objects.create(conversation=self.conversation, sender=sender, text=text, **kwargs)


class MediaMixin:
    def use_temp_media(self):
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=directory.name))
        return directory.name


# --------------------------------------------------------------------------- starting a dialog

class StartConversationTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.conversation.delete()

    def start_url(self, listing_type, pk):
        return reverse('chat:start', args=[listing_type, pk])

    def test_start_from_each_listing_type_creates_dialog_with_owner(self):
        self.client.force_login(self.bob)
        for listing_type, item in (
            ('job', self.job),
            ('internship', make_internship(self.alice)),
            ('resume', make_resume(self.alice)),
        ):
            response = self.client.post(self.start_url(listing_type, item.pk))
            conversation = Conversation.objects.get(object_id=item.pk, content_type__model=listing_type)
            self.assertRedirects(response, reverse('chat:conversation', args=[conversation.pk]))
            self.assertEqual(conversation.initiator, self.bob)
            self.assertEqual(conversation.recipient, self.alice)
            self.assertEqual(conversation.listing, item)

    def test_starting_twice_reuses_the_dialog(self):
        self.client.force_login(self.bob)
        self.client.post(self.start_url('job', self.job.pk))
        self.client.post(self.start_url('job', self.job.pk))
        self.assertEqual(Conversation.objects.count(), 1)

    def test_user_without_profile_can_write(self):
        self.client.force_login(self.carol)
        response = self.client.post(self.start_url('job', self.job.pk))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Conversation.objects.filter(initiator=self.carol).exists())

    def test_owner_cannot_write_to_themselves(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.start_url('job', self.job.pk))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Conversation.objects.count(), 0)

    def test_listing_without_owner_is_not_found(self):
        orphan = make_job(None)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(self.start_url('job', orphan.pk)).status_code, 404)

    def test_unknown_listing_or_type_is_not_found(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(self.start_url('job', 99999)).status_code, 404)
        self.assertEqual(self.client.post(self.start_url('car', self.job.pk)).status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.post(self.start_url('job', self.job.pk))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])
        self.assertEqual(Conversation.objects.count(), 0)

    def test_get_is_not_allowed(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.start_url('job', self.job.pk)).status_code, 405)

    def test_db_forbids_self_conversation_and_duplicates(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Conversation.objects.create(
                content_type=ContentType.objects.get_for_model(Job), object_id=self.job.pk,
                initiator=self.alice, recipient=self.alice,
            )
        Conversation.objects.create(
            content_type=ContentType.objects.get_for_model(Job), object_id=self.job.pk,
            initiator=self.bob, recipient=self.alice,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Conversation.objects.create(
                content_type=ContentType.objects.get_for_model(Job), object_id=self.job.pk,
                initiator=self.bob, recipient=self.alice,
            )

    def test_write_button_visibility_on_detail_pages(self):
        url = reverse('job_detail', args=[self.job.pk])
        start = self.start_url('job', self.job.pk)
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(url), start)
        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get(url), start)
        orphan = make_job(None)
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get(reverse('job_detail', args=[orphan.pk])), '/messages/start/')
        # Guests are sent to the login page instead of getting a working button.
        guest = Client().get(url)
        self.assertNotContains(guest, start)
        self.assertContains(guest, 'chat-start-btn')

    def test_write_button_on_internship_and_resume_pages(self):
        internship = make_internship(self.alice)
        resume = make_resume(self.alice)
        self.client.force_login(self.bob)
        self.assertContains(
            self.client.get(reverse('internship_detail', args=[internship.pk])),
            self.start_url('internship', internship.pk),
        )
        self.assertContains(
            self.client.get(reverse('resume_detail', args=[resume.pk])),
            self.start_url('resume', resume.pk),
        )


# --------------------------------------------------------------------------- access control (HTTP)

class AccessControlTests(ChatFixtureMixin, MediaMixin, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.use_temp_media()
        self.message = self.add_message(self.alice, 'secret')

    def test_participants_can_open_the_dialog(self):
        for user in (self.alice, self.bob):
            self.client.force_login(user)
            response = self.client.get(reverse('chat:conversation', args=[self.conversation.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'secret')

    def test_stranger_gets_404_everywhere(self):
        self.client.force_login(self.carol)
        pk = self.conversation.pk
        self.assertEqual(self.client.get(reverse('chat:conversation', args=[pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('chat:send', args=[pk]), {'text': 'x'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('chat:block', args=[pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('chat:unblock', args=[pk])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse('chat:report', args=[self.message.pk]), {'reason': 'x'}).status_code, 404,
        )
        self.assertEqual(self.client.get(reverse('chat:attachment', args=[self.message.pk])).status_code, 404)
        self.assertEqual(Message.objects.count(), 1)
        self.assertFalse(Report.objects.exists())
        self.assertFalse(Block.objects.exists())

    def test_anonymous_is_redirected_to_login(self):
        for url in (reverse('chat:inbox'), reverse('chat:conversation', args=[self.conversation.pk])):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse('login'), response['Location'])

    def test_stranger_does_not_see_dialog_in_inbox(self):
        self.client.force_login(self.carol)
        self.assertNotContains(self.client.get(reverse('chat:inbox')), 'secret')

    def test_message_text_is_escaped(self):
        self.add_message(self.bob, '<script>alert(1)</script>')
        self.client.force_login(self.alice)
        response = self.client.get(reverse('chat:conversation', args=[self.conversation.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')


# --------------------------------------------------------------------------- sending over HTTP

class HttpSendTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.client.force_login(self.bob)
        self.url = reverse('chat:send', args=[self.conversation.pk])
        self.ajax = {'headers': {'X-Requested-With': 'XMLHttpRequest'}}

    def test_send_text(self):
        response = self.client.post(self.url, {'text': '  Hello  '}, **self.ajax)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['message']['text'], 'Hello')
        message = Message.objects.get()
        self.assertEqual((message.sender, message.conversation), (self.bob, self.conversation))

    def test_send_without_javascript_redirects(self):
        response = self.client.post(self.url, {'text': 'Hello'})
        self.assertRedirects(response, reverse('chat:conversation', args=[self.conversation.pk]))
        self.assertEqual(Message.objects.count(), 1)

    def test_empty_and_whitespace_messages_are_rejected(self):
        for text in ('', '   \n  '):
            response = self.client.post(self.url, {'text': text}, **self.ajax)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['error'], 'empty')
        self.assertEqual(Message.objects.count(), 0)

    @override_settings(CHAT_MESSAGE_MAX_LENGTH=10)
    def test_too_long_message_is_rejected(self):
        ok = self.client.post(self.url, {'text': 'x' * 10}, **self.ajax)
        too_long = self.client.post(self.url, {'text': 'x' * 11}, **self.ajax)
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(too_long.status_code, 400)
        self.assertEqual(too_long.json()['error'], 'too_long')

    @override_settings(CHAT_RATE_LIMIT_COUNT=3)
    def test_rate_limit(self):
        for _ in range(3):
            self.assertEqual(self.client.post(self.url, {'text': 'hi'}, **self.ajax).status_code, 201)
        response = self.client.post(self.url, {'text': 'hi'}, **self.ajax)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['error'], 'rate_limited')
        self.assertEqual(Message.objects.count(), 3)

    def test_sending_bumps_conversation_ordering(self):
        other_job = make_job(self.alice)
        other, _ = services.get_or_create_conversation(self.bob, other_job)
        self.client.post(self.url, {'text': 'bump'}, **self.ajax)
        first = services.conversations_for(self.bob).first()
        self.assertEqual(first, self.conversation)
        self.assertNotEqual(first, other)


# --------------------------------------------------------------------------- blocking

class BlockingTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.send_url = reverse('chat:send', args=[self.conversation.pk])
        self.ajax = {'headers': {'X-Requested-With': 'XMLHttpRequest'}}

    def test_block_view_blocks_the_other_participant(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse('chat:block', args=[self.conversation.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Block.objects.filter(blocker=self.alice, blocked=self.bob).exists())

    def test_block_is_idempotent_and_unblock_removes_it(self):
        self.client.force_login(self.alice)
        block_url = reverse('chat:block', args=[self.conversation.pk])
        self.client.post(block_url)
        self.client.post(block_url)
        self.assertEqual(Block.objects.count(), 1)
        self.client.post(reverse('chat:unblock', args=[self.conversation.pk]))
        self.assertEqual(Block.objects.count(), 0)

    def test_sending_is_forbidden_in_both_directions_over_http(self):
        Block.objects.create(blocker=self.alice, blocked=self.bob)
        for user in (self.alice, self.bob):
            self.client.force_login(user)
            response = self.client.post(self.send_url, {'text': 'hi'}, **self.ajax)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()['error'], 'blocked')
        self.assertEqual(Message.objects.count(), 0)

    def test_sending_works_again_after_unblock(self):
        block = Block.objects.create(blocker=self.alice, blocked=self.bob)
        block.delete()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(self.send_url, {'text': 'hi'}, **self.ajax).status_code, 201)

    def test_blocked_user_does_not_learn_who_blocked_whom(self):
        Block.objects.create(blocker=self.alice, blocked=self.bob)
        self.client.force_login(self.bob)
        page = self.client.get(reverse('chat:conversation', args=[self.conversation.pk]))
        self.assertContains(page, 'Sending messages in this conversation is not possible.')
        self.assertNotContains(page, 'You blocked this user')
        self.assertNotContains(page, 'id="chat-form"')
        self.client.force_login(self.alice)
        page = self.client.get(reverse('chat:conversation', args=[self.conversation.pk]))
        self.assertContains(page, 'You blocked this user')

    def test_existing_history_stays_readable(self):
        self.add_message(self.bob, 'older message')
        Block.objects.create(blocker=self.alice, blocked=self.bob)
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(reverse('chat:conversation', args=[self.conversation.pk])), 'older message')


# --------------------------------------------------------------------------- attachments

class AttachmentTests(ChatFixtureMixin, MediaMixin, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.media_root = self.use_temp_media()
        self.client.force_login(self.bob)
        self.url = reverse('chat:send', args=[self.conversation.pk])
        self.ajax = {'headers': {'X-Requested-With': 'XMLHttpRequest'}}

    def send(self, name, content, text=''):
        return self.client.post(self.url, {'text': text, 'attachment': upload(name, content)}, **self.ajax)

    def test_allowed_files_are_accepted(self):
        samples = {
            'photo.png': image_bytes('PNG'),
            'photo.jpg': image_bytes('JPEG'),
            'photo.jpeg': image_bytes('JPEG'),
            'photo.webp': image_bytes('WEBP'),
            'doc.pdf': PDF_BYTES,
            'old.doc': DOC_BYTES,
            'new.docx': docx_bytes(),
            'notes.txt': 'Привет, мир'.encode('utf-8'),
        }
        for name, content in samples.items():
            response = self.send(name, content)
            self.assertEqual(response.status_code, 201, f'{name}: {response.content!r}')
        self.assertEqual(Message.objects.filter(attachment__gt='').count(), len(samples))

    def test_attachment_with_text(self):
        response = self.send('photo.png', image_bytes(), text='look')
        self.assertEqual(response.status_code, 201)
        body = response.json()['message']
        self.assertEqual(body['text'], 'look')
        self.assertTrue(body['attachment']['is_image'])
        self.assertEqual(body['attachment']['name'], 'photo.png')

    def test_disallowed_extensions_are_rejected(self):
        for name in ('run.exe', 'page.html', 'image.svg', 'shell.php', 'script.js', 'archive.zip', 'noext'):
            response = self.send(name, b'whatever content')
            self.assertEqual(response.status_code, 400, name)
            self.assertEqual(response.json()['error'], 'bad_attachment')
        self.assertEqual(Message.objects.count(), 0)

    def test_content_must_match_extension(self):
        cases = {
            'fake.png': b'this is not a png at all',
            'fake.jpg': image_bytes('PNG'),       # valid image, but not a JPEG
            'fake.pdf': b'MZ\x90\x00 an executable',
            'fake.doc': b'plain text pretending to be doc',
            'fake.docx': b'plain text pretending to be docx',
            'binary.txt': b'text\x00with nul bytes',
            'empty.txt': b'',
        }
        for name, content in cases.items():
            response = self.send(name, content)
            self.assertEqual(response.status_code, 400, name)
        self.assertEqual(Message.objects.count(), 0)

    def test_docx_must_look_like_word_document(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('hello.txt', 'just a zip')
        self.assertEqual(self.send('zip.docx', buffer.getvalue()).status_code, 400)

    @override_settings(CHAT_ATTACHMENT_MAX_BYTES=1024)
    def test_size_limit(self):
        padded = PDF_BYTES + b'0' * 2048
        self.assertEqual(self.send('big.pdf', padded).status_code, 400)
        self.assertEqual(self.send('small.pdf', PDF_BYTES).status_code, 201)

    def test_file_names_cannot_traverse_paths(self):
        response = self.send('../../../evil.png', image_bytes())
        self.assertEqual(response.status_code, 201)
        message = Message.objects.get()
        self.assertEqual(message.attachment_name, 'evil.png')
        stored = os.path.normpath(message.attachment.path)
        self.assertTrue(stored.startswith(os.path.normpath(os.path.join(self.media_root, 'chat_attachments'))))
        self.assertNotIn('evil', os.path.basename(stored))  # random name, client name is display-only

        response = self.send('..\\..\\windows\\evil.png', image_bytes())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Message.objects.latest('pk').attachment_name, 'evil.png')

    def test_download_checks_membership_and_serves_safe_headers(self):
        self.send('photo.png', image_bytes())
        self.send('doc.pdf', PDF_BYTES)
        image_message, pdf_message = Message.objects.order_by('pk')
        url = lambda message: reverse('chat:attachment', args=[message.pk])  # noqa: E731

        response = self.client.get(url(image_message))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertTrue(response['Content-Disposition'].startswith('inline'))
        b''.join(response.streaming_content)

        response = self.client.get(url(pdf_message))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Disposition'].startswith('attachment'))
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        b''.join(response.streaming_content)

        self.client.force_login(self.alice)
        response = self.client.get(url(pdf_message))
        self.assertEqual(response.status_code, 200)
        b''.join(response.streaming_content)

        self.client.force_login(self.carol)
        self.assertEqual(self.client.get(url(pdf_message)).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url(pdf_message)).status_code, 302)

    def test_attachment_cannot_be_sent_when_blocked(self):
        Block.objects.create(blocker=self.alice, blocked=self.bob)
        response = self.send('photo.png', image_bytes())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Message.objects.count(), 0)
        self.assertFalse(os.path.exists(os.path.join(self.media_root, 'chat_attachments')))

    def test_stranger_cannot_send_attachment(self):
        self.client.force_login(self.carol)
        self.assertEqual(self.send('photo.png', image_bytes()).status_code, 404)
        self.assertEqual(Message.objects.count(), 0)


# --------------------------------------------------------------------------- unread counters / inbox

class UnreadAndInboxTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.make_fixtures()

    def test_unread_count_counts_only_incoming_unread_messages(self):
        self.add_message(self.bob, 'one')
        self.add_message(self.bob, 'two')
        self.add_message(self.alice, 'mine')
        self.assertEqual(services.unread_count(self.alice), 2)
        self.assertEqual(services.unread_count(self.bob), 1)
        self.assertEqual(services.unread_count(self.carol), 0)
        self.assertEqual(services.unread_count(AnonymousUser()), 0)

    def test_opening_the_dialog_marks_messages_read(self):
        self.add_message(self.bob, 'one')
        self.add_message(self.bob, 'two')
        self.client.force_login(self.alice)
        self.client.get(reverse('chat:conversation', args=[self.conversation.pk]))
        self.assertEqual(services.unread_count(self.alice), 0)
        self.assertEqual(Message.objects.filter(read_at__isnull=True).count(), 0)

    def test_sender_messages_stay_unread_until_recipient_opens(self):
        self.add_message(self.bob, 'one')
        self.client.force_login(self.bob)  # the sender opening the dialog changes nothing
        self.client.get(reverse('chat:conversation', args=[self.conversation.pk]))
        self.assertEqual(services.unread_count(self.alice), 1)

    def test_header_badge_shows_unread_count(self):
        self.add_message(self.bob, 'one')
        self.add_message(self.bob, 'two')
        self.client.force_login(self.alice)
        response = self.client.get(reverse('jobs_page'))
        self.assertContains(response, reverse('chat:inbox'))
        self.assertContains(response, 'data-chat-unread-badge>2</span>')
        self.client.force_login(self.carol)
        self.assertContains(self.client.get(reverse('jobs_page')), 'data-chat-unread-badge hidden>0</span>')

    def test_header_has_no_chat_link_for_guests(self):
        response = Client().get(reverse('jobs_page'))
        self.assertNotContains(response, 'data-chat-unread-badge')

    def test_inbox_lists_dialogs_with_preview_and_unread(self):
        self.add_message(self.bob, 'preview text here')
        self.client.force_login(self.alice)
        response = self.client.get(reverse('chat:inbox'))
        self.assertContains(response, 'preview text here')
        self.assertContains(response, 'Bob')
        self.assertContains(response, reverse('chat:conversation', args=[self.conversation.pk]))
        self.assertContains(response, 'data-chat-conversation-unread>1</span>')

    def test_empty_dialog_is_hidden_from_recipient_but_visible_to_initiator(self):
        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get(reverse('chat:inbox')), reverse('chat:conversation', args=[self.conversation.pk]))
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(reverse('chat:inbox')), reverse('chat:conversation', args=[self.conversation.pk]))

    def test_dialog_survives_listing_deletion(self):
        self.add_message(self.bob, 'still here')
        self.job.delete()
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(reverse('chat:inbox')), 'still here')
        page = self.client.get(reverse('chat:conversation', args=[self.conversation.pk]))
        self.assertEqual(page.status_code, 200)


# --------------------------------------------------------------------------- reports

class ReportTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.message = self.add_message(self.alice, 'rude message')
        self.url = reverse('chat:report', args=[self.message.pk])

    def test_participant_can_report_the_other_sides_message(self):
        self.client.force_login(self.bob)
        response = self.client.post(self.url, {'reason': 'Insults'})
        self.assertRedirects(response, reverse('chat:conversation', args=[self.conversation.pk]))
        report = Report.objects.get()
        self.assertEqual((report.reporter, report.message, report.reason, report.resolved), (self.bob, self.message, 'Insults', False))

    def test_duplicate_report_is_not_created_twice(self):
        self.client.force_login(self.bob)
        self.client.post(self.url, {'reason': 'Insults'})
        self.client.post(self.url, {'reason': 'Insults again'})
        self.assertEqual(Report.objects.count(), 1)

    def test_cannot_report_own_message(self):
        self.client.force_login(self.alice)
        self.client.post(self.url, {'reason': 'x'})
        self.assertEqual(Report.objects.count(), 0)

    def test_reason_is_required_and_limited(self):
        self.client.force_login(self.bob)
        self.client.post(self.url, {'reason': '   '})
        self.client.post(self.url, {'reason': 'x' * 501})
        self.assertEqual(Report.objects.count(), 0)

    def test_stranger_cannot_report(self):
        self.client.force_login(self.carol)
        self.assertEqual(self.client.post(self.url, {'reason': 'x'}).status_code, 404)
        self.assertEqual(Report.objects.count(), 0)

    def test_chat_models_are_registered_in_admin(self):
        for model in (Conversation, Message, Block, Report):
            self.assertIn(model, admin.site._registry)

    def test_admin_can_resolve_reports(self):
        report = Report.objects.create(reporter=self.bob, message=self.message, reason='x')
        staff = User.objects.create_superuser('root', 'root@example.com', 'test-password')
        self.client.force_login(staff)
        response = self.client.post(reverse('admin:chat_report_changelist'), {
            'action': 'mark_resolved', '_selected_action': [report.pk],
        })
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        self.assertTrue(report.resolved)
        self.assertEqual(self.client.get(reverse('admin:chat_message_changelist')).status_code, 200)


# --------------------------------------------------------------------------- REST API

class ApiTests(ChatFixtureMixin, MediaMixin, TestCase):
    def setUp(self):
        cache.clear()  # DRF throttle counters live in the cache
        self.make_fixtures()
        self.use_temp_media()
        self.add_message(self.alice, 'first')

    def api(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
        return client

    def test_authentication_is_required(self):
        client = APIClient()
        for url in (
            reverse('chat:api-conversation-list'),
            reverse('chat:api-conversation-messages', args=[self.conversation.pk]),
            reverse('chat:api-block-list'),
            reverse('chat:api-report-list'),
        ):
            self.assertEqual(client.get(url).status_code, 401, url)

    def test_list_conversations(self):
        response = self.api(self.bob).get(reverse('chat:api-conversation-list'))
        self.assertEqual(response.status_code, 200)
        result = response.json()['results'][0]
        self.assertEqual(result['id'], self.conversation.pk)
        self.assertEqual(result['other_user']['username'], 'alice')
        self.assertEqual(result['unread_count'], 1)
        self.assertEqual(result['last_message']['text'], 'first')
        self.assertEqual(result['listing'], {'type': 'job', 'id': self.job.pk, 'title': 'Developer', 'exists': True})
        self.assertEqual(self.api(self.carol).get(reverse('chat:api-conversation-list')).json()['count'], 0)

    def test_create_conversation_from_listing(self):
        url = reverse('chat:api-conversation-list')
        client = self.api(self.carol)
        payload = {'listing_type': 'job', 'listing_id': self.job.pk}
        first = client.post(url, payload, format='json')
        again = client.post(url, payload, format='json')
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.json()['id'], again.json()['id'])
        self.assertEqual(first.json()['other_user']['username'], 'alice')

    def test_create_conversation_rules(self):
        url = reverse('chat:api-conversation-list')
        own = self.api(self.alice).post(url, {'listing_type': 'job', 'listing_id': self.job.pk}, format='json')
        self.assertEqual(own.status_code, 403)
        orphan = make_job(None)
        no_owner = self.api(self.bob).post(url, {'listing_type': 'job', 'listing_id': orphan.pk}, format='json')
        self.assertEqual(no_owner.status_code, 400)
        missing = self.api(self.bob).post(url, {'listing_type': 'job', 'listing_id': 99999}, format='json')
        self.assertEqual(missing.status_code, 404)
        bad_type = self.api(self.bob).post(url, {'listing_type': 'car', 'listing_id': 1}, format='json')
        self.assertEqual(bad_type.status_code, 400)

    def test_conversation_detail_is_participants_only(self):
        url = reverse('chat:api-conversation-detail', args=[self.conversation.pk])
        self.assertEqual(self.api(self.alice).get(url).status_code, 200)
        self.assertEqual(self.api(self.carol).get(url).status_code, 404)

    def test_messages_get_and_post(self):
        url = reverse('chat:api-conversation-messages', args=[self.conversation.pk])
        client = self.api(self.bob)
        response = client.post(url, {'text': 'reply'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['sender']['username'], 'bob')
        listing = client.get(url).json()
        self.assertEqual([m['text'] for m in listing['results']], ['reply', 'first'])  # newest first

    def test_messages_validation_over_api(self):
        url = reverse('chat:api-conversation-messages', args=[self.conversation.pk])
        client = self.api(self.bob)
        empty = client.post(url, {'text': '  '}, format='json')
        self.assertEqual((empty.status_code, empty.json()['code']), (400, 'empty'))
        with override_settings(CHAT_MESSAGE_MAX_LENGTH=5):
            long = client.post(url, {'text': 'x' * 6}, format='json')
        self.assertEqual((long.status_code, long.json()['code']), (400, 'too_long'))

    def test_messages_are_participants_only(self):
        url = reverse('chat:api-conversation-messages', args=[self.conversation.pk])
        client = self.api(self.carol)
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(client.post(url, {'text': 'x'}, format='json').status_code, 404)

    def test_blocked_participants_cannot_post(self):
        Block.objects.create(blocker=self.alice, blocked=self.bob)
        url = reverse('chat:api-conversation-messages', args=[self.conversation.pk])
        for user in (self.alice, self.bob):
            response = self.api(user).post(url, {'text': 'x'}, format='json')
            self.assertEqual((response.status_code, response.json()['code']), (403, 'blocked'))
        self.assertEqual(Message.objects.count(), 1)

    def test_attachment_upload_and_download_with_jwt(self):
        url = reverse('chat:api-conversation-messages', args=[self.conversation.pk])
        client = self.api(self.bob)
        response = client.post(url, {'attachment': upload('photo.png', image_bytes())}, format='multipart')
        self.assertEqual(response.status_code, 201, response.content)
        attachment = response.json()['attachment']
        self.assertEqual(attachment['name'], 'photo.png')
        download = client.get(attachment['url'])
        self.assertEqual(download.status_code, 200)
        b''.join(download.streaming_content)
        self.assertEqual(self.api(self.carol).get(attachment['url']).status_code, 404)

        bad = client.post(url, {'attachment': upload('run.exe', b'MZ')}, format='multipart')
        self.assertEqual((bad.status_code, bad.json()['code']), (400, 'bad_attachment'))
        fake = client.post(url, {'attachment': upload('fake.png', b'not an image')}, format='multipart')
        self.assertEqual(fake.status_code, 400)

    @override_settings(CHAT_ATTACHMENT_MAX_BYTES=1024)
    def test_attachment_size_limit_over_api(self):
        url = reverse('chat:api-conversation-messages', args=[self.conversation.pk])
        response = self.api(self.bob).post(
            url, {'attachment': upload('big.pdf', PDF_BYTES + b'0' * 2048)}, format='multipart',
        )
        self.assertEqual(response.status_code, 400)

    def test_mark_read(self):
        url = reverse('chat:api-conversation-read', args=[self.conversation.pk])
        self.assertEqual(self.api(self.carol).post(url).status_code, 404)
        response = self.api(self.bob).post(url)
        self.assertEqual(response.json(), {'marked_read': 1})
        self.assertEqual(services.unread_count(self.bob), 0)

    def test_blocks_crud(self):
        client = self.api(self.alice)
        url = reverse('chat:api-block-list')
        created = client.post(url, {'user_id': self.bob.pk}, format='json')
        again = client.post(url, {'user_id': self.bob.pk}, format='json')
        self.assertEqual((created.status_code, again.status_code), (201, 200))
        self.assertEqual(client.get(url).json()['results'][0]['blocked']['username'], 'bob')
        self.assertEqual(self.api(self.bob).get(url).json()['count'], 0)
        detail = reverse('chat:api-block-detail', args=[created.json()['id']])
        self.assertEqual(self.api(self.bob).delete(detail).status_code, 404)  # not the blocker's
        self.assertEqual(client.delete(detail).status_code, 204)
        self.assertEqual(Block.objects.count(), 0)

    def test_cannot_block_strangers_or_yourself(self):
        client = self.api(self.alice)
        url = reverse('chat:api-block-list')
        self.assertEqual(client.post(url, {'user_id': self.carol.pk}, format='json').status_code, 404)
        self.assertEqual(client.post(url, {'user_id': 99999}, format='json').status_code, 404)
        self.assertEqual(client.post(url, {'user_id': self.alice.pk}, format='json').status_code, 404)
        self.assertEqual(Block.objects.count(), 0)

    def test_reports(self):
        message = Message.objects.get()
        url = reverse('chat:api-report-list')
        client = self.api(self.bob)
        created = client.post(url, {'message_id': message.pk, 'reason': 'Spam'}, format='json')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()['message'], message.pk)
        self.assertFalse(created.json()['resolved'])
        self.assertEqual(client.post(url, {'message_id': message.pk, 'reason': 'Spam'}, format='json').status_code, 200)
        self.assertEqual(Report.objects.count(), 1)
        self.assertEqual(client.get(url).json()['count'], 1)
        self.assertEqual(self.api(self.alice).get(url).json()['count'], 0)

    def test_report_rules(self):
        message = Message.objects.get()
        url = reverse('chat:api-report-list')
        self.assertEqual(
            self.api(self.alice).post(url, {'message_id': message.pk, 'reason': 'x'}, format='json').status_code, 403,
        )  # own message
        self.assertEqual(
            self.api(self.carol).post(url, {'message_id': message.pk, 'reason': 'x'}, format='json').status_code, 404,
        )
        self.assertEqual(
            self.api(self.bob).post(url, {'message_id': 99999, 'reason': 'x'}, format='json').status_code, 404,
        )
        self.assertEqual(
            self.api(self.bob).post(url, {'message_id': message.pk, 'reason': '  '}, format='json').status_code, 400,
        )

    def test_write_throttle_applies_to_unsafe_methods_only(self):
        from .throttling import ChatWriteThrottle
        self.assertEqual(ChatWriteThrottle.rate, '30/minute')
        url = reverse('chat:api-conversation-list')
        client = self.api(self.bob)
        for _ in range(35):  # reads are never counted against the write bucket
            self.assertEqual(client.get(url).status_code, 200)

    def test_swagger_schema_still_builds(self):
        response = self.client.get('/swagger/?format=openapi')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/conversations/', response.content.decode())


# --------------------------------------------------------------------------- WebSocket consumers

def ws_client(consumer, user, path, **url_kwargs):
    communicator = WebsocketCommunicator(consumer.as_asgi(), path)
    communicator.scope['user'] = user
    communicator.scope['url_route'] = {'args': (), 'kwargs': url_kwargs}
    return communicator


class WebSocketTests(ChatFixtureMixin, MediaMixin, TransactionTestCase):
    def setUp(self):
        self.make_fixtures()
        self.use_temp_media()
        self.path = f'/ws/chat/{self.conversation.pk}/'

    def chat(self, user):
        return ws_client(ChatConsumer, user, self.path, conversation_id=str(self.conversation.pk))

    def notifications(self, user):
        return ws_client(NotificationConsumer, user, '/ws/notifications/')

    async def open_chat(self, user):
        communicator = self.chat(user)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        ready = await communicator.receive_json_from()
        self.assertEqual(ready['type'], 'ready')
        return communicator, ready

    # ---- connect rules
    async def test_anonymous_is_rejected(self):
        connected, _ = await self.chat(AnonymousUser()).connect()
        self.assertFalse(connected)

    async def test_stranger_is_rejected(self):
        connected, _ = await self.chat(self.carol).connect()
        self.assertFalse(connected)

    async def test_unknown_conversation_is_rejected(self):
        communicator = ws_client(ChatConsumer, self.bob, '/ws/chat/999999/', conversation_id='999999')
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    async def test_participants_connect_and_get_state(self):
        for user in (self.alice, self.bob):
            communicator, ready = await self.open_chat(user)
            self.assertEqual((ready['can_send'], ready['blocked_by_me']), (True, False))
            await communicator.disconnect()

    async def test_ready_state_reflects_blocks(self):
        await database_sync_to_async(Block.objects.create)(blocker=self.alice, blocked=self.bob)
        alice, alice_state = await self.open_chat(self.alice)
        bob, bob_state = await self.open_chat(self.bob)
        self.assertEqual((alice_state['can_send'], alice_state['blocked_by_me']), (False, True))
        self.assertEqual((bob_state['can_send'], bob_state['blocked_by_me']), (False, False))
        await alice.disconnect()
        await bob.disconnect()

    # ---- messaging
    async def test_message_reaches_both_participants_and_is_stored(self):
        alice, _ = await self.open_chat(self.alice)
        bob, _ = await self.open_chat(self.bob)
        await bob.send_json_to({'type': 'message', 'text': '  hello <b>there</b>  '})
        for communicator in (alice, bob):
            event = await communicator.receive_json_from()
            self.assertEqual(event['type'], 'message')
            self.assertEqual(event['message']['text'], 'hello <b>there</b>')
            self.assertEqual(event['message']['sender_id'], self.bob.pk)
        stored = await database_sync_to_async(lambda: list(Message.objects.values_list('text', 'sender_id')))()
        self.assertEqual(stored, [('hello <b>there</b>', self.bob.pk)])
        await alice.disconnect()
        await bob.disconnect()

    async def test_invalid_input_is_rejected(self):
        bob, _ = await self.open_chat(self.bob)
        cases = [
            ({'type': 'message', 'text': ''}, 'empty'),
            ({'type': 'message', 'text': '   '}, 'empty'),
            ({'type': 'message'}, 'empty'),
            ({'type': 'message', 'text': 123}, 'invalid'),
            ({'type': 'message', 'text': 'x' * 2001}, 'too_long'),
            ({'type': 'nonsense'}, 'invalid'),
        ]
        for payload, code in cases:
            await bob.send_json_to(payload)
            event = await bob.receive_json_from()
            self.assertEqual((event['type'], event['code']), ('error', code), payload)
        await bob.send_to(text_data='this is not json')
        self.assertEqual((await bob.receive_json_from())['code'], 'invalid')
        await bob.send_to(text_data='[1, 2]')
        self.assertEqual((await bob.receive_json_from())['code'], 'invalid')
        await bob.send_to(text_data=json.dumps({'type': 'message', 'text': 'x' * 100000}))
        self.assertEqual((await bob.receive_json_from())['code'], 'too_long')
        self.assertEqual(await database_sync_to_async(Message.objects.count)(), 0)
        await bob.disconnect()

    @override_settings(CHAT_RATE_LIMIT_COUNT=2)
    async def test_rate_limit(self):
        bob, _ = await self.open_chat(self.bob)
        for index in range(2):
            await bob.send_json_to({'type': 'message', 'text': f'm{index}'})
            self.assertEqual((await bob.receive_json_from())['type'], 'message')
        await bob.send_json_to({'type': 'message', 'text': 'third'})
        event = await bob.receive_json_from()
        self.assertEqual((event['type'], event['code']), ('error', 'rate_limited'))
        self.assertEqual(await database_sync_to_async(Message.objects.count)(), 2)
        await bob.disconnect()

    async def test_blocked_user_cannot_send(self):
        bob, _ = await self.open_chat(self.bob)
        alice, _ = await self.open_chat(self.alice)
        await database_sync_to_async(Block.objects.create)(blocker=self.alice, blocked=self.bob)
        for communicator in (bob, alice):
            await communicator.send_json_to({'type': 'message', 'text': 'hi'})
            event = await communicator.receive_json_from()
            self.assertEqual((event['type'], event['code']), ('error', 'blocked'))
        self.assertEqual(await database_sync_to_async(Message.objects.count)(), 0)
        await bob.disconnect()
        await alice.disconnect()

    async def test_membership_is_rechecked_on_every_message(self):
        # The conversation disappears while the socket is open: nothing may be stored.
        bob, _ = await self.open_chat(self.bob)
        await database_sync_to_async(Conversation.objects.all().delete)()
        await bob.send_json_to({'type': 'message', 'text': 'hi'})
        event = await bob.receive_json_from()
        self.assertEqual((event['type'], event['code']), ('error', 'forbidden'))
        self.assertEqual(await database_sync_to_async(Message.objects.count)(), 0)
        await bob.disconnect()

    # ---- read receipts and notifications
    async def test_read_receipt_reaches_sender_and_updates_counters(self):
        message = await database_sync_to_async(self.add_message)(self.bob, 'unread one')
        alice_notifications = self.notifications(self.alice)
        connected, _ = await alice_notifications.connect()
        self.assertTrue(connected)
        self.assertEqual(await alice_notifications.receive_json_from(), {'type': 'unread', 'unread': 1})

        bob, _ = await self.open_chat(self.bob)
        alice, _ = await self.open_chat(self.alice)
        await alice.send_json_to({'type': 'read'})

        receipt = await bob.receive_json_from()
        self.assertEqual(receipt, {'type': 'read', 'reader_id': self.alice.pk, 'message_ids': [message.pk]})
        self.assertEqual(await alice_notifications.receive_json_from(), {'type': 'unread', 'unread': 0})
        stored = await database_sync_to_async(Message.objects.get)(pk=message.pk)
        self.assertIsNotNone(stored.read_at)
        await alice_notifications.disconnect()
        await bob.disconnect()
        await alice.disconnect()

    async def test_read_by_stranger_is_impossible(self):
        connected, _ = await self.chat(self.carol).connect()
        self.assertFalse(connected)

    async def test_notification_consumer_requires_login(self):
        connected, _ = await self.notifications(AnonymousUser()).connect()
        self.assertFalse(connected)

    async def test_new_message_pushes_counter_to_recipient_only(self):
        alice_notifications = self.notifications(self.alice)
        bob_notifications = self.notifications(self.bob)
        for communicator in (alice_notifications, bob_notifications):
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            self.assertEqual((await communicator.receive_json_from())['unread'], 0)

        bob, _ = await self.open_chat(self.bob)
        await bob.send_json_to({'type': 'message', 'text': 'ping'})
        await bob.receive_json_from()
        push = await alice_notifications.receive_json_from()
        self.assertEqual(push['type'], 'new_message')
        self.assertEqual(push['unread'], 1)
        self.assertEqual(push['conversation_id'], self.conversation.pk)
        self.assertEqual(push['preview'], 'ping')
        self.assertTrue(await bob_notifications.receive_nothing(timeout=0.2))
        await alice_notifications.disconnect()
        await bob_notifications.disconnect()
        await bob.disconnect()

    async def test_notification_consumer_answers_ping(self):
        communicator = self.notifications(self.alice)
        await communicator.connect()
        await communicator.receive_json_from()
        await communicator.send_json_to({'type': 'ping'})
        self.assertEqual(await communicator.receive_json_from(), {'type': 'pong'})
        await communicator.disconnect()

    # ---- HTTP -> WebSocket
    async def test_attachment_uploaded_over_http_is_broadcast_to_the_group(self):
        alice, _ = await self.open_chat(self.alice)

        def post_attachment():
            client = Client()
            client.force_login(self.bob)
            return client.post(
                reverse('chat:send', args=[self.conversation.pk]),
                {'text': 'see file', 'attachment': upload('photo.png', image_bytes())},
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        response = await database_sync_to_async(post_attachment)()
        self.assertEqual(response.status_code, 201)
        event = await alice.receive_json_from()
        self.assertEqual(event['type'], 'message')
        self.assertEqual(event['message']['text'], 'see file')
        self.assertEqual(event['message']['attachment']['name'], 'photo.png')
        self.assertTrue(event['message']['attachment']['is_image'])
        await alice.disconnect()

    async def test_attachment_over_http_is_not_broadcast_when_blocked(self):
        await database_sync_to_async(Block.objects.create)(blocker=self.alice, blocked=self.bob)
        alice, _ = await self.open_chat(self.alice)

        def post_attachment():
            client = Client()
            client.force_login(self.bob)
            return client.post(
                reverse('chat:send', args=[self.conversation.pk]),
                {'attachment': upload('photo.png', image_bytes())},
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        response = await database_sync_to_async(post_attachment)()
        self.assertEqual(response.status_code, 403)
        self.assertTrue(await alice.receive_nothing(timeout=0.2))
        await alice.disconnect()

    # ---- the real ASGI application: origin check + session auth
    async def test_origin_validation_and_session_auth_on_the_real_application(self):
        from config.asgi import application

        def session_cookie():
            client = Client()
            client.force_login(self.bob)
            return f"sessionid={client.cookies['sessionid'].value}".encode()

        cookie = await database_sync_to_async(session_cookie)()

        evil = WebsocketCommunicator(
            application, '/ws/notifications/', headers=[(b'origin', b'http://evil.example'), (b'cookie', cookie)],
        )
        self.assertFalse((await evil.connect())[0])

        anonymous = WebsocketCommunicator(application, '/ws/notifications/', headers=[(b'origin', b'http://localhost')])
        self.assertFalse((await anonymous.connect())[0])

        good = WebsocketCommunicator(
            application, '/ws/notifications/', headers=[(b'origin', b'http://localhost'), (b'cookie', cookie)],
        )
        connected, _ = await good.connect()
        self.assertTrue(connected)
        self.assertEqual((await good.receive_json_from())['type'], 'unread')
        await good.disconnect()

        chat = WebsocketCommunicator(
            application, self.path, headers=[(b'origin', b'http://localhost'), (b'cookie', cookie)],
        )
        connected, _ = await chat.connect()
        self.assertTrue(connected)
        self.assertEqual((await chat.receive_json_from())['type'], 'ready')
        await chat.disconnect()


class ServiceUnitTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.make_fixtures()

    def test_filename_sanitising(self):
        from .attachments import clean_filename, validate_attachment
        from .exceptions import ChatError
        self.assertEqual(clean_filename('../../etc/passwd.txt'), 'passwd.txt')
        self.assertEqual(clean_filename('C:\\Users\\x\\cv.pdf'), 'cv.pdf')
        self.assertEqual(clean_filename('a\x00b.png'), 'ab.png')
        self.assertEqual(clean_filename('..'), '')
        self.assertEqual(clean_filename('.png'), 'png')  # no extension left, so validation rejects it
        with self.assertRaises(ChatError):
            validate_attachment(upload('.png', image_bytes()))
        self.assertEqual(clean_filename('Резюме 1.PDF'), 'Резюме 1.pdf')
        self.assertLessEqual(len(clean_filename('a' * 500 + '.png')), 104)

    def test_blocked_users_helper_is_symmetric(self):
        self.assertFalse(services.users_blocked(self.alice, self.bob))
        Block.objects.create(blocker=self.alice, blocked=self.bob)
        self.assertTrue(services.users_blocked(self.alice, self.bob))
        self.assertTrue(services.users_blocked(self.bob, self.alice))
        self.assertFalse(services.users_blocked(self.alice, self.carol))
