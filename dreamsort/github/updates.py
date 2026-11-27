# release comparison

from ..gamebanana.policy import archive_usable
from ..rules.versions import compare_versions, parse_version

NONE = "unlinked"
UNKNOWN = "unknown"
NO_ASSET = "no_asset"
CURRENT = "up_to_date"
UPDATE = "update_available"


def usable_assets(release):
    # what dreamSort can open once downloaded
    assets = (release or {}).get("assets") or []
    return [asset for asset in assets if archive_usable(asset.get("name"))]


def pick_asset(release, want=""):
    # the asset we installed last, else the release build
    usable = usable_assets(release)
    want = str(want or "").strip().lower()
    if want:
        match = next((asset for asset in usable
                      if asset["name"].lower() == want), None)
        if match:
            return match
    if usable:
        # the build is usually the short name, not a source or debug archive
        return sorted(usable,
                      key=lambda asset: (len(asset["name"]),
                                         asset["name"].lower()))[0]
    # a source zipball is the repo, not an installable mod
    return None


def evaluate(record, release):
    # status and the asset that would replace the installed copy
    github = (record or {}).get("github") or {}
    if not github.get("repo"):
        return NONE, None
    tag = (release or {}).get("tag") or ""
    if not tag:
        return UNKNOWN, None
    installed = github.get("tag") or ""
    if not installed:
        # linked after the install, so there is nothing to compare against
        return NONE, None
    if compare_versions(parse_version(tag), parse_version(installed)) > 0:
        asset = pick_asset(release, github.get("asset", ""))
        return (UPDATE, asset) if asset else (NO_ASSET, None)
    return CURRENT, None
