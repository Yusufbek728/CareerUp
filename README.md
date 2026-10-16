# CareerUp

## Render deployment

Set these environment variables in the Render service:

- `SECRET_KEY`: a new random Django secret
- `DEBUG`: `False`
- `SUPER_ADMIN_USERNAME`: the administrator login
- `SUPER_ADMIN_PASSWORD`: the administrator password
- `CLOUDINARY_URL`: the Cloudinary connection URL for permanent image storage
- `REDIS_URL` (optional, see "Chat" below): a Redis connection URL for the chat channel layer

When `CLOUDINARY_URL` is set, uploaded images are stored permanently in
Cloudinary. Without it, local development uses the `media/` directory.

Use this build command so the administrator is created without Render Shell:

```text
pip install -r requirements.txt && python -m babel.messages.frontend compile -d locale -D django && python manage.py migrate && python manage.py ensure_admin && python manage.py collectstatic --noinput
```

The chat uses WebSockets, so the service must run as an ASGI application. The start
command is now:

```text
python -m daphne -b 0.0.0.0 -p $PORT --proxy-headers config.asgi:application
```

(`gunicorn config.wsgi:application` still serves the site, but WebSocket connections
will fail with it, so the chat would only work through plain page reloads / HTTP.)

## Chat

Users start a private dialog from a listing page (the "Write a message" button writes to
the listing owner). Pages: `/messages/` and `/messages/<id>/`. REST API (JWT, HTTP only):
`/api/conversations/`, `/api/conversations/<id>/messages/`, `/api/blocks/`,
`/api/reports/`. WebSocket endpoints: `/ws/chat/<id>/` and `/ws/notifications/`
(session cookie authentication, the `Origin` must be one of `ALLOWED_HOSTS`).

Reported messages appear in Django admin under "Reports" for moderation.

Attachments (jpg, png, webp, pdf, doc, docx, txt, up to 5 MB) are stored through the
configured storage: Cloudinary (raw resources) when `CLOUDINARY_URL` is set, otherwise
the `media/` directory. They are downloaded through an authenticated view, not by a
public URL. Limits (`CHAT_MESSAGE_MAX_LENGTH`, `CHAT_ATTACHMENT_MAX_BYTES`,
`CHAT_RATE_LIMIT_COUNT`, `CHAT_RATE_LIMIT_WINDOW`) are in `config/settings.py`.

### Channel layer: `REDIS_URL`

Real-time delivery goes through a Channels channel layer.

- With `REDIS_URL` set (for example the Internal URL of a Render Key Value / Redis
  instance, `redis://...` or `rediss://...`), `channels_redis` is used. This is required
  for production as soon as more than one server process or instance is running.
- Without `REDIS_URL` the in-memory layer is used. It works only inside a single
  process: messages are delivered live only between users connected to the same process,
  nothing is shared between several workers/instances, and the state is lost on restart.
  That is fine for local development (`python manage.py runserver` is ASGI-aware
  thanks to `daphne` in `INSTALLED_APPS`) and for a single-instance, single-process
  deployment. Messages are always saved in the database first, so with a missing or
  partial layer nothing is lost: the chat page catches up over HTTP after a reconnect and
  the unread counters are recalculated on every page load.

When Redis is unavailable at runtime, sending still works (messages are stored); only
the live push is skipped.
