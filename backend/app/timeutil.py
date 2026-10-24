from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; everything we store is UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def to_local(dt: datetime, tz: str) -> datetime:
    return as_utc(dt).astimezone(ZoneInfo(tz))


def local_day_bounds(day: date, tz: str) -> tuple[datetime, datetime]:
    """UTC instants for [day 00:00, next day 00:00) in the given zone."""
    zone = ZoneInfo(tz)
    start = datetime.combine(day, time.min, zone)
    end = datetime.combine(date.fromordinal(day.toordinal() + 1), time.min, zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def demo_now(today: date, tz: str, hour: int = 8) -> datetime:
    """The fixed demo clock: `today` at 08:00 local, as UTC."""
    return datetime.combine(today, time(hour), ZoneInfo(tz)).astimezone(UTC)
