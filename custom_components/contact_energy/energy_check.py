"""Warn when the Energy Dashboard uses one of the rolling-total sensors.

Energy Usage, Peak Usage Cost and Off-Peak Usage Cost are totals over the
last N days. Used as an Energy Dashboard source they produce spikes and
negative bars, because every time the window moves the total can fall.
The dashboard should use the contact_energy:* statistics instead.
"""

from __future__ import annotations

from collections.abc import Iterator
import logging

from homeassistant.components.energy.data import async_get_manager
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Unique ID suffixes of the rolling-total sensors (see sensor.py).
ROLLING_SENSOR_SUFFIXES = ("usage", "peak_cost", "offpeak_cost")
ISSUE_TRANSLATION_KEY = "rolling_sensor_in_energy"
LEARN_MORE_URL = "https://github.com/garethcheyne/ha-contact-energy#-energy-dashboard-integration"


def _strings(value) -> Iterator[str]:
    """Yield every string in nested Energy Dashboard preferences.

    Walking the whole structure keeps this working across changes to the
    preferences format between Home Assistant versions.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


async def async_check_energy_sources(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Raise (or clear) a Repairs issue if a rolling-total sensor is a dashboard source."""
    issue_id = f"{ISSUE_TRANSLATION_KEY}_{entry.entry_id}"
    try:
        registry = er.async_get(hass)
        ours = {
            entity_id
            for suffix in ROLLING_SENSOR_SUFFIXES
            if (
                entity_id := registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
                )
            )
        }
        used: list[str] = []
        if ours and "energy" in hass.config.components:
            manager = await async_get_manager(hass)
            used = sorted(ours & set(_strings(manager.data or {})))
    except Exception:  # never let this check break setup
        _LOGGER.debug("Could not check the Energy Dashboard configuration", exc_info=True)
        return

    if not used:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    _LOGGER.warning(
        "The Energy Dashboard uses %s, which are rolling totals and give wrong results; "
        "use the Contact Energy statistics instead",
        ", ".join(used),
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_TRANSLATION_KEY,
        translation_placeholders={"entities": ", ".join(used)},
        learn_more_url=LEARN_MORE_URL,
    )
