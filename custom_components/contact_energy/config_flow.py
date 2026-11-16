"""Config flow for the Contact Energy integration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ContactEnergyApi, ContactEnergyAuthError, ContactEnergyConnectionError
from .const import (
    CONF_CLEAR_EXISTING,
    CONF_HISTORY_DAYS,
    CONF_OFFPEAK_RATE,
    CONF_PEAK_RATE,
    CONF_USAGE_DAYS,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_USAGE_DAYS,
    DOMAIN,
    MAX_HISTORY_DAYS,
)
from .coordinator import HistoryImportRunning

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
USAGE_DAYS_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=30, step=1, mode=NumberSelectorMode.BOX)
)
HISTORY_DAYS_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=0, max=MAX_HISTORY_DAYS, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="days"
    )
)
RATE_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=0, max=5, step="any", mode=NumberSelectorMode.BOX, unit_of_measurement="NZD/kWh"
    )
)

# Rates are optional with no default: left empty, they come from the bill.
SETTINGS_FIELDS = {
    vol.Required(CONF_USAGE_DAYS, default=DEFAULT_USAGE_DAYS): USAGE_DAYS_SELECTOR,
    vol.Optional(CONF_PEAK_RATE): RATE_SELECTOR,
    vol.Optional(CONF_OFFPEAK_RATE): RATE_SELECTOR,
}

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
        vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
        **SETTINGS_FIELDS,
        vol.Required(CONF_HISTORY_DAYS, default=DEFAULT_HISTORY_DAYS): HISTORY_DAYS_SELECTOR,
    }
)
OPTIONS_SCHEMA = vol.Schema(SETTINGS_FIELDS)
IMPORT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HISTORY_DAYS, default=365): NumberSelector(
            NumberSelectorConfig(
                min=1, max=MAX_HISTORY_DAYS, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="days"
            )
        ),
        vol.Required(CONF_CLEAR_EXISTING, default=False): BooleanSelector(),
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR})


def _normalise_settings(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Store usage days as an int and empty rates as None (meaning "use the bill")."""
    return {
        CONF_USAGE_DAYS: int(user_input.get(CONF_USAGE_DAYS, DEFAULT_USAGE_DAYS)),
        CONF_PEAK_RATE: user_input.get(CONF_PEAK_RATE),
        CONF_OFFPEAK_RATE: user_input.get(CONF_OFFPEAK_RATE),
    }


async def _async_validate_login(hass: HomeAssistant, email: str, password: str) -> dict[str, str]:
    """Try to log in; return form errors (empty on success)."""
    api = ContactEnergyApi(email, password)
    try:
        await hass.async_add_executor_job(api.authenticate)
    except ContactEnergyAuthError:
        return {"base": "invalid_auth"}
    except ContactEnergyConnectionError:
        return {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected error while logging in to Contact Energy")
        return {"base": "unknown"}
    return {}


class ContactEnergyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Contact Energy."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ContactEnergyOptionsFlow:
        """Get the options flow for this handler."""
        return ContactEnergyOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            errors = await _async_validate_login(self.hass, email, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_create_entry(
                    title=f"Contact Energy ({email})",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        **_normalise_settings(user_input),
                        CONF_HISTORY_DAYS: int(user_input.get(CONF_HISTORY_DAYS, 0)),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start re-authentication when Contact rejects the stored password."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate_login(
                self.hass, entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )


class ContactEnergyOptionsFlow(OptionsFlowWithReload):
    """Change settings, or import history with a progress bar."""

    def __init__(self) -> None:
        """Initialise the options flow."""
        self._import_days = 0
        self._import_clear = False
        self._import_task: asyncio.Task[dict] | None = None
        self._wait_task: asyncio.Task[Any] | None = None
        self._remove_listener = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose what to do."""
        return self.async_show_menu(step_id="init", menu_options=["settings", "import_history"])

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the usage window and rate overrides."""
        if user_input is not None:
            return self.async_create_entry(data=_normalise_settings(user_input))

        current = {**self.config_entry.data, **self.config_entry.options}
        suggested = {key: value for key, value in current.items() if value is not None}
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, suggested),
        )

    async def async_step_import_history(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how much history to import."""
        coordinator = self.config_entry.runtime_data
        if coordinator.import_running:
            return self.async_abort(reason="import_running")
        if user_input is not None:
            self._import_days = int(user_input[CONF_HISTORY_DAYS])
            self._import_clear = bool(user_input[CONF_CLEAR_EXISTING])
            return await self.async_step_import_progress()

        history = coordinator.history_range
        return self.async_show_form(
            step_id="import_history",
            data_schema=IMPORT_SCHEMA,
            description_placeholders={
                "stored": (
                    f"{(history[1] - history[0]).days + 1} days ({history[0]} to {history[1]})"
                    if history
                    else "none yet"
                ),
                "max_days": str(MAX_HISTORY_DAYS),
            },
        )

    async def async_step_import_progress(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a progress bar while the import runs."""
        coordinator = self.config_entry.runtime_data
        if self._import_task is None:
            try:
                self._import_task = coordinator.async_start_history_import(
                    self._import_days, self._import_clear
                )
            except HistoryImportRunning:
                return self.async_abort(reason="import_running")
            self._remove_listener = coordinator.async_add_progress_listener(self.async_update_progress)
            # Closing the dialog cancels this waiter, not the import itself.
            self._wait_task = self.hass.async_create_task(_wait_quietly(self._import_task))
        if not self._import_task.done():
            return self.async_show_progress(
                step_id="import_progress",
                progress_action="importing",
                progress_task=self._wait_task,
                description_placeholders={"days": str(self._import_days)},
            )
        return self.async_show_progress_done(next_step_id="import_done")

    async def async_step_import_done(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the result."""
        self._stop_listening()
        task = self._import_task
        if task is None or task.cancelled() or task.exception() is not None:
            error = "cancelled" if task is None or task.cancelled() else str(task.exception())
            return self.async_abort(reason="import_failed", description_placeholders={"error": error})
        result = task.result()
        limit = (
            f" Contact has no data before {result['contact_history_starts']}."
            if result.get("contact_history_starts")
            else ""
        )
        return self.async_abort(
            reason="import_complete",
            description_placeholders={
                "days": str(result["days_imported"]),
                "hours": str(result["hours_imported"]),
                "oldest": result["oldest"],
                "newest": result["newest"],
                "kwh": f"{result['kwh']:.1f}",
                "cost": f"{result['cost_nzd']:.2f}",
                "limit": limit,
            },
        )

    def _stop_listening(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None

    @callback
    def async_remove(self) -> None:
        """Stop listening for progress when the dialog closes."""
        self._stop_listening()


async def _wait_quietly(task: asyncio.Task) -> None:
    """Wait for the import without cancelling it or raising its error."""
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        if not task.cancelled():
            raise  # only this waiter was cancelled; the import carries on
    except Exception:  # noqa: BLE001 - the result step reports the error
        pass
