import logging
import os
import threading
import time
import urllib.request

from django.apps import AppConfig

logger = logging.getLogger(__name__)

# Render's free tier suspends a service after 15 minutes without inbound traffic.
KEEP_ALIVE_INTERVAL = 10 * 60


def _keep_alive_loop(url):
    while True:
        time.sleep(KEEP_ALIVE_INTERVAL)
        try:
            urllib.request.urlopen(url, timeout=30).close()
        except Exception as exc:
            logger.warning('Keep-alive ping failed: %s', exc)


class MainappConfig(AppConfig):
    name = 'mainapp'

    def ready(self):
        # Render sets RENDER_EXTERNAL_URL; locally it is absent, so no pings are sent.
        url = os.environ.get('RENDER_EXTERNAL_URL')
        if url:
            threading.Thread(target=_keep_alive_loop, args=(url,), daemon=True).start()
