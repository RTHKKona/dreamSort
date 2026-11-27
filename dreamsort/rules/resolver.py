# dependency and conflict resolver, pure python

from .model import Plan, Violation
from .versions import satisfies


def _resolve(ref, aliases):
    return (aliases or {}).get(ref, ref)


def _reverse_requires(rules, aliases):
    out = {}
    for node, rule in rules.items():
        for ref in rule.requires:
            out.setdefault(_resolve(ref, aliases), set()).add(node)
    return out


def _needed(mod, proposed, rules, aliases):
    for node in proposed:
        rule = rules.get(node)
        if rule and _resolve(mod, aliases) in {
                _resolve(ref, aliases) for ref in rule.requires}:
            return True
    return False


def _closure(rules, aliases, installed, start):
    # transitive requires; only a back edge on the current path is a cycle
    visited, missing, blocked, cycles = [], [], [], []
    seen, path = set(), []

    def walk(ref):
        node = _resolve(ref, aliases)
        if node in path:
            cycles.append(tuple(path[path.index(node):] + [node]))
            return
        if node in seen:
            return
        seen.add(node)
        visited.append(node)
        rule = rules.get(node)
        if rule is None:
            return
        path.append(node)
        for dep, constraint in rule.requires.items():
            req = _resolve(dep, aliases)
            if req in path:
                cycles.append(tuple(path[path.index(req):] + [req]))
                continue
            if req not in installed:
                if req not in missing:
                    missing.append(req)
            else:
                req_rule = rules.get(req)
                version = req_rule.version if req_rule else None
                ok, warn = satisfies(version, constraint)
                if not ok and not warn:
                    blocked.append((node, "needs %s %s, installed %s"
                                    % (req, constraint, version or "unknown")))
            walk(req)
        path.pop()

    walk(start)
    return visited, missing, blocked, cycles


def plan_enable(installed, enabled, rules, target, aliases=None):
    aliases = aliases or {}
    visited, missing, blocked, cycles = _closure(
        rules, aliases, set(installed), target)
    proposed = set(enabled) | set(visited)
    disable = []

    for node in list(visited):
        rule = rules.get(node)
        if not rule:
            continue
        for ref, constraint in rule.conflicts.items():
            other = _resolve(ref, aliases)
            if other == node or other not in proposed:
                continue
            if _needed(other, proposed, rules, aliases):
                blocked.append((node, "conflicts with %s, which another "
                                      "enabled mod needs" % other))
            elif other not in disable:
                disable.append(other)

    for node, rule in rules.items():
        if node not in proposed:
            continue
        for ref in rule.conflicts:
            other = _resolve(ref, aliases)
            if other in visited and node not in disable:
                if _needed(node, proposed, rules, aliases):
                    blocked.append((other, "conflicts with %s, which another "
                                           "enabled mod needs" % node))
                elif node not in disable:
                    disable.append(node)

    group_members = {}
    for node in proposed:
        rule = rules.get(node)
        if not rule:
            continue
        for group in rule.groups:
            group_members.setdefault(group, []).append(node)
    for members in group_members.values():
        active = [m for m in members if m in proposed]
        for extra in active[1:]:
            if not _needed(extra, proposed, rules, aliases):
                disable.append(extra)

    return Plan(enable=visited, disable=disable, missing=missing,
                blocked=blocked, cycles=cycles)


def plan_disable(installed, enabled, rules, target, aliases=None):
    aliases = aliases or {}
    target = _resolve(target, aliases)
    reverse = _reverse_requires(rules, aliases)
    dependents = [d for d in reverse.get(target, set()) if d in enabled]
    if dependents:
        return Plan(blocked=[(target, "still required by enabled mods: %s"
                              % ", ".join(sorted(dependents)))])
    return Plan(disable=[target])


def _find_cycles(rules, aliases=None):
    # loop detection over resolved refs, one report per distinct loop
    aliases = aliases or {}
    cycles = []
    reported = set()
    state = {}

    def dfs(node, path):
        state[node] = 1
        path.append(node)
        rule = rules.get(node)
        if rule:
            for dep in rule.requires:
                ref = _resolve(dep, aliases)
                if state.get(ref) == 1:
                    loop = path[path.index(ref):] + [ref]
                    key = frozenset(loop)
                    if key not in reported:
                        reported.add(key)
                        cycles.append(loop)
                elif state.get(ref, 0) == 0 and ref in rules:
                    dfs(ref, path)
        path.pop()
        state[node] = 2

    for node in rules:
        if state.get(node, 0) == 0:
            dfs(node, [])
    return cycles


def validate(installed, enabled, rules, aliases=None, order=None):
    aliases = aliases or {}
    violations = []
    enabled = set(enabled)

    for node in enabled:
        rule = rules.get(node)
        if not rule:
            continue
        for ref, constraint in rule.requires.items():
            req = _resolve(ref, aliases)
            if req not in installed:
                violations.append(Violation(
                    "MISSING_REQUIRED", "error", node,
                    "requires %s which is not installed" % req))
            elif req not in enabled:
                violations.append(Violation(
                    "REQUIRED_DISABLED", "warning", node,
                    "%s is installed but disabled" % req))
            else:
                req_rule = rules.get(req)
                version = req_rule.version if req_rule else None
                ok, warn = satisfies(version, constraint)
                if not ok:
                    violations.append(Violation(
                        "VERSION_MISMATCH", "warning" if warn else "error", node,
                        "%s needs %s %s" % (node, req, constraint)))
        for ref, constraint in rule.conflicts.items():
            other = _resolve(ref, aliases)
            if other == node:
                # a mod listing itself is a typo, not a real conflict
                continue
            if other in enabled:
                other_rule = rules.get(other)
                version = other_rule.version if other_rule else None
                match, _ = satisfies(version, constraint)
                if match:
                    violations.append(Violation(
                        "ACTIVE_CONFLICT", "error", node,
                        "conflicts with %s" % other))

    group_members = {}
    for node in enabled:
        rule = rules.get(node)
        if not rule:
            continue
        for group in rule.groups:
            group_members.setdefault(group, []).append(node)
    for group, members in group_members.items():
        if len(members) > 1:
            violations.append(Violation(
                "GROUP_VIOLATION", "error", members[0],
                "group %s has more than one enabled: %s"
                % (group, ", ".join(members))))

    for cycle in _find_cycles(rules, aliases):
        # only a loop that is fully switched on can block an apply
        if not all(node in enabled for node in cycle):
            continue
        violations.append(Violation(
            "CYCLE", "error", cycle[0],
            "requires cycle: %s" % " -> ".join(cycle)))

    if order:
        index = {mod: i for i, mod in enumerate(order)}
        for node in enabled:
            rule = rules.get(node)
            if not rule or node not in index:
                continue
            for ref in rule.load_after:
                other = _resolve(ref, aliases)
                if other in enabled and other in index and index[node] <= index[other]:
                    violations.append(Violation(
                        "ORDER_VIOLATION", "warning", node,
                        "should load after %s" % other))
            for ref in rule.load_before:
                other = _resolve(ref, aliases)
                if other in enabled and other in index and index[node] >= index[other]:
                    violations.append(Violation(
                        "ORDER_VIOLATION", "warning", node,
                        "should load before %s" % other))

    return violations
