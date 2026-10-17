from slyguy.language import BaseLanguage


class Language(BaseLanguage):
    LOGIN_FAILED = 30000
    REFRESH_FAILED = 30001
    PLAYBACK_ERROR = 30002
    DEVICE_CODE = 30003
    NEXT_PAGE = 30004


_ = Language()
