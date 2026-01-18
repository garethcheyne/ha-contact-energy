"""Support for Contact Energy integration."""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import async_add_external_statistics, clear_statistics, StatisticData, StatisticMetaData
from homeassistant.const import UnitOfEnergy

from .api import ContactEnergyApi
from .const import DOMAIN, CONF_USAGE_DAYS

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Contact Energy from a config entry."""
    _LOGGER.debug("Setting up Contact Energy integration")

    # Create API instance
    api = ContactEnergyApi(
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )

    # Try to login
    login_success = await hass.async_add_executor_job(api.login)
    if not login_success:
        _LOGGER.error("Failed to login to Contact Energy API")
        return False

    # Store API and config in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "usage_days": entry.data.get(CONF_USAGE_DAYS, 10),
    }

    # Forward setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register service to export historical data
    async def handle_export_historical_data(call: ServiceCall) -> None:
        """Handle the export historical data service call."""
        days = call.data.get("days", 30)
        _LOGGER.info(f"Exporting {days} days of Contact Energy historical data...")
        
        # Get API instance from first available entry
        api = None
        for entry_data in hass.data[DOMAIN].values():
            if "api" in entry_data:
                api = entry_data["api"]
                break
        
        if not api:
            _LOGGER.error("No Contact Energy API instance found")
            return
        
        # Ensure logged in
        if not api._api_token:
            login_success = await hass.async_add_executor_job(api.login)
            if not login_success:
                _LOGGER.error("Failed to login to Contact Energy API")
                return
        
        # Fetch historical data
        all_data = []
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        for i in range(days):
            day = today - timedelta(days=days - i)
            response = await hass.async_add_executor_job(
                api.get_usage,
                str(day.year),
                str(day.month),
                str(day.day),
            )
            
            if response:
                for point in response:
                    try:
                        timestamp = datetime.strptime(point["date"], "%Y-%m-%dT%H:%M:%S.%f%z")
                        value = float(point.get("value", 0))
                        dollar_value = float(point.get("dollarValue", 0))
                        offpeak_value = float(point.get("offpeakValue", 0))
                        
                        all_data.append({
                            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                            "date": timestamp.strftime("%Y-%m-%d"),
                            "hour": timestamp.hour,
                            "kwh": value,
                            "cost_nzd": dollar_value,
                            "is_offpeak": 1 if offpeak_value > 0 else 0,
                            "offpeak_kwh": offpeak_value,
                            "peak_kwh": value if offpeak_value == 0 else 0,
                        })
                    except (KeyError, ValueError) as e:
                        _LOGGER.warning(f"Failed to parse data point: {e}")
                        continue
        
        if not all_data:
            _LOGGER.warning("No historical data found to export")
            return
        
        # Save to CSV file in Home Assistant config directory
        csv_path = Path(hass.config.path("contact_energy_export.csv"))
        
        await hass.async_add_executor_job(
            _write_csv, csv_path, all_data
        )
        
        _LOGGER.info(
            f"Exported {len(all_data)} hourly records to {csv_path}"
        )
        
        # Calculate summary statistics
        total_kwh = sum(d["kwh"] for d in all_data)
        total_cost = sum(d["cost_nzd"] for d in all_data)
        peak_kwh = sum(d["peak_kwh"] for d in all_data)
        offpeak_kwh = sum(d["offpeak_kwh"] for d in all_data)
        
        _LOGGER.info(
            f"Summary: Total={total_kwh:.2f} kWh (Peak={peak_kwh:.2f}, Off-Peak={offpeak_kwh:.2f}), Cost=${total_cost:.2f}"
        )

    def _write_csv(csv_path: Path, data: list) -> None:
        """Write data to CSV file (runs in executor)."""
        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["timestamp", "date", "hour", "kwh", "cost_nzd", "is_offpeak", "offpeak_kwh", "peak_kwh"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

    hass.services.async_register(
        DOMAIN,
        "export_historical_data",
        handle_export_historical_data,
        schema=vol.Schema({
            vol.Optional("days", default=30): cv.positive_int,
        }),
    )

    # Register service to import historical data into database
    async def handle_import_historical_data(call: ServiceCall) -> None:
        """Handle the import historical data service call."""
        days = call.data.get("days", 90)
        clear_existing = call.data.get("clear_existing", False)
        confirm_clear = call.data.get("confirm_clear", "").strip().lower()
        
        # If clearing existing data, require confirmation
        if clear_existing:
            if confirm_clear != "yes":
                _LOGGER.error("Import cancelled - clear_existing is true but confirmation not provided. You must type 'yes' in confirm_clear field.")
                return
            
            _LOGGER.info("Clearing existing Contact Energy statistics...")
            statistic_ids = [
                f"{DOMAIN}:energy_consumption",
                f"{DOMAIN}:free_energy_consumption",
            ]
            
            for statistic_id in statistic_ids:
                await get_instance(hass).async_clear_statistics([statistic_id])
                _LOGGER.info(f"Cleared statistics for {statistic_id}")
        
        _LOGGER.info(f"Importing {days} days of Contact Energy historical data into database...")
        
        # Get API instance from first available entry
        api = None
        for entry_data in hass.data[DOMAIN].values():
            if "api" in entry_data:
                api = entry_data["api"]
                break
        
        if not api:
            _LOGGER.error("No Contact Energy API instance found")
            return
        
        # Ensure logged in
        if not api._api_token:
            login_success = await hass.async_add_executor_job(api.login)
            if not login_success:
                _LOGGER.error("Failed to login to Contact Energy API")
                return
        
        # Fetch historical data
        kWh_statistics = []
        free_kWh_statistics = []
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        _LOGGER.info(f"Fetching data from API for {days} days...")
        for i in range(days):
            day = today - timedelta(days=days - i)
            response = await hass.async_add_executor_job(
                api.get_usage,
                str(day.year),
                str(day.month),
                str(day.day),
            )
            
            if not response:
                continue
            
            for point in response:
                try:
                    timestamp = datetime.strptime(point["date"], "%Y-%m-%dT%H:%M:%S.%f%z")
                    value = float(point.get("value", 0))
                    offpeak_value = float(point.get("offpeakValue", 0))
                    
                    if offpeak_value > 0:
                        # This is off-peak/free energy
                        free_kWh_statistics.append(
                            StatisticData(start=timestamp, state=value)
                        )
                    else:
                        # This is peak energy
                        kWh_statistics.append(
                            StatisticData(start=timestamp, state=value)
                        )
                except (KeyError, ValueError) as e:
                    _LOGGER.warning(f"Failed to parse data point: {e}")
                    continue
            
            # Log progress every 10 days
            if (i + 1) % 10 == 0:
                _LOGGER.info(f"Processed {i + 1}/{days} days...")
        
        if not kWh_statistics and not free_kWh_statistics:
            _LOGGER.warning("No historical data found to import")
            return
        
        # Import peak energy statistics
        if kWh_statistics:
            kWh_metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name="Contact Energy",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:energy_consumption",
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            )
            async_add_external_statistics(hass, kWh_metadata, kWh_statistics)
            _LOGGER.info(f"Imported {len(kWh_statistics)} peak energy statistics")
        
        # Import off-peak energy statistics
        if free_kWh_statistics:
            free_kWh_metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name="Contact Energy Free",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:free_energy_consumption",
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            )
            async_add_external_statistics(hass, free_kWh_metadata, free_kWh_statistics)
            _LOGGER.info(f"Imported {len(free_kWh_statistics)} off-peak energy statistics")
        
        total_records = len(kWh_statistics) + len(free_kWh_statistics)
        _LOGGER.info(
            f"Successfully imported {total_records} hourly statistics into Energy Dashboard"
        )

    hass.services.async_register(
        DOMAIN,
        "import_historical_data",
        handle_import_historical_data,
        schema=vol.Schema({
            vol.Optional("days", default=90): cv.positive_int,
            vol.Optional("clear_existing", default=False): cv.boolean,
            vol.Optional("confirm_clear", default=""): cv.string,
        }),
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Contact Energy integration")

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove stored data
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
