"""Data update coordinator for Contact Energy."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging

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
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.unit_conversion import EnergyConverter

from .api import ContactEnergyApi, ContactEnergyAuthError, ContactEnergyConnectionError
from .const import (
    CONF_OFFPEAK_RATE,
    CONF_PEAK_RATE,
    CONF_USAGE_DAYS,
    DEFAULT_OFFPEAK_RATE,
    DEFAULT_PEAK_RATE,
    CURRENCY,
    DEFAULT_USAGE_DAYS,
    DOMAIN,
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

    def fetch_points(self, days: int, refresh_account: bool = False) -> list[UsagePoint]:
        """Fetch hourly usage for the last `days` full NZ days (blocking).

        Logs in when there is no session, and logs in again if the session
        expires part way through.
        """
        api = self.api
        if not api.is_logged_in:
            api.authenticate()  # also refreshes plan and bill details
        elif refresh_account:
            api.get_plan_details()
            api.get_bill_details()
            if not api.is_logged_in:  # the token had expired
                api.authenticate()

        today = datetime.now(NZ_TZ).date()
        points: list[UsagePoint] = []
        for offset in range(days, 0, -1):
            day = today - timedelta(days=offset)
            points.extend(parse_points(self._get_usage(day)))
        return points

    def _get_usage(self, day: date) -> list:
        """Fetch one day, logging in again once if the token was rejected."""
        args = (str(day.year), str(day.month), str(day.day))
        response = self.api.get_usage(*args)
        if response is False and not self.api.is_logged_in:
            self.api.authenticate()
            response = self.api.get_usage(*args)
        return response or []


async def _async_sum_before(hass: HomeAssistant, statistic_id: str, start: datetime) -> float:
    """Return the running sum recorded before `start` (0 when there is none)."""
    recorder = get_instance(hass)
    # Make sure earlier queued imports are committed before reading sums back.
    await recorder.async_block_till_done()

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
