"""Validation of chat attachments: extension whitelist, size limit and content sniffing."""
import os
import re
import zipfile
from dataclasses import dataclass

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .exceptions import ChatError

ALLOWED_EXTENSIONS = ('jpg', 'jpeg', 'png', 'webp', 'pdf', 'doc', 'docx', 'txt')

# Content type that is sent back when an attachment is downloaded. Derived from the
# validated extension, never from what the client declared.
CONTENT_TYPES = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'webp': 'image/webp',
    'pdf': 'application/pdf',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'txt': 'text/plain; charset=utf-8',
}
IMAGE_FORMATS = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP'}
OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
MAX_UNCOMPRESSED_DOCX_BYTES = 100 * 1024 * 1024
MAX_NAME_LENGTH = 100


@dataclass(frozen=True)
class ValidAttachment:
    name: str          # sanitised display name (no path components)
    extension: str     # lower case, without a dot
    size: int
    content_type: str


def max_bytes():
    return settings.CHAT_ATTACHMENT_MAX_BYTES


def clean_filename(raw_name):
    """Strip any path (both / and \\ separators), control characters and odd symbols.

    Returns ('stem.ext') or '' when nothing usable is left."""
    name = (raw_name or '').replace('\\', '/').split('/')[-1]
    name = re.sub(r'[\x00-\x1f\x7f]', '', name).strip().strip('.')
    stem, ext = os.path.splitext(name)
    stem = re.sub(r'[^\w\- ().]', '_', stem, flags=re.UNICODE).strip(' .')
    ext = re.sub(r'[^A-Za-z0-9.]', '', ext)
    if not stem:
        return ''
    return f'{stem[:MAX_NAME_LENGTH]}{ext.lower()}'


def _bad(message):
    return ChatError('bad_attachment', message)


def validate_attachment(uploaded):
    """Return ValidAttachment or raise ChatError('bad_attachment', ...)."""
    size = getattr(uploaded, 'size', None)
    if size is None:
        raise _bad(_('Could not read the uploaded file.'))
    if size <= 0:
        raise _bad(_('The file is empty.'))
    if size > max_bytes():
        raise _bad(_('The file is too large (maximum %(mb)s MB).') % {'mb': max_bytes() // (1024 * 1024)})

    name = clean_filename(getattr(uploaded, 'name', ''))
    extension = os.path.splitext(name)[1].lstrip('.').lower()
    if not name or extension not in ALLOWED_EXTENSIONS:
        raise _bad(_('This file type is not allowed. Allowed: %(types)s.') % {
            'types': ', '.join(ALLOWED_EXTENSIONS),
        })

    try:
        uploaded.seek(0)
        head = uploaded.read(4096)
        uploaded.seek(0)
        if extension in IMAGE_FORMATS:
            _check_image(uploaded, IMAGE_FORMATS[extension])
        elif extension == 'pdf':
            if b'%PDF-' not in head[:1024]:
                raise _bad(_('The file content does not match its type.'))
        elif extension == 'doc':
            if not head.startswith(OLE_MAGIC):
                raise _bad(_('The file content does not match its type.'))
        elif extension == 'docx':
            _check_docx(uploaded)
        elif extension == 'txt':
            if b'\x00' in uploaded.read():
                raise _bad(_('The file content does not match its type.'))
    finally:
        try:
            uploaded.seek(0)
        except Exception:  # pragma: no cover - defensive
            pass

    return ValidAttachment(name=name, extension=extension, size=size, content_type=CONTENT_TYPES[extension])


def _check_image(uploaded, expected_format):
    from PIL import Image

    try:
        with Image.open(uploaded) as image:
            actual_format = image.format
            image.verify()
    except Exception:
        raise _bad(_('The file is not a valid image.'))
    if actual_format != expected_format:
        raise _bad(_('The file content does not match its type.'))


def _check_docx(uploaded):
    try:
        with zipfile.ZipFile(uploaded) as archive:
            infos = archive.infolist()
            names = {info.filename for info in infos}
            if '[Content_Types].xml' not in names or not any(n.startswith('word/') for n in names):
                raise _bad(_('The file content does not match its type.'))
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_DOCX_BYTES:
                raise _bad(_('The file content does not match its type.'))
    except zipfile.BadZipFile:
        raise _bad(_('The file content does not match its type.'))
