import requests


class Session(requests.Session):
    def __init__(self, headers=None, **kwargs):
        super().__init__()
        self.headers.update(headers or {})

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", 30)
        return super().request(method, url, **kwargs)
