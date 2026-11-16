"""The Contact Energy integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import ContactEnergyApi
from .const import CONF_HISTORY_DAYS, CONF_INITIAL_HISTORY_DONE, DOMAIN
from .coordinator import ContactEnergyConfigEntry, ContactEnergyCoordinator
from .energy_check import async_check_energy_sources
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once, whatever the number of accounts."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ContactEnergyConfigEntry) -> bool:
    """Set up Contact Energy from a config entry."""
    api = ContactEnergyApi(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    coordinator = ContactEnergyCoordinator(hass, entry, api)

    # Raises ConfigEntryAuthFailed (starts re-authentication) or
    # ConfigEntryNotReady (Home Assistant retries setup later).
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_check_energy_sources(hass, entry)

    # Import the history chosen at setup once, in the background.
    if (days := int(entry.data.get(CONF_HISTORY_DAYS) or 0)) and not entry.data.get(
        CONF_INITIAL_HISTORY_DONE
    ):
        entry.async_create_background_task(
            hass, _async_initial_history(hass, entry, days), f"{DOMAIN} initial history import"
        )
    return True


async def _async_initial_history(hass: HomeAssistant, entry: ContactEnergyConfigEntry, days: int) -> None:
    """Run the first history import, and remember it succeeded."""
    _LOGGER.info("Importing %d days of Contact Energy history", days)
    try:
        await entry.runtime_data.async_start_history_import(days, clear=False)
    except Exception as err:  # noqa: BLE001 - retried on the next start
        _LOGGER.warning("Initial history import failed (will retry on next start): %s", err)
        return
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_INITIAL_HISTORY_DONE: True}
    )


async def async_unload_entry(hass: HomeAssistant, entry: ContactEnergyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
