import random

import requests
import urllib3
from requests.adapters import HTTPAdapter

# Mirror script.module.slyguy's TLS setup: Kayo's WAF rejects the default Python/OpenSSL fingerprint on the
# sign-in and Playback endpoints, but accepts SlyGuy's shuffled cipher list.
SSL_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-SHA:"
    "ECDHE-ECDSA-AES256-SHA:ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256:AES256-GCM-SHA384:"
    "AES128-SHA:AES256-SHA"
).split(":")
random.shuffle(SSL_CIPHERS)
SSL_CIPHERS = ":".join(SSL_CIPHERS) + "@SECLEVEL=0"

SSL_OPTIONS = (
    urllib3.util.ssl_.OP_NO_SSLv2
    | urllib3.util.ssl_.OP_NO_SSLv3
    | urllib3.util.ssl_.OP_NO_COMPRESSION
    | urllib3.util.ssl_.OP_NO_TICKET
)


class _SSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = urllib3.util.ssl_.create_urllib3_context(ciphers=SSL_CIPHERS, options=SSL_OPTIONS)
        return super().init_poolmanager(*args, **kwargs)


class Session(requests.Session):
    def __init__(self, headers=None, **kwargs):
        super().__init__()
        self.headers.update(headers or {})
        self.mount("https://", _SSLAdapter())

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", 30)
        return super().request(method, url, **kwargs)
