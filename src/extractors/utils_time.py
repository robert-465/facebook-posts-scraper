import logging
from datetime import datetime, timezone
from typing import Union

logger = logging.getLogger(__name__)

def now_timestamp() -> int:
    """Return the current UTC timestamp as an integer."""
    return int(datetime.now(tz=timezone.utc).timestamp())

def parse_timestamp(value: Union[int, float, str, datetime]) -> int:
    """
    Normalize different timestamp formats into a UNIX timestamp (seconds).

    Supported:
    - int/float: assumed to already be a UNIX timestamp (seconds).
    - datetime: converted to UTC then timestamp.
    - str: several ISO-8601 / simple formats, or integer-like string.
    """
    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return int(value.timestamp())

    if isinstance(value, str):
        stripped = value.strip()
        # integer-like?
        if stripped.isdigit():
            return int(stripped)

        # Try a few common date-time formats
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(stripped, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
            except ValueError:
                continue

    logger.warning("Could not parse timestamp value %r, falling back to 'now'.", value)
    return now_timestamp()