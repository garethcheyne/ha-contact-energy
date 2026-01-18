"""Support for Contact Energy integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant

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
