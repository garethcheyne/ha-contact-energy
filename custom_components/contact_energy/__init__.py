"""The Contact Energy integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import ContactEnergyApi
from .const import DOMAIN
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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ContactEnergyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
