# username redaction

import getpass
import os
import re

PLACEHOLDER = "[Username]"

_SEPARATORS = re.compile(r"([\\/])")


def _home():
    try:
        return os.path.normpath(os.path.expanduser("~"))
    except Exception:
        return ""


def _username():
    home = _home()
    name = os.path.basename(home) if home else ""
    if not name:
        try:
            name = getpass.getuser()
        except Exception:
            name = ""
    return name


def redact_path(path):
    # swap the folder and name
    if not path:
        return ""
    text = str(path)
    home = _home()
    if home and text[:len(home)].casefold() == home.casefold():
        text = os.path.join(os.path.dirname(home), PLACEHOLDER) + text[len(home):]
    name = _username()
    if name:
        pieces = _SEPARATORS.split(text)
        for index, piece in enumerate(pieces):
            if piece.casefold() == name.casefold():
                pieces[index] = PLACEHOLDER
        text = "".join(pieces)
    return text


def unredact_path(text):
    # put the name back
    if not text or PLACEHOLDER not in text:
        return text
    name = _username()
    if not name:
        return text
    pattern = re.compile(re.escape(PLACEHOLDER), re.IGNORECASE)
    return pattern.sub(lambda _match: name, text)


def expand_path(text):
    # config values
    if not text:
        return ""
    return os.path.expanduser(unredact_path(text))
