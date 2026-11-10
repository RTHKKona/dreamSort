# drop payloads

from PySide6.QtCore import QMimeData

MOD_ROW_MIME = "application/x-dreamsort-modrow"


def has_local_urls(mime: QMimeData) -> bool:
    # local paths only
    if not mime.hasUrls():
        return False
    urls = mime.urls()
    if not urls:
        return False
    return all(url.isLocalFile() for url in urls)


def paths_from_mime(mime: QMimeData) -> list:
    return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]


def has_mod_row(mime: QMimeData) -> bool:
    return mime.hasFormat(MOD_ROW_MIME)


def mod_id_from_mime(mime: QMimeData) -> str:
    raw = mime.data(MOD_ROW_MIME)
    if raw is None:
        return ""
    try:
        return bytes(raw.data()).decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return ""
