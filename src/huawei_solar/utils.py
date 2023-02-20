"""
Generic Utilities
"""

from datetime import datetime, tzinfo
import typing as t


def get_local_timezone() -> t.Optional[tzinfo]:
    """Returns the current local timezone"""
    return datetime.now().astimezone().tzinfo
