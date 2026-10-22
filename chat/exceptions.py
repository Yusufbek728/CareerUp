class ChatError(Exception):
    """A business-rule violation in the chat. `code` is stable and machine readable
    (clients localise by code); `message` is a (lazy) human readable text."""

    HTTP_STATUS = {
        'not_found': 404,
        'forbidden': 403,
        'blocked': 403,
        'muted': 403,
        'empty': 400,
        'too_long': 400,
        'invalid': 400,
        'bad_attachment': 400,
        'bad_request': 400,
        'rate_limited': 429,
    }

    def __init__(self, code, message=''):
        super().__init__(str(message) if message else code)
        self.code = code
        self.message = message

    @property
    def http_status(self):
        return self.HTTP_STATUS.get(self.code, 400)
