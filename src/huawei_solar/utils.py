"""Generic Utilities."""

from datetime import datetime, tzinfo


def get_local_timezone() -> tzinfo:
    """Return the current local timezone."""
    local_timezone = datetime.now().astimezone().tzinfo

    if not local_timezone:
        raise ValueError
    return local_timezone
