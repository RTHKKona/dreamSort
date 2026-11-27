# small version + constraint handling, no external deps

import re


def _numeric(token):
    return int(token) if token.isdigit() else token


def parse_version(text):
    # dotted core plus optional prerelease; build metadata is dropped
    raw = str(text or "").strip().lower()
    if raw.startswith("v"):
        raw = raw[1:].strip()
    if not raw:
        return None
    core, sep, pre = raw.partition("-")
    core = core.partition("+")[0]
    parts = []
    for token in core.split("."):
        parts.append(_numeric(re.sub(r"[^0-9a-z]", "", token) or "0"))
    pre_parts = None
    if sep:
        pre = pre.partition("+")[0].strip()
        if pre:
            pre_parts = tuple(_numeric(t) for t in pre.split("."))
    return parts, pre_parts


def _sort_key(version):
    if version is None:
        return None
    core, pre = version
    pre_key = (1,) if pre is None else (0,) + tuple(
        (0, p) if isinstance(p, int) else (1, str(p)) for p in pre)
    return tuple(p if isinstance(p, int) else 0 for p in core), pre_key


def compare_versions(a, b):
    # -1 / 0 / 1, None treated as unknown
    ka, kb = _sort_key(a), _sort_key(b)
    if ka is None or kb is None:
        return 0
    core_a, pre_a = ka
    core_b, pre_b = kb
    width = max(len(core_a), len(core_b))
    pad_a = core_a + (0,) * (width - len(core_a))
    pad_b = core_b + (0,) * (width - len(core_b))
    if pad_a < pad_b:
        return -1
    if pad_a > pad_b:
        return 1
    if pre_a < pre_b:
        return -1
    if pre_a > pre_b:
        return 1
    return 0


_OPS = (">=", "<=", "==", "!=", ">", "<")


def _split_constraint(token):
    token = token.strip()
    for op in _OPS:
        if token.startswith(op):
            return op, token[len(op):].strip()
    # a bare version is a floor, so a newer release still satisfies it
    return ">=", token


def satisfies(version, constraint):
    # (matches, needs_warning); ">=*" and friends accept any version
    constraint = str(constraint or "").strip()
    if constraint in ("", "*"):
        return True, False
    tokens = []
    for token in constraint.split(","):
        token = token.strip()
        if not token:
            continue
        op, target = _split_constraint(token)
        tokens.append((op, target))
    if all(target in ("", "*") for _op, target in tokens):
        return True, False
    if version is not None and not isinstance(version, tuple):
        # "*" is a placeholder, not the number zero
        version = None if str(version).strip() in ("", "*") else parse_version(version)
    if version is None:
        return False, True
    for op, target in tokens:
        if target in ("", "*"):
            continue
        target_version = parse_version(target)
        cmp = compare_versions(version, target_version)
        holds = {
            ">=": cmp >= 0,
            "<=": cmp <= 0,
            "==": cmp == 0,
            "!=": cmp != 0,
            ">": cmp > 0,
            "<": cmp < 0,
        }.get(op, False)
        if not holds:
            return False, False
    return True, False
