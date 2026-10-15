import json
import os

_PATH = os.environ.get("KAYO_USERDATA", os.path.join(os.path.dirname(__file__), "..", "..", ".userdata.json"))


def _load():
    try:
        with open(_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def get(key, default=None):
    return _load().get(key, default)


def set(key, value):
    data = _load()
    data[key] = value
    with open(_PATH, "w") as f:
        json.dump(data, f)
    os.chmod(_PATH, 0o600)


def delete(key):
    data = _load()
    data.pop(key, None)
    with open(_PATH, "w") as f:
        json.dump(data, f)
