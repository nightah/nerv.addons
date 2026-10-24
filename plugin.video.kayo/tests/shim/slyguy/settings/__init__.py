class _Value:
    def __init__(self, value):
        self.value = value


class CommonSettings:
    # The SlyGuy codec settings the API reads, at their defaults
    H265 = _Value(True)
    AC3 = _Value(True)
    EC3 = _Value(True)
