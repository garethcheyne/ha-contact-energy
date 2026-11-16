"""Contact Energy sensors."""

from __future__ import annotations

from datetime import date, datetime
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CURRENCY, DOMAIN
from .coordinator import ContactEnergyConfigEntry, ContactEnergyCoordinator
from .data import NZ_TZ, ContactEnergyData, UsageSummary, is_offpeak_hour, parse_bill_date

_LOGGER = logging.getLogger(__name__)

# The coordinator does the polling; entities never poll themselves.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ContactEnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Contact Energy sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        sensor_class(coordinator)
        for sensor_class in (
            ContactEnergyUsageSensor,
            ContactEnergyCurrentPriceSensor,
            ContactEnergyPeakCostSensor,
            ContactEnergyOffPeakCostSensor,
            ContactEnergyPeakRateSensor,
            ContactEnergyOffPeakRateSensor,
            ContactEnergyOffPeakPeriodSensor,
            ContactEnergyNextBillDateSensor,
            ContactEnergyNextBillAmountSensor,
        )
    )


class ContactEnergySensor(CoordinatorEntity[ContactEnergyCoordinator], SensorEntity):
    """Base class for Contact Energy sensors."""

    _attr_has_entity_name = True
    # Unique IDs are "<prefix><entry_id>_<suffix>". Never change these:
    # Home Assistant tracks entities by unique_id, so a change would orphan
    # every existing entity and its history.
    _unique_id_prefix = ""
    _unique_id_suffix: str

    def __init__(self, coordinator: ContactEnergyCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{self._unique_id_prefix}{entry_id}_{self._unique_id_suffix}"
        plan = coordinator.data.plan if coordinator.data else {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Contact Energy",
            manufacturer="Contact Energy",
            model=plan.get("plan_name") or "Smart Meter",
            sw_version=plan.get("plan_id") or None,
            configuration_url="https://www.contact.co.nz/myaccount",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _data(self) -> ContactEnergyData:
        return self.coordinator.data


class ContactEnergyUsageSensor(ContactEnergySensor):
    """Total usage over the usage window (see the period_* attributes).

    This is a rolling total, so it has no state class: the Energy Dashboard
    should use the `contact_energy:energy_consumption` and
    `contact_energy:free_energy_consumption` statistics instead.
    """

    _attr_name = "Energy Usage"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_icon = "mdi:meter-electric"
    _unique_id_suffix = "usage"

    @property
    def native_value(self) -> float | None:
        """Return the total usage in the window."""
        usage = self._data.usage
        return round(usage.total_kwh, 2) if usage else None

    @property
    def extra_state_attributes(self) -> dict:
        """Return account and plan details."""
        data = self._data
        usage = data.usage
        attributes = {
            **_period_attributes(usage),
            "account_id": data.account_id,
            "contract_id": data.contract_id,
            "last_daily_cost": f"${usage.latest_day_cost:.2f}" if usage else None,
            "last_daily_usage": round(usage.latest_day_kwh, 2) if usage else None,
            "last_data_date": usage.latest_day.isoformat() if usage and usage.latest_day else None,
            "peak_usage": round(usage.peak_kwh, 2) if usage else None,
            "offpeak_usage": round(usage.offpeak_kwh, 2) if usage else None,
        }
        if plan := data.plan:
            attributes.update(
                {
                    "plan_name": plan.get("plan_name", "Unknown"),
                    "plan_id": plan.get("plan_id", ""),
                    "campaign": plan.get("campaign", ""),
                    "contract_start_date": plan.get("contract_start", ""),
                    "contract_end_date": plan.get("contract_end", ""),
                    "prompt_payment_discount": plan.get("ppd_percentage", "0%"),
                    "service_type": plan.get("service_type", "Electricity"),
                }
            )
        return attributes


class ContactEnergyCurrentPriceSensor(ContactEnergySensor):
    """Price per kWh right now, for the Energy Dashboard's "current price" option."""

    _attr_name = "Current Price"
    _attr_native_unit_of_measurement = f"{CURRENCY}/{UnitOfEnergy.KILO_WATT_HOUR}"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:cash-clock"
    _unique_id_suffix = "current_price"

    async def async_added_to_hass(self) -> None:
        """Re-evaluate the price at the top of every hour."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(self.hass, self._async_hour_changed, minute=0, second=5)
        )

    @callback
    def _async_hour_changed(self, now: datetime) -> None:
        self.async_write_ha_state()

    def _is_offpeak(self) -> bool:
        usage = self._data.usage
        window = usage.offpeak_window if usage else None
        return is_offpeak_hour(datetime.now(NZ_TZ).hour, window)

    @property
    def native_value(self) -> float:
        """Return the rate for the current hour."""
        rates = self._data.rates
        return round(rates.offpeak if self._is_offpeak() else rates.peak, 4)

    @property
    def extra_state_attributes(self) -> dict:
        """Return both rates and the current period."""
        rates = self._data.rates
        return {
            "peak_rate": f"${rates.peak:.4f}/kWh",
            "offpeak_rate": f"${rates.offpeak:.4f}/kWh",
            "current_period": "off-peak" if self._is_offpeak() else "peak",
            "rate_source": rates.source,
        }


def _period_attributes(usage: UsageSummary | None) -> dict:
    """Describe the days a usage total covers."""
    if usage is None:
        return {}
    return {
        "period_start": usage.period_start.isoformat() if usage.period_start else None,
        "period_end": usage.period_end.isoformat() if usage.period_end else None,
        "days": usage.days,
    }


class _UsageCostSensor(ContactEnergySensor):
    """Total cost of peak or off-peak usage over the usage window.

    Uses what Contact charged for each hour. Falls back to kWh x rate when
    Contact reported no costs for the window.
    """

    _attr_native_unit_of_measurement = CURRENCY
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2
    _offpeak: bool
    _energy_attribute: str

    def _figures(self) -> tuple[float, float, float, float] | None:
        """Return (kwh, rate, contact_cost, estimated_cost) for this period type."""
        usage = self._data.usage
        if usage is None:
            return None
        rates = self._data.rates
        if self._offpeak:
            kwh, rate, cost = usage.offpeak_kwh, rates.offpeak, usage.offpeak_cost
        else:
            kwh, rate, cost = usage.peak_kwh, rates.peak, usage.peak_cost
        return kwh, rate, cost, kwh * rate

    @property
    def native_value(self) -> float | None:
        """Return the total cost for the period."""
        if (figures := self._figures()) is None:
            return None
        _, _, cost, estimated = figures
        return round(cost if self._data.usage.has_cost else estimated, 2)

    @property
    def extra_state_attributes(self) -> dict:
        """Explain the period, usage and rate behind the total."""
        if (figures := self._figures()) is None:
            return {}
        kwh, rate, _, estimated = figures
        return {
            **_period_attributes(self._data.usage),
            "kwh": round(kwh, 2),
            "rate": f"${rate:.4f}/kWh",
            "cost_source": "contact" if self._data.usage.has_cost else "estimated",
            "estimated_cost": round(estimated, 2),
            # Kept for existing dashboards and templates.
            self._energy_attribute: f"{kwh:.2f} kWh",
        }


class ContactEnergyPeakCostSensor(_UsageCostSensor):
    """What peak-time usage cost over the usage window."""

    _attr_name = "Peak Usage Cost"
    _attr_icon = "mdi:currency-usd"
    _unique_id_suffix = "peak_cost"
    _offpeak = False
    _energy_attribute = "peak_energy"


class ContactEnergyOffPeakCostSensor(_UsageCostSensor):
    """What off-peak usage cost over the usage window."""

    _attr_name = "Off-Peak Usage Cost"
    _attr_icon = "mdi:currency-usd-off"
    _unique_id_suffix = "offpeak_cost"
    _offpeak = True
    _energy_attribute = "offpeak_energy"


class _RateSensor(ContactEnergySensor):
    """A per-kWh rate (from the bill, your override, or the default)."""

    _attr_native_unit_of_measurement = f"{CURRENCY}/{UnitOfEnergy.KILO_WATT_HOUR}"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:cash"
    _offpeak: bool

    @property
    def native_value(self) -> float:
        """Return the rate."""
        rates = self._data.rates
        return round(rates.offpeak if self._offpeak else rates.peak, 4)

    @property
    def extra_state_attributes(self) -> dict:
        """Return where the rate came from."""
        return {"rate_source": self._data.rates.source}


class ContactEnergyPeakRateSensor(_RateSensor):
    """Peak rate per kWh."""

    _attr_name = "Peak Rate"
    _unique_id_suffix = "peak_rate"
    _offpeak = False


class ContactEnergyOffPeakRateSensor(_RateSensor):
    """Off-peak rate per kWh."""

    _attr_name = "Off-Peak Rate"
    _unique_id_suffix = "offpeak_rate"
    _offpeak = True


class ContactEnergyOffPeakPeriodSensor(ContactEnergySensor):
    """Off-peak hours detected from recent usage, e.g. "21:00 - 07:00"."""

    _attr_name = "Off-Peak Period"
    _attr_icon = "mdi:clock-time-eight-outline"
    _unique_id_suffix = "offpeak_period"

    def _window(self) -> tuple[int, int] | None:
        usage = self._data.usage
        return usage.offpeak_window if usage else None

    @property
    def native_value(self) -> str | None:
        """Return the off-peak period."""
        if self._data.usage is None:
            return None
        if (window := self._window()) is None:
            return "No off-peak detected"
        return f"{window[0]:02d}:00 - {window[1]:02d}:00"

    @property
    def extra_state_attributes(self) -> dict:
        """Return the start and end of the off-peak period."""
        if (window := self._window()) is None:
            return {}
        return {"offpeak_start": f"{window[0]:02d}:00", "offpeak_end": f"{window[1]:02d}:00"}


class ContactEnergyNextBillDateSensor(ContactEnergySensor):
    """Date of the next bill."""

    _attr_name = "Next Bill Date"
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-clock"
    _unique_id_prefix = f"{DOMAIN}_"
    _unique_id_suffix = "next_bill_date"

    @property
    def native_value(self) -> date | None:
        """Return the next bill date."""
        return parse_bill_date(self._data.bill.get("next_bill_date"))


class ContactEnergyNextBillAmountSensor(ContactEnergySensor):
    """Amount of the next bill."""

    _attr_name = "Next Bill Amount"
    _attr_native_unit_of_measurement = CURRENCY
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:currency-usd"
    _unique_id_prefix = f"{DOMAIN}_"
    _unique_id_suffix = "next_bill_amount"

    @property
    def native_value(self) -> float | None:
        """Return the next bill amount."""
        amount = self._data.bill.get("next_bill_amount")
        return round(amount, 2) if amount is not None else None
