# rules model, plain data

import re
from dataclasses import dataclass, field

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
_FOLDER_PREFIX = re.compile(r"^~?\d*[_\-\s]*")


def normalize_id(text):
    return str(text or "").strip().lower()


def valid_id(text):
    # canonical author/mod id; option suffix stays after #
    raw = str(text or "").strip()
    if any(char.isupper() for char in raw):
        return False
    node = raw.lower().split("#", 1)[0]
    return bool(_ID_RE.match(node))


def clean_folder(name):
    # folder fallback identity, strip flags and numbering
    value = normalize_id(name)
    value = _FOLDER_PREFIX.sub("", value)
    return value.strip("._-")


@dataclass(frozen=True)
class ModRules:
    mod_id: str
    version: str = None
    requires: dict = field(default_factory=dict)
    conflicts: dict = field(default_factory=dict)
    load_after: tuple = ()
    load_before: tuple = ()
    groups: tuple = ()
    name: str = ""
    authors: tuple = ()
    description: str = ""
    page_url: str = ""
    options: dict = field(default_factory=dict)


@dataclass
class Plan:
    enable: list = field(default_factory=list)
    disable: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    blocked: list = field(default_factory=list)
    cycles: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.blocked


@dataclass
class Violation:
    kind: str
    severity: str
    mod: str
    message: str
