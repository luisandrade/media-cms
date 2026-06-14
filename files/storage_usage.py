import os

from django.conf import settings


BYTES_PER_GB = 1024 ** 3
STORAGE_LIMIT_MESSAGE = "No hay espacio de almacenamiento disponible para subir más videos."


def directory_size_bytes(path):
    total = 0

    try:
        entries = list(os.scandir(path))
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return 0

    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                total += directory_size_bytes(entry.path)
            elif entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
        except (FileNotFoundError, PermissionError, OSError):
            continue

    return total


def media_storage_paths():
    media_root = getattr(settings, "MEDIA_ROOT", "")
    encoded_dir = os.path.join(media_root, getattr(settings, "MEDIA_ENCODING_DIR", "encoded/"))
    live_record_dir = os.path.join(media_root, "live_record")
    return encoded_dir, live_record_dir


def media_storage_limit_bytes():
    limit_gb = float(getattr(settings, "MEDIA_STORAGE_LIMIT_GB", 1000) or 0)
    return max(0, int(limit_gb * BYTES_PER_GB))


def media_storage_used_bytes():
    return sum(directory_size_bytes(path) for path in media_storage_paths())


def get_media_storage_usage():
    limit_bytes = media_storage_limit_bytes()
    used_bytes = media_storage_used_bytes()
    remaining_bytes = max(0, limit_bytes - used_bytes)
    used_percent = (used_bytes / limit_bytes * 100) if limit_bytes else 0

    return {
        "used_bytes": used_bytes,
        "limit_bytes": limit_bytes,
        "remaining_bytes": remaining_bytes,
        "used_gb": used_bytes / BYTES_PER_GB,
        "limit_gb": limit_bytes / BYTES_PER_GB if limit_bytes else 0,
        "remaining_gb": remaining_bytes / BYTES_PER_GB,
        "used_percent": min(100, used_percent),
        "folders": ["encoded", "live_record"],
    }


def media_storage_has_capacity(incoming_bytes=0):
    limit_bytes = media_storage_limit_bytes()
    if limit_bytes <= 0:
        return False
    incoming_bytes = max(0, int(incoming_bytes or 0))
    used_bytes = media_storage_used_bytes()
    if incoming_bytes:
        return used_bytes + incoming_bytes <= limit_bytes
    return used_bytes < limit_bytes
