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
    
    # Priority: User-configured rates > API-fetched rates > Default values
    user_peak_rate = entry.data.get("peak_rate")
    user_offpeak_rate = entry.data.get("offpeak_rate")
    
    if user_peak_rate is not None and user_offpeak_rate is not None:
        # User has explicitly configured rates - use those
        peak_rate = user_peak_rate
        offpeak_rate = user_offpeak_rate
        _LOGGER.info("Using user-configured rates: Peak=$%.4f, Off-peak=$%.4f", peak_rate, offpeak_rate)
    elif api._bill_details and api._bill_details.get("peak_rate", 0) > 0:
        # No user override - use API-fetched rates
        peak_rate = api._bill_details["peak_rate"]
        offpeak_rate = api._bill_details["offpeak_rate"]
        _LOGGER.info("Using API-fetched rates: Peak=$%.4f, Off-peak=$%.4f", peak_rate, offpeak_rate)
    else:
        # Fallback to defaults
        peak_rate = 0.30
        offpeak_rate = 0.15
        _LOGGER.warning("Using default rates: Peak=$%.4f, Off-peak=$%.4f", peak_rate, offpeak_rate)

    sensors = [
        ContactEnergyUsageSensor(entry, api, usage_days),
        ContactEnergyCurrentPriceSensor(entry, api, peak_rate, offpeak_rate),
        ContactEnergyPeakCostSensor(entry, api, usage_days, peak_rate),
        ContactEnergyOffPeakCostSensor(entry, api, usage_days, offpeak_rate),
        ContactEnergyOffPeakPeriodSensor(entry, api),        ContactEnergyNextBillDateSensor(entry, api, usage_days),
        ContactEnergyNextBillAmountSensor(entry, api, usage_days),    ]

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
        
        # Build device info with plan details if available
        plan_name = api._plan_details.get("plan_name", "Smart Meter") if api._plan_details else "Smart Meter"
        sw_version = api._plan_details.get("plan_id", "Unknown") if api._plan_details else "Unknown"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Contact Energy",
            manufacturer="Contact Energy",
            model=plan_name,
            sw_version=sw_version,
            configuration_url="https://www.contact.co.nz/myaccount",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._last_total = 0.0
        self._last_cost = 0.0

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        attributes = {
            "account_id": self._api._accountId,
            "contract_id": self._api._contractId,
            "last_daily_cost": f"${self._last_cost:.2f}",
        }
        
        # Add plan details if available
        if self._api._plan_details:
            plan = self._api._plan_details
            attributes.update({
                "plan_name": plan.get("plan_name", "Unknown"),
                "plan_id": plan.get("plan_id", ""),
                "campaign": plan.get("campaign", ""),
                "contract_start_date": plan.get("contract_start", ""),
                "contract_end_date": plan.get("contract_end", ""),
                "prompt_payment_discount": plan.get("ppd_percentage", "0%"),
                "service_type": plan.get("service_type", "Electricity"),
            })
        
        return attributes

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

                # Off-peak detection: offpeakValue > 0 means off-peak energy
                offpeak_value = point.get("offpeakValue", "0")
                try:
                    offpeak_float = float(offpeak_value) if offpeak_value else 0.0
                except (ValueError, TypeError):
                    offpeak_float = 0.0
                
                # Parse timestamp first (before adding to sums)
                try:
                    timestamp = datetime.strptime(
                        point["date"], "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                except (KeyError, ValueError):
                    _LOGGER.warning("Failed to parse timestamp for data point")
                    continue
                
                if offpeak_float > 0:
                    # This is off-peak/free energy
                    freeKWhRunningSum += value
                    # Add hourly statistics with both state (this hour's value) and sum (cumulative)
                    freeKWhStatistics.append(
                        StatisticData(start=timestamp, state=value, sum=freeKWhRunningSum)
                    )
                else:
                    # This is peak energy
                    kWhRunningSum += value
                    # Add hourly statistics with both state (this hour's value) and sum (cumulative)
                    kWhStatistics.append(
                        StatisticData(start=timestamp, state=value, sum=kWhRunningSum)
                    )

            # Track latest day with data
            if daily_total > 0:
                latest_daily_total = daily_total
                latest_daily_cost = daily_cost

        # Update sensor state with total consumption
        total_consumption = round(kWhRunningSum + freeKWhRunningSum, 2)
        self._attr_native_value = total_consumption
        self._last_total = latest_daily_total
        self._last_cost = latest_daily_cost

        _LOGGER.info(
            "Updated Contact Energy: %d hourly statistics, Total: %.2f kWh (%.2f peak + %.2f off-peak)",
            len(kWhStatistics),
            total_consumption,
            kWhRunningSum,
            freeKWhRunningSum,
        )

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
            _LOGGER.debug(
                "Added %d statistics for contact_energy:energy_consumption",
                len(kWhStatistics)
            )

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
                "Added %d statistics for contact_energy:free_energy_consumption",
                len(freeKWhStatistics)
            )


class ContactEnergyCurrentPriceSensor(SensorEntity):
    """Contact Energy Current Price sensor for Energy Dashboard."""

    _attr_has_entity_name = True
    _attr_name = "Current Price"
    _attr_native_unit_of_measurement = "NZD/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash-clock"

    def __init__(self, entry: ConfigEntry, api, peak_rate: float, offpeak_rate: float) -> None:
        """Initialize the sensor."""
        self._api = api
        self._attr_unique_id = f"{entry.entry_id}_current_price"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Contact Energy",
            manufacturer="Contact Energy",
            model="Smart Meter",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._peak_rate = peak_rate
        self._offpeak_rate = offpeak_rate
        self._is_offpeak = False
        self._attr_native_value = peak_rate

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        return {
            "peak_rate": f"${self._peak_rate:.4f}/kWh",
            "offpeak_rate": f"${self._offpeak_rate:.4f}/kWh",
            "current_period": "off-peak" if self._is_offpeak else "peak",
        }

    async def async_update(self) -> None:
        """Update the sensor."""
        await self.hass.async_add_executor_job(self._update)

    def _update(self) -> None:
        """Determine current price based on time period."""
        if not self._api._api_token:
            if not self._api.login():
                return

        # Get yesterday's data to determine current period
        yesterday = datetime.now() - timedelta(days=2)
        response = self._api.get_usage(
            str(yesterday.year),
            str(yesterday.month),
            str(yesterday.day),
        )

        if not response:
            # Default to peak rate if no data
            self._attr_native_value = round(self._peak_rate, 4)
            return

        current_hour = datetime.now().hour

        # Determine if current time is off-peak (based on yesterday's pattern)
        for point in response:
            try:
                timestamp = datetime.strptime(point["date"], "%Y-%m-%dT%H:%M:%S.%f%z")
                if timestamp.hour == current_hour:
                    offpeak_value = point.get("offpeakValue", "0")
                    offpeak_float = float(offpeak_value) if offpeak_value else 0.0
                    self._is_offpeak = offpeak_float > 0
                    break
            except (KeyError, ValueError):
                continue

        # Set current price based on time of day
        if self._is_offpeak:
            self._attr_native_value = round(self._offpeak_rate, 4)
        else:
            self._attr_native_value = round(self._peak_rate, 4)



class ContactEnergyPeakCostSensor(SensorEntity):
    """Contact Energy Peak Cost sensor."""

    _attr_has_entity_name = True
    _attr_name = "Peak Cost"
    _attr_native_unit_of_measurement = "NZD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:currency-usd"

    def __init__(self, entry: ConfigEntry, api, usage_days: int, peak_rate: float) -> None:
        """Initialize the sensor."""
        self._api = api
        self._usage_days = usage_days
        self._peak_rate = peak_rate
        self._attr_unique_id = f"{entry.entry_id}_peak_cost"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Contact Energy",
            manufacturer="Contact Energy",
            model="Smart Meter",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._peak_cost = 0.0
        self._peak_kwh = 0.0

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        return {
            "peak_energy": f"{self._peak_kwh:.2f} kWh",
        }

    async def async_update(self) -> None:
        """Update the sensor."""
        await self.hass.async_add_executor_job(self._update)

    def _update(self) -> None:
        """Fetch peak cost data."""
        if not self._api._api_token:
            if not self._api.login():
                return

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        total_peak_cost = 0.0
        total_peak_kwh = 0.0

        for i in range(self._usage_days):
            previous_day = today - timedelta(days=self._usage_days - i)
            response = self._api.get_usage(
                str(previous_day.year),
                str(previous_day.month),
                str(previous_day.day),
            )

            if not response:
                continue

            for point in response:
                value = point.get("value")
                if not value:
                    continue

                offpeak_value = point.get("offpeakValue", "0")
                try:
                    offpeak_float = float(offpeak_value) if offpeak_value else 0.0
                except (ValueError, TypeError):
                    offpeak_float = 0.0

                # Peak time = when offpeakValue is 0
                if offpeak_float == 0:
                    try:
                        total_peak_kwh += float(value)
                    except (ValueError, TypeError):
                        pass

        # Calculate cost from kWh and configured rate
        total_peak_cost = total_peak_kwh * self._peak_rate
        self._attr_native_value = round(total_peak_cost, 2)
        self._peak_cost = total_peak_cost
        self._peak_kwh = total_peak_kwh


class ContactEnergyOffPeakCostSensor(SensorEntity):
    """Contact Energy Off-Peak Cost sensor."""

    _attr_has_entity_name = True
    _attr_name = "Off-Peak Cost"
    _attr_native_unit_of_measurement = "NZD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:currency-usd-off"

    def __init__(self, entry: ConfigEntry, api, usage_days: int, offpeak_rate: float) -> None:
        """Initialize the sensor."""
        self._api = api
        self._usage_days = usage_days
        self._offpeak_rate = offpeak_rate
        self._attr_unique_id = f"{entry.entry_id}_offpeak_cost"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Contact Energy",
            manufacturer="Contact Energy",
            model="Smart Meter",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._offpeak_cost = 0.0
        self._offpeak_kwh = 0.0

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        return {
            "offpeak_energy": f"{self._offpeak_kwh:.2f} kWh",
        }

    async def async_update(self) -> None:
        """Update the sensor."""
        await self.hass.async_add_executor_job(self._update)

    def _update(self) -> None:
        """Fetch off-peak cost data."""
        if not self._api._api_token:
            if not self._api.login():
                return

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        total_offpeak_cost = 0.0
        total_offpeak_kwh = 0.0

        for i in range(self._usage_days):
            previous_day = today - timedelta(days=self._usage_days - i)
            response = self._api.get_usage(
                str(previous_day.year),
                str(previous_day.month),
                str(previous_day.day),
            )

            if not response:
                continue

            for point in response:
                value = point.get("value")
                if not value:
                    continue

                offpeak_value = point.get("offpeakValue", "0")
                try:
                    offpeak_float = float(offpeak_value) if offpeak_value else 0.0
                except (ValueError, TypeError):
                    offpeak_float = 0.0

                # Off-peak time = when offpeakValue > 0
                if offpeak_float > 0:
                    try:
                        total_offpeak_kwh += float(value)
                    except (ValueError, TypeError):
                        pass

        # Calculate cost from kWh and configured rate
        total_offpeak_cost = total_offpeak_kwh * self._offpeak_rate
        self._attr_native_value = round(total_offpeak_cost, 2)
        self._offpeak_cost = total_offpeak_cost
        self._offpeak_kwh = total_offpeak_kwh


class ContactEnergyNextBillDateSensor(SensorEntity):
    """Sensor for next bill due date."""

    def __init__(self, entry, api, usage_days):
        """Initialize the sensor."""
        self._api = api
        self._attr_name = "Contact Energy Next Bill Date"
        self._attr_unique_id = f"contact_energy_{entry.entry_id}_next_bill_date"
        self._attr_device_class = SensorDeviceClass.DATE
        self._attr_icon = "mdi:calendar-clock"

    def update(self):
        """Update sensor."""
        if self._api._bill_details and self._api._bill_details.get("next_bill_date"):
            # Parse date string (ISO format) and extract just the date
            date_str = self._api._bill_details["next_bill_date"]
            if date_str:
                # Expected format: 2026-02-17T00:00:00+13:00
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    self._attr_native_value = dt.date()
                except (ValueError, AttributeError):
                    # Fallback: try to extract just the date part
                    self._attr_native_value = date_str[:10] if len(date_str) >= 10 else None
            else:
                self._attr_native_value = None
        else:
            self._attr_native_value = None


class ContactEnergyNextBillAmountSensor(SensorEntity):
    """Sensor for next bill amount."""

    def __init__(self, entry, api, usage_days):
        """Initialize the sensor."""
        self._api = api
        self._attr_name = "Contact Energy Next Bill Amount"
        self._attr_unique_id = f"contact_energy_{entry.entry_id}_next_bill_amount"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "NZD"
        self._attr_icon = "mdi:currency-usd"
        self._attr_state_class = SensorStateClass.TOTAL

    def update(self):
        """Update sensor."""
        if self._api._bill_details:
            amount = self._api._bill_details.get("next_bill_amount", 0)
            self._attr_native_value = round(amount, 2) if amount else 0.0
        else:
            self._attr_native_value = 0.0


class ContactEnergyOffPeakPeriodSensor(SensorEntity):
    """Contact Energy Off-Peak Period sensor."""

    _attr_has_entity_name = True
    _attr_name = "Off-Peak Period"
    _attr_icon = "mdi:clock-time-eight-outline"

    def __init__(self, entry: ConfigEntry, api) -> None:
        """Initialize the sensor."""
        self._api = api
        self._attr_unique_id = f"{entry.entry_id}_offpeak_period"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Contact Energy",
            manufacturer="Contact Energy",
            model="Smart Meter",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._offpeak_start = None
        self._offpeak_end = None

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        attrs = {}
        if self._offpeak_start:
            attrs["offpeak_start"] = self._offpeak_start
        if self._offpeak_end:
            attrs["offpeak_end"] = self._offpeak_end
        return attrs

    async def async_update(self) -> None:
        """Update the sensor."""
        await self.hass.async_add_executor_job(self._update)

    def _update(self) -> None:
        """Determine off-peak period from recent data."""
        if not self._api._api_token:
            if not self._api.login():
                return

        # Get yesterday's data to determine off-peak hours
        yesterday = datetime.now() - timedelta(days=2)  # Use 2 days ago due to data delay
        response = self._api.get_usage(
            str(yesterday.year),
            str(yesterday.month),
            str(yesterday.day),
        )

        if not response:
            self._attr_native_value = "Unknown"
            return

        offpeak_hours = []
        for point in response:
            offpeak_value = point.get("offpeakValue", "0")
            try:
                offpeak_float = float(offpeak_value) if offpeak_value else 0.0
            except (ValueError, TypeError):
                continue

            if offpeak_float > 0:
                # Extract hour from timestamp
                try:
                    timestamp = datetime.strptime(
                        point["date"], "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    offpeak_hours.append(timestamp.hour)
                except (KeyError, ValueError):
                    continue

        if offpeak_hours:
            # Find continuous periods
            offpeak_hours = sorted(set(offpeak_hours))
            
            # Detect if it wraps around midnight
            if 0 in offpeak_hours and 23 in offpeak_hours:
                # Find the break point
                for i in range(len(offpeak_hours) - 1):
                    if offpeak_hours[i + 1] - offpeak_hours[i] > 1:
                        start_hour = offpeak_hours[i + 1]
                        end_hour = offpeak_hours[i] + 1
                        break
                else:
                    start_hour = min(offpeak_hours)
                    end_hour = max(offpeak_hours) + 1
            else:
                start_hour = min(offpeak_hours)
                end_hour = max(offpeak_hours) + 1

            self._offpeak_start = f"{start_hour:02d}:00"
            self._offpeak_end = f"{end_hour:02d}:00"
            self._attr_native_value = f"{self._offpeak_start} - {self._offpeak_end}"
        else:
            self._attr_native_value = "No off-peak detected"
