from slyguy.settings import CommonSettings
from slyguy.settings.types import Enum

from .constants import LOGIN_EMAIL, LOGIN_QR
from .language import _


class Settings(CommonSettings):
    LOGIN_METHOD = Enum(
        "login_method",
        _.LOGIN_METHOD,
        options=[[_.LOGIN_QR, LOGIN_QR], [_.LOGIN_EMAIL, LOGIN_EMAIL]],
        default=LOGIN_QR,
    )


settings = Settings()
