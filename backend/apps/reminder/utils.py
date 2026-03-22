# backend/apps/reminder/utils.py
#
# Utility functions for the Reminder app.
# Handles time calculations, random time generation, and repeat schedule computation.

import random
import logging
from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Try to import pytz, fall back to zoneinfo for Python 3.9+
try:
    import pytz
    USE_PYTZ = True
except ImportError:
    from zoneinfo import ZoneInfo
    USE_PYTZ = False


def get_timezone(timezone_str: str):
    """
    Get a timezone object from a timezone string.
    
    Args:
        timezone_str: Timezone string (e.g., "Europe/Berlin", "America/New_York")
        
    Returns:
        Timezone object (pytz timezone or ZoneInfo)
    """
    if USE_PYTZ:
        return pytz.timezone(timezone_str)
    else:
        return ZoneInfo(timezone_str)


def localize_datetime(dt: datetime, timezone_str: str) -> datetime:
    """
    Localize a naive datetime to a specific timezone.
    
    Args:
        dt: Naive datetime object
        timezone_str: Timezone string
        
    Returns:
        Timezone-aware datetime
    """
    tz = get_timezone(timezone_str)
    if USE_PYTZ:
        return tz.localize(dt)
    else:
        return dt.replace(tzinfo=tz)


def parse_specific_datetime(datetime_str: str, timezone_str: str) -> int:
    """
    Parse a specific datetime string and convert to Unix timestamp.
    
    Args:
        datetime_str: ISO 8601 datetime string (e.g., "2026-02-05T14:30:00")
        timezone_str: User's timezone
        
    Returns:
        Unix timestamp (seconds)
        
    Raises:
        ValueError: If datetime string is invalid
    """
    try:
        # Try parsing with timezone info first
        if "+" in datetime_str or "Z" in datetime_str:
            dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
        else:
            # Parse as naive datetime and localize to user's timezone
            dt = datetime.fromisoformat(datetime_str)
            dt = localize_datetime(dt, timezone_str)
        
        return int(dt.timestamp())
    except Exception as e:
        logger.error(f"Error parsing datetime '{datetime_str}': {e}")
        raise ValueError(f"Invalid datetime format: {datetime_str}")


def calculate_random_trigger(
    start_date: str,
    end_date: str,
    timezone_str: str,
    time_window_start: Optional[str] = None,
    time_window_end: Optional[str] = None
) -> Tuple[int, Dict[str, Any]]:
    """
    Calculate a random trigger time within a date range and optional time window.
    
    The algorithm:
    1. Pick a random date between start_date and end_date (inclusive)
    2. Pick a random time within the time window on that date
    3. Convert to UTC timestamp
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        timezone_str: User's timezone
        time_window_start: Optional earliest time (HH:MM, 24h format), defaults to "00:00"
        time_window_end: Optional latest time (HH:MM, 24h format), defaults to "23:59"
        
    Returns:
        Tuple of (unix_timestamp, random_config_dict)
        
    Raises:
        ValueError: If dates or times are invalid
    """
    try:
        # Default time windows
        if not time_window_start:
            time_window_start = "00:00"
        if not time_window_end:
            time_window_end = "23:59"
        
        # Parse dates
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        if end < start:
            raise ValueError(f"End date {end_date} cannot be before start date {start_date}")
        
        # Parse times
        t_start = datetime.strptime(time_window_start, "%H:%M").time()
        t_end = datetime.strptime(time_window_end, "%H:%M").time()
        
        if t_end < t_start:
            raise ValueError(f"End time {time_window_end} cannot be before start time {time_window_start}")
        
        # Pick random date
        days_diff = (end - start).days
        random_day_offset = random.randint(0, days_diff)
        random_date = start + timedelta(days=random_day_offset)
        
        # Pick random time within window (in minutes from midnight)
        start_minutes = t_start.hour * 60 + t_start.minute
        end_minutes = t_end.hour * 60 + t_end.minute
        random_minutes = random.randint(start_minutes, end_minutes)
        
        random_hour = random_minutes // 60
        random_minute = random_minutes % 60
        random_time = time(random_hour, random_minute)
        
        # Combine date and time
        random_dt = datetime.combine(random_date, random_time)
        
        # Localize to user's timezone
        local_dt = localize_datetime(random_dt, timezone_str)
        
        # Build random_config for storage (needed for recalculating repeats)
        random_config = {
            "start_date": start_date,
            "end_date": end_date,
            "time_window_start": time_window_start,
            "time_window_end": time_window_end,
            "timezone": timezone_str
        }
        
        return int(local_dt.timestamp()), random_config
        
    except Exception as e:
        logger.error(f"Error calculating random trigger: {e}")
        raise ValueError(f"Invalid random trigger configuration: {e}")


def calculate_next_repeat_time(
    current_trigger_at: int,
    repeat_config: Dict[str, Any],
    timezone_str: str,
    random_config: Optional[Dict[str, Any]] = None
) -> Optional[int]:
    """
    Calculate the next trigger time for a repeating reminder.
    
    Args:
        current_trigger_at: Current trigger timestamp
        repeat_config: Repeat configuration dict
        timezone_str: User's timezone
        random_config: If present, recalculate random time for random triggers
        
    Returns:
        Next trigger timestamp, or None if repeat should end
    """
    try:
        repeat_type = repeat_config.get("type")
        end_date_str = repeat_config.get("end_date")
        # Note: max_occurrences is handled by the calling task, not here
        
        # Get timezone
        tz = get_timezone(timezone_str)
        
        # Convert current trigger to local datetime
        if USE_PYTZ:
            current_dt = datetime.fromtimestamp(current_trigger_at, tz)
        else:
            current_dt = datetime.fromtimestamp(current_trigger_at, tz)
        
        # Calculate next occurrence based on repeat type
        if repeat_type == "daily":
            next_dt = current_dt + timedelta(days=1)
            
        elif repeat_type == "weekly":
            next_dt = current_dt + timedelta(weeks=1)
            
        elif repeat_type == "monthly":
            # Move to same day next month
            day_of_month = repeat_config.get("day_of_month", current_dt.day)
            next_month = current_dt.month + 1
            next_year = current_dt.year
            
            if next_month > 12:
                next_month = 1
                next_year += 1
            
            # Handle months with fewer days
            import calendar
            max_day = calendar.monthrange(next_year, next_month)[1]
            actual_day = min(day_of_month, max_day)
            
            next_dt = current_dt.replace(year=next_year, month=next_month, day=actual_day)
            
        elif repeat_type == "custom":
            interval = repeat_config.get("interval", 1)
            interval_unit = repeat_config.get("interval_unit", "days")
            
            if interval_unit == "days":
                next_dt = current_dt + timedelta(days=interval)
            elif interval_unit == "weeks":
                next_dt = current_dt + timedelta(weeks=interval)
            elif interval_unit == "months":
                # Custom months calculation
                months_to_add = interval
                next_month = current_dt.month + months_to_add
                next_year = current_dt.year
                
                while next_month > 12:
                    next_month -= 12
                    next_year += 1
                
                import calendar
                max_day = calendar.monthrange(next_year, next_month)[1]
                actual_day = min(current_dt.day, max_day)
                
                next_dt = current_dt.replace(year=next_year, month=next_month, day=actual_day)
            else:
                logger.error(f"Unknown interval unit: {interval_unit}")
                return None
        else:
            logger.error(f"Unknown repeat type: {repeat_type}")
            return None
        
        # Check end date constraint
        if end_date_str:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            if next_dt.date() > end_date:
                logger.debug(f"Repeat ended: next date {next_dt.date()} > end date {end_date}")
                return None
        
        # For random triggers, we might want to recalculate a random time
        # For now, keep the same time pattern but advance the date
        # Future enhancement: recalculate random time within the daily window
        
        return int(next_dt.timestamp())
        
    except Exception as e:
        logger.error(f"Error calculating next repeat time: {e}", exc_info=True)
        return None


def format_reminder_time(timestamp: int, timezone_str: str) -> str:
    """
    Format a timestamp for display in a user-friendly format.
    
    Args:
        timestamp: Unix timestamp
        timezone_str: User's timezone
        
    Returns:
        Formatted datetime string (e.g., "Feb 5, 2026 at 2:30 PM")
    """
    try:
        tz = get_timezone(timezone_str)
        if USE_PYTZ:
            dt = datetime.fromtimestamp(timestamp, tz)
        else:
            dt = datetime.fromtimestamp(timestamp, tz)
        
        return dt.strftime("%b %d, %Y at %I:%M %p")
    except Exception as e:
        logger.error(f"Error formatting reminder time: {e}")
        return f"Timestamp: {timestamp}"


def validate_timezone(timezone_str: str) -> bool:
    """
    Validate that a timezone string is valid.
    
    Args:
        timezone_str: Timezone string to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        get_timezone(timezone_str)
        return True
    except Exception:
        return False


def get_common_timezones() -> list:
    """
    Get a list of common timezone names for user selection.
    
    Returns:
        List of timezone strings
    """
    return [
        "UTC",
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Toronto",
        "America/Vancouver",
        "Europe/London",
        "Europe/Paris",
        "Europe/Berlin",
        "Europe/Amsterdam",
        "Europe/Rome",
        "Europe/Madrid",
        "Europe/Stockholm",
        "Asia/Tokyo",
        "Asia/Shanghai",
        "Asia/Hong_Kong",
        "Asia/Singapore",
        "Asia/Seoul",
        "Asia/Dubai",
        "Asia/Kolkata",
        "Australia/Sydney",
        "Australia/Melbourne",
        "Pacific/Auckland",
    ]
