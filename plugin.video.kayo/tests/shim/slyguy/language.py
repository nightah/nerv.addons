class BaseLanguage:
    def __call__(self, string, **kwargs):
        return f"{string} {kwargs}" if kwargs else f"{string}"
