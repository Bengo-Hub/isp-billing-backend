"""Datetime utilities for handling timezone-aware and timezone-naive datetime objects."""

from datetime import datetime
from typing import Optional


def normalize_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert timezone-aware datetime to timezone-naive UTC datetime.
    
    This function ensures all datetime objects are timezone-naive for database compatibility.
    PostgreSQL with asyncpg requires consistent timezone handling.
    
    Args:
        dt: Datetime object that may be timezone-aware or timezone-naive
        
    Returns:
        Timezone-naive datetime in UTC, or None if input is None
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # Convert to UTC and remove timezone info
        return datetime(*dt.utctimetuple()[:6])
    return dt


def ensure_timezone_naive(*datetimes: Optional[datetime]) -> tuple:
    """Normalize multiple datetime objects to timezone-naive.
    
    Args:
        *datetimes: Variable number of datetime objects
        
    Returns:
        Tuple of normalized datetime objects
    """
    return tuple(normalize_datetime(dt) for dt in datetimes)
