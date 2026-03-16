"""Time utility functions."""
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_jst() -> datetime:
    return datetime.now(JST)


def utc_to_jst(dt: datetime) -> datetime:
    return dt.astimezone(JST)
