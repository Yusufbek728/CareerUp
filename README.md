# CareerUp

## Render deployment

Set these environment variables in the Render service:

- `SECRET_KEY`: a new random Django secret
- `DEBUG`: `False`
- `SUPER_ADMIN_USERNAME`: the administrator login
- `SUPER_ADMIN_PASSWORD`: the administrator password

Uploaded images are stored in `media/`. Add a Render Persistent Disk mounted at
`/opt/render/project/src/media`; otherwise uploaded images are deleted whenever
the service is redeployed or moved to another instance.

Use this build command so the administrator is created without Render Shell:

```text
pip install -r requirements.txt && python -m babel.messages.frontend compile -d locale -D django && python manage.py migrate && python manage.py ensure_admin && python manage.py collectstatic --noinput
```

The start command can be:

```text
gunicorn config.wsgi:application
```