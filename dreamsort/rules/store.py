# rule sources: built-in seeds, manifests, user overrides

from dataclasses import replace

from .model import ModRules, clean_folder


def _groups_from_options(manifest):
    options = manifest.get("options") or {}
    groups = {}
    for option, data in options.items():
        if isinstance(data, dict) and data.get("group"):
            node = "%s#%s" % (manifest["id"], option)
            groups.setdefault(str(data["group"]), []).append(node)
    return tuple(tuple(members) for members in groups.values())


def rules_from_manifest(manifest):
    if not manifest or not manifest.get("id"):
        return None
    return ModRules(
        mod_id=manifest["id"],
        version=manifest.get("version"),
        requires=dict(manifest.get("requires") or {}),
        conflicts=dict(manifest.get("conflicts") or {}),
        load_after=tuple(manifest.get("load_after") or ()),
        load_before=tuple(manifest.get("load_before") or ()),
        groups=_groups_from_options(manifest),
        name=manifest.get("name") or "",
        authors=tuple(manifest.get("authors") or ()),
        description=manifest.get("description") or "",
        page_url=manifest.get("page_url") or "",
        options=manifest.get("options") or {},
    )


# built-in library seed, replaces the old hardcoded list
SEED_RULES = {
    "katlib": ModRules(mod_id="katlib", name="KatLib"),
}


def merge_overrides(rules, overrides):
    # user config wins over manifests and seeds, malformed entries skipped
    merged = dict(rules)
    for mod_id, patch in (overrides or {}).items():
        if not isinstance(patch, dict):
            continue
        base = merged.get(mod_id) or ModRules(mod_id=str(mod_id))
        requires = dict(base.requires)
        extra = patch.get("requires")
        if isinstance(extra, dict):
            requires.update(extra)
        conflicts = dict(base.conflicts)
        extra = patch.get("conflicts")
        if isinstance(extra, dict):
            conflicts.update(extra)
        merged[str(mod_id)] = replace(base, requires=requires,
                                      conflicts=conflicts)
    return merged


def aliases_from_items(items):
    # folder name and gb record id -> canonical node
    aliases = {}
    for item in items:
        mod_id = item.get("mod_id")
        record = item.get("record") or {}
        folder = clean_folder(item.get("folder_name") or mod_id or "")
        if folder:
            aliases[folder] = mod_id
        gb_id = record.get("gb_mod_id")
        if gb_id:
            aliases[str(gb_id)] = mod_id
    return aliases


def load_overrides(config):
    rules = config.get("rules") if isinstance(config, dict) else None
    return rules if isinstance(rules, dict) else {}
