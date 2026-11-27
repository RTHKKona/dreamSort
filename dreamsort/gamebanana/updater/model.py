# update state for the ui

from ..updates import CHOICE, CURRENT, GONE, UNKNOWN, UPDATE

LABELS = {
    UPDATE: ("update", "update"),
    CHOICE: ("pick a file", "choice"),
    GONE: ("file gone", "muted"),
}

BUSY = ("queued", "waiting_for_disk", "downloading", "staging", "committing")


def badge(status, knowledge, operation="idle"):
    # text and chip kind for one row, or nothing
    if operation in BUSY:
        return operation.replace("_", " "), "update"
    if status in LABELS:
        return LABELS[status]
    if status == UNKNOWN and knowledge == "failed":
        return "check failed", "muted"
    return "", "none"


def badges(items, operations=None):
    operations = operations or {}
    return {folder_id: badge(item["status"], item["knowledge"],
                             operations.get(folder_id, "idle"))
            for folder_id, item in items.items()}


def summary(items):
    # counts for the bar text
    return {
        "updates": sum(1 for item in items.values()
                       if item["status"] == UPDATE),
        "choices": sum(1 for item in items.values()
                       if item["status"] == CHOICE),
        "current": sum(1 for item in items.values()
                       if item["status"] == CURRENT),
        "linked": sum(1 for item in items.values() if item["page_id"]),
    }
