from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


def validate_image_size(file):
    """Reject uploads larger than MAX_IMAGE_SIZE. Used on model ImageFields, so forms and DRF both enforce it."""
    if file.size > MAX_IMAGE_SIZE:
        raise ValidationError(_('Image is too large. Maximum size is %(max)d MB.'), params={'max': MAX_IMAGE_SIZE // (1024 * 1024)})
