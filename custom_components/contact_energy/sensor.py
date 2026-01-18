"""Contact Energy sensors."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=3)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Contact Energy sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    usage_days = data["usage_days"]

    sensors = [
        ContactEnergyUsageSensor(entry, api, usage_days),
    ]

    async_add_entities(sensors, True)


class ContactEnergyUsageSensor(SensorEntity):
    """Contact Energy Usage sensor."""

    _attr_has_entity_name = True
    _attr_name = "Energy Usage"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:meter-electric"

    def __init__(self, entry: ConfigEntry, api, usage_days: int) -> None:
        """Initialize the sensor."""
        self._api = api
        self._usage_days = usage_days
        self._attr_unique_id = f"{entry.entry_id}_usage"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Contact Energy",
            manufacturer="Contact Energy",
            model="Smart Meter",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._last_total = 0.0
        self._last_cost = 0.0

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        return {
            "account_id": self._api._accountId,
            "contract_id": self._api._contractId,
            "last_daily_cost": f"${self._last_cost:.2f}",
        }

    async def async_update(self) -> None:
        """Update the sensor."""
        await self.hass.async_add_executor_job(self._update)

    def _update(self) -> None:
        """Fetch usage data (runs in executor)."""
        _LOGGER.debug("Beginning usage update")

        # Check API token
        if not self._api._api_token:
            _LOGGER.info("Not logged in, attempting login...")
            if not self._api.login():
                _LOGGER.error("Failed to login - check credentials")
                return

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        kWhStatistics = []
        kWhRunningSum = 0.0

        freeKWhStatistics = []
        freeKWhRunningSum = 0.0

        latest_daily_total = 0.0
        latest_daily_cost = 0.0

        for i in range(self._usage_days):
            previous_day = today - timedelta(days=self._usage_days - i)
            response = self._api.get_usage(
                str(previous_day.year),
                str(previous_day.month),
                str(previous_day.day),
            )

            if not response or not response[0]:
                continue

            daily_total = 0.0
            daily_cost = 0.0

            for point in response:
                value = point.get("value")
                if not value:
                    continue

                value = float(value)
                daily_total += value

                # Track cost
                dollar_value = point.get("dollarValue", "0")
                if dollar_value:
                    daily_cost += float(dollar_value)

                # If offpeak value is '0.00', the energy is free
                if point.get("offpeakValue") == "0.00":
                    freeKWhRunningSum += value
                else:
                    kWhRunningSum += value

                # Parse timestamp
                try:
                    timestamp = datetime.strptime(
                        point["date"], "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                except (KeyError, ValueError):
                    continue

                kWhStatistics.append(
                    StatisticData(start=timestamp, sum=kWhRunningSum)
                )
                freeKWhStatistics.append(
                    StatisticData(start=timestamp, sum=freeKWhRunningSum)
                )

            # Track latest day with data
            if daily_total > 0:
                latest_daily_total = daily_total
                latest_daily_cost = daily_cost

        # Update sensor state
        self._attr_native_value = round(kWhRunningSum + freeKWhRunningSum, 2)
        self._last_total = latest_daily_total
        self._last_cost = latest_daily_cost

        # Add statistics for energy dashboard
        if kWhStatistics:
            kWhMetadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name="Contact Energy",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:energy_consumption",
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            )
            async_add_external_statistics(self.hass, kWhMetadata, kWhStatistics)

        if freeKWhStatistics:
            freeKWhMetadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name="Contact Energy Free",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:free_energy_consumption",
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            )
            async_add_external_statistics(self.hass, freeKWhMetadata, freeKWhStatistics)

        _LOGGER.debug(
            "Updated usage: %.2f kWh total, %.2f kWh free",
            kWhRunningSum,
            freeKWhRunningSum,
        )
