import os

from django.http import FileResponse, Http404, HttpResponseRedirect

from .attachments import CONTENT_TYPES


def attachment_response(message):
    """Serve a message attachment (the caller has already checked access).

    The content type comes from the validated extension, not from the client. Images are
    shown inline, everything else is forced to download."""
    if not message.attachment:
        raise Http404
    extension = os.path.splitext(message.attachment_name or '')[1].lstrip('.').lower()
    content_type = CONTENT_TYPES.get(extension, 'application/octet-stream')
    try:
        path = message.attachment.path
    except NotImplementedError:
        # Remote storage (Cloudinary): there is no local file, hand out the storage URL.
        return HttpResponseRedirect(message.attachment.url)
    try:
        handle = open(path, 'rb')
    except FileNotFoundError:
        raise Http404
    response = FileResponse(
        handle,
        as_attachment=not message.attachment_is_image,
        filename=message.attachment_name or os.path.basename(path),
        content_type=content_type,
    )
    response['Cache-Control'] = 'private, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
