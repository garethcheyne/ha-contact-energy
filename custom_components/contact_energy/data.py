"""Parsing and aggregation of Contact Energy usage data.

Deliberately free of Home Assistant imports so it can be unit tested on its own.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
import logging
from zoneinfo import ZoneInfo

_LOGGER = logging.getLogger(__name__)

# Contact's plan times (e.g. "9PM - 7AM") are New Zealand local time,
# whatever time zone Home Assistant itself is configured for.
NZ_TZ = ZoneInfo("Pacific/Auckland")

API_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"


@dataclass(frozen=True)
class UsagePoint:
    """One hour of usage."""

    start: datetime  # time-zone aware, top of the hour
    kwh: float
    cost: float
    offpeak: bool


@dataclass(frozen=True)
class UsageSummary:
    """Aggregates over the fetched usage window."""

    points: tuple[UsagePoint, ...]
    peak_kwh: float
    offpeak_kwh: float
    latest_day: date | None
    latest_day_kwh: float
    latest_day_cost: float
    offpeak_window: tuple[int, int] | None  # (start hour, end hour), NZ time

    @property
    def total_kwh(self) -> float:
        """Total usage in the window."""
        return self.peak_kwh + self.offpeak_kwh


@dataclass(frozen=True)
class Rates:
    """Per-kWh rates in NZD and where they came from."""

    peak: float
    offpeak: float
    source: str  # "configured", "bill" or "default"


@dataclass(frozen=True)
class ContactEnergyData:
    """Everything the sensors read from the coordinator."""

    usage: UsageSummary | None
    rates: Rates
    plan: dict = field(default_factory=dict)
    bill: dict = field(default_factory=dict)
    account_id: str = ""
    contract_id: str = ""


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_points(raw_points: Iterable[dict] | None) -> list[UsagePoint]:
    """Convert raw API data points into UsagePoints, skipping unusable ones."""
    points: list[UsagePoint] = []
    for raw in raw_points or []:
        if not isinstance(raw, dict):
            continue
        kwh = _to_float(raw.get("value"))
        if kwh is None:
            continue  # hour not published yet
        try:
            start = datetime.strptime(raw["date"], API_DATE_FORMAT)
        except (KeyError, TypeError, ValueError):
            _LOGGER.debug("Skipping data point with unparseable date: %s", raw.get("date"))
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=NZ_TZ)
        points.append(
            UsagePoint(
                start=start.replace(minute=0, second=0, microsecond=0),
                kwh=kwh,
                cost=_to_float(raw.get("dollarValue")) or 0.0,
                offpeak=(_to_float(raw.get("offpeakValue")) or 0.0) > 0,
            )
        )
    return points


def detect_offpeak_window(points: Iterable[UsagePoint]) -> tuple[int, int] | None:
    """Work out the off-peak hours (start, end) from one day's points.

    The end hour is exclusive, so (21, 7) means 9pm until 7am.
    """
    hours = sorted({p.start.hour for p in points if p.offpeak})
    if not hours:
        return None
    if 0 in hours and 23 in hours:
        # The window wraps midnight: it starts after the first gap.
        for i in range(len(hours) - 1):
            if hours[i + 1] - hours[i] > 1:
                return hours[i + 1], hours[i] + 1
        return 0, 0  # every hour is off-peak
    return hours[0], (hours[-1] + 1) % 24


def is_offpeak_hour(hour: int, window: tuple[int, int] | None) -> bool:
    """Return True if the given NZ hour falls inside the off-peak window."""
    if window is None:
        return False
    start, end = window
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def summarise(points: Iterable[UsagePoint]) -> UsageSummary | None:
    """Aggregate usage points; returns None when there are none."""
    ordered = tuple(sorted(points, key=lambda p: p.start))
    if not ordered:
        return None

    by_day: dict[date, list[UsagePoint]] = {}
    for point in ordered:
        by_day.setdefault(point.start.date(), []).append(point)

    latest_day = max(
        (day for day, pts in by_day.items() if sum(p.kwh for p in pts) > 0),
        default=None,
    )
    latest_points = by_day.get(latest_day, []) if latest_day else []

    # Use the most recent day that shows any off-peak hours.
    window = None
    for day in sorted(by_day, reverse=True):
        if (window := detect_offpeak_window(by_day[day])) is not None:
            break

    return UsageSummary(
        points=ordered,
        peak_kwh=sum(p.kwh for p in ordered if not p.offpeak),
        offpeak_kwh=sum(p.kwh for p in ordered if p.offpeak),
        latest_day=latest_day,
        latest_day_kwh=sum(p.kwh for p in latest_points),
        latest_day_cost=sum(p.cost for p in latest_points),
        offpeak_window=window,
    )


def choose_usage(previous: UsageSummary | None, latest: UsageSummary | None) -> UsageSummary | None:
    """Keep the last good usage when a fetch comes back completely empty."""
    return latest if latest is not None else previous


def cumulative_statistics(
    points: Iterable[UsagePoint], *, offpeak: bool, base_sum: float, value: str = "kwh"
) -> list[dict]:
    """Build hourly statistics rows with a running sum.

    `value` is the UsagePoint field to accumulate: "kwh" or "cost".
    Every hour gets a row in both series (0 when the hour belongs to the
    other series) so each series is continuous and the running sum always
    carries on from the previous hour.
    """
    rows = []
    running = base_sum
    for point in sorted(points, key=lambda p: p.start):
        amount = getattr(point, value) if point.offpeak == offpeak else 0.0
        running += amount
        rows.append({"start": point.start, "state": amount, "sum": running})
    return rows


def resolve_rates(
    peak_override: float | None,
    offpeak_override: float | None,
    bill: dict | None,
    default_peak: float,
    default_offpeak: float,
) -> Rates:
    """Pick rates: user override, then the bill, then the defaults."""
    bill = bill or {}
    bill_peak = bill.get("peak_rate") or 0.0
    bill_offpeak = bill.get("offpeak_rate") or 0.0

    if bill_peak > 0:
        peak, offpeak, source = bill_peak, bill_offpeak, "bill"
    else:
        peak, offpeak, source = default_peak, default_offpeak, "default"

    if peak_override is not None:
        peak, source = peak_override, "configured"
    if offpeak_override is not None:
        offpeak, source = offpeak_override, "configured"
    return Rates(peak=peak, offpeak=offpeak, source=source)


def parse_bill_date(value: str | None) -> date | None:
    """Parse a bill date such as 2026-02-17T00:00:00+13:00."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
