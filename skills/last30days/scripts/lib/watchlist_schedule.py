"""Five-field UTC cron matching for watchlist polling; no provider calls."""

from datetime import datetime, timezone


def _field(expression: str, low: int, high: int) -> set[int]:
    values = set()
    try:
        for part in expression.split(","):
            pieces = part.split("/")
            if len(pieces) > 2:
                raise ValueError
            step = int(pieces[1]) if len(pieces) == 2 else 1
            if step < 1:
                raise ValueError
            base = pieces[0]
            if base == "*":
                start, end = low, high
            elif "-" in base:
                start, end = map(int, base.split("-"))
            else:
                start = int(base)
                end = high if len(pieces) == 2 else start
            if not low <= start <= end <= high:
                raise ValueError
            values.update(range(start, end + 1, step))
    except (ValueError, TypeError):
        raise ValueError("Schedule requires five numeric cron fields with valid ranges/steps") from None
    return values


def parse_schedule(schedule: str) -> list[set[int]]:
    parts = schedule.split()
    if len(parts) != 5:
        raise ValueError("Schedule requires five numeric UTC cron fields")
    return [_field(part, *bounds) for part, bounds in zip(
        parts, [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
    )]


def schedule_due(topic: dict, now: datetime | None = None) -> bool:
    schedule = topic.get("schedule") or "0 8 * * *"
    minute, hour, dom, month, dow = parse_schedule(schedule)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    weekday = (now.weekday() + 1) % 7
    day_matches = now.day in dom
    week_matches = weekday in dow or (weekday == 0 and 7 in dow)
    parts = schedule.split()
    # Standard cron: restricted day-of-month and weekday fields combine with OR.
    if not parts[2].startswith("*") and not parts[4].startswith("*"):
        date_matches = day_matches or week_matches
    else:
        date_matches = day_matches and week_matches
    if not (now.minute in minute and now.hour in hour and now.month in month and date_matches):
        return False
    if topic.get("last_run"):
        try:
            last = datetime.fromisoformat(topic["last_run"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)  # SQLite datetime('now')
        except (ValueError, TypeError):
            raise ValueError("Invalid last_run timestamp; inspect topic before retrying") from None
        if last >= now.replace(second=0, microsecond=0):
            return False
    return True
