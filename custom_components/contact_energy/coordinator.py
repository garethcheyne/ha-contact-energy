"""Data update coordinator for Contact Energy."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .api import ContactEnergyApi, ContactEnergyAuthError, ContactEnergyConnectionError
from .const import (
    ALL_STATISTIC_IDS,
    CONF_OFFPEAK_RATE,
    CONF_PEAK_RATE,
    CONF_USAGE_DAYS,
    CURRENCY,
    DEFAULT_OFFPEAK_RATE,
    DEFAULT_PEAK_RATE,
    DEFAULT_USAGE_DAYS,
    DOMAIN,
    FETCH_CHUNK_DAYS,
    HISTORY_EMPTY_STOP_DAYS,
    STATISTIC_OFFPEAK,
    STATISTIC_OFFPEAK_COST,
    STATISTIC_PEAK,
    STATISTIC_PEAK_COST,
    UPDATE_INTERVAL,
)
from .data import (
    NZ_TZ,
    ContactEnergyData,
    UsagePoint,
    choose_usage,
    cumulative_statistics,
    parse_points,
    resolve_rates,
    summarise,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StatisticSeries:
    """One external statistic written from the hourly usage points."""

    statistic_id: str
    name: str
    offpeak: bool
    value: str  # UsagePoint field: "kwh" or "cost"
    unit: str
    unit_class: str | None


STATISTIC_SERIES = (
    StatisticSeries(
        STATISTIC_PEAK, "Contact Energy", False, "kwh",
        UnitOfEnergy.KILO_WATT_HOUR, EnergyConverter.UNIT_CLASS,
    ),
    StatisticSeries(
        STATISTIC_OFFPEAK, "Contact Energy Free", True, "kwh",
        UnitOfEnergy.KILO_WATT_HOUR, EnergyConverter.UNIT_CLASS,
    ),
    # Currencies have no unit converter, so unit_class is None.
    StatisticSeries(STATISTIC_PEAK_COST, "Contact Energy Cost", False, "cost", CURRENCY, None),
    StatisticSeries(STATISTIC_OFFPEAK_COST, "Contact Energy Free Cost", True, "cost", CURRENCY, None),
)

type ContactEnergyConfigEntry = ConfigEntry[ContactEnergyCoordinator]


def entry_settings(entry: ConfigEntry) -> dict:
    """Return config entry data with options layered on top."""
    return {**entry.data, **entry.options}


class ContactEnergyCoordinator(DataUpdateCoordinator[ContactEnergyData]):
    """Fetches usage once per update and shares it with every sensor."""

    config_entry: ContactEnergyConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ContactEnergyConfigEntry, api: ContactEnergyApi
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        # Serialises statistics writes between scheduled updates and the
        # import service, so running sums are always read after the last write.
        self.statistics_lock = asyncio.Lock()
        # None until checked: does Contact return hourly data for multi-day requests?
        self._range_supported: bool | None = None
        self.import_task: asyncio.Task[dict] | None = None
        self.import_state: dict[str, Any] = {
            "status": "idle",
            "progress": 0,
            "days_requested": None,
            "last_import": None,
            "last_result": None,
            "error": None,
        }
        self._progress_listeners: set[Callable[[float], None]] = set()
        # (oldest, newest) day with statistics stored, or None.
        self.history_range: tuple[date, date] | None = None

    @property
    def usage_days(self) -> int:
        """Number of days fetched on each update."""
        return int(entry_settings(self.config_entry).get(CONF_USAGE_DAYS, DEFAULT_USAGE_DAYS))

    async def _async_update_data(self) -> ContactEnergyData:
        """Fetch the latest data from Contact Energy."""
        try:
            points = await self.hass.async_add_executor_job(
                self.fetch_points, self.usage_days, True
            )
        except ContactEnergyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ContactEnergyConnectionError as err:
            raise UpdateFailed(str(err)) from err

        latest = summarise(points)
        if latest is None:
            _LOGGER.warning(
                "No usage data returned for the last %d day(s); keeping the previous values",
                self.usage_days,
            )
        else:
            async with self.statistics_lock:
                await async_write_statistics(self.hass, latest.points)
        try:
            self.history_range = await async_history_range(self.hass)
        except Exception:  # informational only
            _LOGGER.debug("Could not read the stored history range", exc_info=True)

        settings = entry_settings(self.config_entry)
        bill = dict(self.api.bill_details)
        return ContactEnergyData(
            usage=choose_usage(self.data.usage if self.data else None, latest),
            rates=resolve_rates(
                settings.get(CONF_PEAK_RATE),
                settings.get(CONF_OFFPEAK_RATE),
                bill,
                DEFAULT_PEAK_RATE,
                DEFAULT_OFFPEAK_RATE,
            ),
            plan=dict(self.api.plan_details),
            bill=bill,
            account_id=self.api.account_id,
            contract_id=self.api.contract_id,
        )

    # --- Fetching (blocking; run in the executor) --------------------------

    def ensure_session(self, refresh_account: bool = False) -> None:
        """Log in if needed; optionally refresh plan and bill details."""
        api = self.api
        if not api.is_logged_in:
            api.authenticate()  # also refreshes plan and bill details
        elif refresh_account:
            api.get_plan_details()
            api.get_bill_details()
            if not api.is_logged_in:  # the token had expired
                api.authenticate()

    def fetch_points(self, days: int, refresh_account: bool = False) -> list[UsagePoint]:
        """Fetch hourly usage for the last `days` full NZ days.

        Logs in when there is no session, and logs in again if the session
        expires part way through.
        """
        self.ensure_session(refresh_account)
        end = datetime.now(NZ_TZ).date() - timedelta(days=1)
        start = end - timedelta(days=days - 1)
        points: list[UsagePoint] = []
        for chunk_start, chunk_end in date_chunks(start, end, FETCH_CHUNK_DAYS):
            points.extend(self.fetch_range(chunk_start, chunk_end))
        return points

    def fetch_range(self, start: date, end: date) -> list[UsagePoint]:
        """Fetch hourly usage for start..end inclusive.

        Uses one multi-day request when Contact supports it. The first time,
        the result is checked against day-by-day requests; if they differ
        (or the request fails) every later fetch goes day by day.
        """
        if start == end or self._range_supported is False:
            return self._fetch_days(start, end)
        if self._range_supported is None:
            by_day = self._fetch_days(start, end)
            if by_day:
                ranged = self._fetch_range_once(start, end)
                self._range_supported = ranged is not None and _same_points(by_day, ranged)
                _LOGGER.debug(
                    "Contact multi-day usage requests %s (%s to %s: %d points day by day, %s in one request%s)",
                    "work" if self._range_supported else "don't match; fetching day by day",
                    start,
                    end,
                    len(by_day),
                    "failed" if ranged is None else f"{len(ranged)} points",
                    ""
                    if not ranged
                    else f", days {sorted({p.start.date().isoformat() for p in ranged})}, "
                    f"first {ranged[0].start.isoformat()} {ranged[0].kwh} kWh",
                )
            return by_day
        ranged = self._fetch_range_once(start, end)
        return ranged if ranged is not None else self._fetch_days(start, end)

    def _fetch_range_once(self, start: date, end: date) -> list[UsagePoint] | None:
        response = self._with_reauth(lambda: self.api.get_usage_range(start, end))
        if response is False:
            return None
        return [p for p in parse_points(response) if start <= p.start.date() <= end]

    def _fetch_days(self, start: date, end: date) -> list[UsagePoint]:
        points: list[UsagePoint] = []
        day = start
        while day <= end:
            args = (str(day.year), str(day.month), str(day.day))
            points.extend(parse_points(self._with_reauth(lambda: self.api.get_usage(*args)) or []))
            day += timedelta(days=1)
        return points

    def _with_reauth(self, call):
        """Make an API call, logging in again once if the token was rejected."""
        response = call()
        if response is False and not self.api.is_logged_in:
            self.api.authenticate()
            response = call()
        return response

    # --- History import ------------------------------------------------------

    @property
    def import_running(self) -> bool:
        """True while a history import is in progress."""
        return self.import_task is not None and not self.import_task.done()

    @callback
    def async_add_progress_listener(self, listener: Callable[[float], None]) -> Callable[[], None]:
        """Call `listener` with the import progress (0-1); returns a remover."""
        self._progress_listeners.add(listener)
        return lambda: self._progress_listeners.discard(listener)

    @callback
    def async_start_history_import(self, days: int, clear: bool) -> asyncio.Task[dict]:
        """Start a history import in the background and return its task.

        The task belongs to the config entry, so closing the dialog that
        started it doesn't stop it.
        """
        if self.import_running:
            raise HistoryImportRunning
        self.import_task = self.config_entry.async_create_background_task(
            self.hass, self._async_run_import(days, clear), f"{DOMAIN} history import"
        )
        return self.import_task

    async def _async_run_import(self, days: int, clear: bool) -> dict:
        state = self.import_state
        state.update(status="running", progress=0, days_requested=days, error=None)
        self.async_update_listeners()
        try:
            summary = await self._async_import(days, clear)
        except ContactEnergyAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            self._import_failed(f"Contact Energy login failed: {err}")
            raise HomeAssistantError(f"Contact Energy login failed: {err}") from err
        except ContactEnergyConnectionError as err:
            self._import_failed(f"Could not reach Contact Energy: {err}")
            raise HomeAssistantError(f"Could not reach Contact Energy: {err}") from err
        except Exception as err:
            self._import_failed(str(err) or type(err).__name__)
            raise
        state.update(
            status="idle", progress=100, last_import=dt_util.utcnow(), last_result=summary, error=None
        )
        self.async_update_listeners()
        _LOGGER.info("History import finished: %s", summary)
        return summary

    def _import_failed(self, message: str) -> None:
        self.import_state.update(status="failed", error=message, last_import=dt_util.utcnow())
        self.async_update_listeners()
        _LOGGER.warning("History import failed: %s", message)

    async def _async_import(self, days: int, clear: bool) -> dict:
        """Fetch newest to oldest, stop when Contact runs out of data, then write."""
        hass = self.hass
        await hass.async_add_executor_job(self.ensure_session)
        end = datetime.now(NZ_TZ).date() - timedelta(days=1)
        earliest = end - timedelta(days=days - 1)

        points: list[UsagePoint] = []
        seen_data = False
        empty_run = 0
        stopped_early = False
        fetched = 0
        for chunk_start, chunk_end in reversed(date_chunks(earliest, end, FETCH_CHUNK_DAYS)):
            chunk = await hass.async_add_executor_job(self.fetch_range, chunk_start, chunk_end)
            points.extend(chunk)
            days_with_data = {p.start.date() for p in chunk}
            day = chunk_end
            while day >= chunk_start:
                if day in days_with_data:
                    seen_data, empty_run = True, 0
                elif seen_data:
                    empty_run += 1
                day -= timedelta(days=1)
            fetched += (chunk_end - chunk_start).days + 1
            self._report_progress(fetched / days)
            if seen_data and empty_run >= HISTORY_EMPTY_STOP_DAYS:
                stopped_early = True
                break

        if not points:
            raise HomeAssistantError(f"Contact Energy returned no usage for the last {days} days")

        async with self.statistics_lock:
            if clear:
                # Queued on the recorder ahead of the import, so it always lands first.
                get_instance(hass).async_clear_statistics(list(ALL_STATISTIC_IDS))
            await async_write_statistics(hass, points, reset=clear)
        self.history_range = await async_history_range(hass)

        oldest = min(p.start for p in points).date()
        newest = max(p.start for p in points).date()
        return {
            "days_requested": days,
            "days_imported": len({p.start.date() for p in points}),
            "hours_imported": len(points),
            "oldest": oldest.isoformat(),
            "newest": newest.isoformat(),
            "kwh": round(sum(p.kwh for p in points), 3),
            "cost_nzd": round(sum(p.cost for p in points), 2),
            "cleared_existing": clear,
            # Set when Contact has no data before `oldest`.
            "contact_history_starts": oldest.isoformat() if stopped_early else None,
        }

    def _report_progress(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, fraction))
        self.import_state["progress"] = round(fraction * 100)
        for listener in list(self._progress_listeners):
            listener(fraction)
        self.async_update_listeners()


class HistoryImportRunning(HomeAssistantError):
    """A history import is already in progress."""


def date_chunks(start: date, end: date, size: int) -> list[tuple[date, date]]:
    """Split start..end (inclusive) into consecutive chunks of up to `size` days."""
    chunks = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=size - 1))
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return chunks


def _same_points(a: list[UsagePoint], b: list[UsagePoint]) -> bool:
    return {(p.start, p.kwh, p.cost) for p in a} == {(p.start, p.kwh, p.cost) for p in b}


RECORDER_WAIT_TIMEOUT = 60


async def _async_wait_for_recorder(hass: HomeAssistant) -> None:
    """Wait until statistics already queued on the recorder are committed.

    Skipped while Home Assistant is starting: the recorder doesn't commit
    until startup has finished, so waiting then would block this
    integration's setup (and Home Assistant's startup) until startup times
    out. Nothing of ours is pending at that point anyway.
    """
    if not hass.is_running:
        return
    try:
        async with asyncio.timeout(RECORDER_WAIT_TIMEOUT):
            await get_instance(hass).async_block_till_done()
    except TimeoutError:
        _LOGGER.debug("Timed out waiting for the recorder; reading stored statistics anyway")


async def async_history_range(hass: HomeAssistant) -> tuple[date, date] | None:
    """Return the oldest and newest NZ day with usage statistics stored."""
    recorder = get_instance(hass)
    await _async_wait_for_recorder(hass)
    last = await recorder.async_add_executor_job(
        get_last_statistics, hass, 1, STATISTIC_PEAK, True, {"sum"}
    )
    if not (rows := last.get(STATISTIC_PEAK)):
        return None
    newest_ts = rows[0]["start"]
    # Find the first month with data, then the first day within it.
    months = await recorder.async_add_executor_job(
        statistics_during_period,
        hass, dt_util.utcnow() - timedelta(days=3650), None, {STATISTIC_PEAK}, "month", None, {"sum"},
    )
    if not (month_rows := months.get(STATISTIC_PEAK)):
        return None
    # Month and day rows follow Home Assistant's time zone, which may not be
    # NZ, so narrow down to the first hourly row for an exact NZ date.
    month_start = dt_util.utc_from_timestamp(month_rows[0]["start"])
    days = await recorder.async_add_executor_job(
        statistics_during_period,
        hass, month_start, month_start + timedelta(days=32), {STATISTIC_PEAK}, "day", None, {"sum"},
    )
    day_start = (
        dt_util.utc_from_timestamp(days[STATISTIC_PEAK][0]["start"]) if days.get(STATISTIC_PEAK) else month_start
    )
    hours = await recorder.async_add_executor_job(
        statistics_during_period,
        hass, day_start, day_start + timedelta(days=2), {STATISTIC_PEAK}, "hour", None, {"sum"},
    )
    oldest_ts = hours[STATISTIC_PEAK][0]["start"] if hours.get(STATISTIC_PEAK) else day_start.timestamp()
    return (
        datetime.fromtimestamp(oldest_ts, NZ_TZ).date(),
        datetime.fromtimestamp(newest_ts, NZ_TZ).date(),
    )


async def _async_sum_before(hass: HomeAssistant, statistic_id: str, start: datetime) -> float:
    """Return the running sum recorded before `start` (0 when there is none)."""
    recorder = get_instance(hass)
    # Make sure earlier queued imports are committed before reading sums back.
    await _async_wait_for_recorder(hass)

    last = await recorder.async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum"}
    )
    rows = last.get(statistic_id)
    if not rows:
        return 0.0
    if rows[0]["start"] < start.timestamp():
        return rows[0].get("sum") or 0.0

    # The new data overlaps what is stored: find the last hourly row before it.
    # Every hour gets a row, so a short look-back almost always finds one; the
    # long one only runs when there is nothing just before the window (e.g. on
    # the first day after setup, where it finds nothing and the sum starts at 0).
    # Only hourly rows are used: a daily or monthly row would also cover hours
    # inside the window being rewritten.
    for lookback in (timedelta(days=3), timedelta(days=3650)):
        result = await recorder.async_add_executor_job(
            statistics_during_period,
            hass,
            start - lookback,
            start,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        if earlier := [row for row in result.get(statistic_id, []) if row["start"] < start.timestamp()]:
            return earlier[-1].get("sum") or 0.0
    return 0.0


async def async_write_statistics(
    hass: HomeAssistant, points: tuple[UsagePoint, ...] | list[UsagePoint], *, reset: bool = False
) -> None:
    """Import hourly usage into the Energy Dashboard statistics.

    Must be called from the event loop. With reset=True the running sums start
    at zero (used right after the statistics have been cleared).
    """
    if not points:
        return
    first = min(p.start for p in points)
    for series in STATISTIC_SERIES:
        base_sum = 0.0 if reset else await _async_sum_before(hass, series.statistic_id, first)
        rows = cumulative_statistics(
            points, offpeak=series.offpeak, base_sum=base_sum, value=series.value
        )
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=series.name,
            source=DOMAIN,
            statistic_id=series.statistic_id,
            unit_class=series.unit_class,
            unit_of_measurement=series.unit,
        )
        async_add_external_statistics(
            hass, metadata, [StatisticData(**row) for row in rows]
        )
        _LOGGER.debug("Queued %d hourly statistics for %s", len(rows), series.statistic_id)
