def cached(*args, **kwargs):
    return lambda f: f


def empty():
    pass
