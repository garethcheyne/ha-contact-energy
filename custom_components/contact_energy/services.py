"""Services for the Contact Energy integration."""

from __future__ import annotations

import asyncio
import csv
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import ContactEnergyAuthError, ContactEnergyConnectionError
from .const import CONF_CONFIG_ENTRY_ID, DOMAIN, MAX_HISTORY_DAYS
from .coordinator import ContactEnergyCoordinator, HistoryImportRunning
from .data import UsagePoint

_LOGGER = logging.getLogger(__name__)

SERVICE_IMPORT = "import_historical_data"
SERVICE_EXPORT = "export_historical_data"

EXPORT_FILENAME = "contact_energy_export.csv"
CSV_FIELDS = ["timestamp", "date", "hour", "kwh", "cost_nzd", "is_offpeak", "offpeak_kwh", "peak_kwh"]

IMPORT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional("days", default=90): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_HISTORY_DAYS)
        ),
        vol.Optional("clear_existing", default=False): cv.boolean,
        vol.Optional("confirm_clear", default=""): cv.string,
    }
)

EXPORT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional("days", default=30): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_HISTORY_DAYS)
        ),
    }
)


def _get_coordinator(hass: HomeAssistant, call: ServiceCall) -> ContactEnergyCoordinator:
    """Return the coordinator for the requested (or only loaded) account."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if entry_id := call.data.get(CONF_CONFIG_ENTRY_ID):
        entries = [entry for entry in entries if entry.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError(
                f"No loaded Contact Energy account with config entry ID {entry_id}"
            )
    if not entries:
        raise ServiceValidationError("No Contact Energy account is set up and loaded")
    if len(entries) > 1:
        raise ServiceValidationError(
            "More than one Contact Energy account is set up; choose one with config_entry_id"
        )
    return entries[0].runtime_data


async def _async_fetch(coordinator: ContactEnergyCoordinator, days: int) -> list[UsagePoint]:
    _LOGGER.info("Fetching %d days of Contact Energy usage", days)
    try:
        points = await coordinator.hass.async_add_executor_job(coordinator.fetch_points, days)
    except ContactEnergyAuthError as err:
        coordinator.config_entry.async_start_reauth(coordinator.hass)
        raise HomeAssistantError(f"Contact Energy login failed: {err}") from err
    except ContactEnergyConnectionError as err:
        raise HomeAssistantError(f"Could not fetch data from Contact Energy: {err}") from err
    if not points:
        raise HomeAssistantError(f"Contact Energy returned no usage for the last {days} days")
    return points


def _write_csv(path: Path, points: list[UsagePoint]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for point in points:
            writer.writerow(
                {
                    "timestamp": point.start.strftime("%Y-%m-%d %H:%M:%S"),
                    "date": point.start.strftime("%Y-%m-%d"),
                    "hour": point.start.hour,
                    "kwh": point.kwh,
                    "cost_nzd": point.cost,
                    "is_offpeak": int(point.offpeak),
                    "offpeak_kwh": point.kwh if point.offpeak else 0,
                    "peak_kwh": 0 if point.offpeak else point.kwh,
                }
            )


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Contact Energy services."""

    async def handle_import(call: ServiceCall) -> ServiceResponse:
        clear_existing = call.data["clear_existing"]
        if clear_existing and call.data["confirm_clear"].strip().lower() != "yes":
            raise ServiceValidationError(
                "clear_existing deletes all Contact Energy statistics; type 'yes' in confirm_clear to go ahead"
            )
        coordinator = _get_coordinator(hass, call)
        try:
            task = coordinator.async_start_history_import(call.data["days"], clear_existing)
        except HistoryImportRunning as err:
            raise ServiceValidationError("A Contact Energy history import is already running") from err
        # The import runs as its own background task; this only waits for it.
        return await asyncio.shield(task)

    async def handle_export(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call)
        points = await _async_fetch(coordinator, call.data["days"])
        path = Path(hass.config.path(EXPORT_FILENAME))
        await hass.async_add_executor_job(_write_csv, path, points)

        total_kwh = sum(p.kwh for p in points)
        offpeak_kwh = sum(p.kwh for p in points if p.offpeak)
        total_cost = sum(p.cost for p in points)
        _LOGGER.info(
            "Exported %d hourly records to %s (%.2f kWh, $%.2f)",
            len(points),
            path,
            total_kwh,
            total_cost,
        )
        return {
            "path": str(path),
            "hours": len(points),
            "total_kwh": round(total_kwh, 3),
            "peak_kwh": round(total_kwh - offpeak_kwh, 3),
            "offpeak_kwh": round(offpeak_kwh, 3),
            "cost_nzd": round(total_cost, 2),
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT,
        handle_import,
        schema=IMPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT,
        handle_export,
        schema=EXPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
