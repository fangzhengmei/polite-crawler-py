"""DateTime utilities for consistent timestamp handling.

This module provides utilities to handle datetime operations consistently
while addressing the deprecation of datetime.utcnow() in Python 3.12+.

All timestamps in this project use naive datetime (without timezone info)
but represent UTC time. This maintains backward compatibility with existing
data while avoiding deprecation warnings.
"""

from datetime import datetime, UTC


def utc_now() -> datetime:
    """Get current UTC time as a naive datetime.

    This function addresses the deprecation of datetime.utcnow() in Python 3.12+
    while maintaining semantic equivalence:
    - Returns a naive datetime (without timezone info)
    - The value represents the current UTC time

    Equivalent behavior to the deprecated datetime.utcnow():
    - datetime.utcnow() -> naive datetime, UTC value
    - utc_now() -> naive datetime, UTC value

    Returns:
        A naive datetime representing the current UTC time.
    """
    return datetime.now(UTC).replace(tzinfo=None)
