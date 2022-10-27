"""
Generic Utilities
"""

from datetime import datetime, tzinfo


def get_local_timezone() -> tzinfo:
    """Returns the current local timezone"""
    return datetime.now().astimezone().tzinfo
