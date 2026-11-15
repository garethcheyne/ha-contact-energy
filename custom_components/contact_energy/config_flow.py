"""Config flow for the Contact Energy integration."""

from __future__ import annotations

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
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ContactEnergyApi, ContactEnergyAuthError, ContactEnergyConnectionError
from .const import CONF_OFFPEAK_RATE, CONF_PEAK_RATE, CONF_USAGE_DAYS, DEFAULT_USAGE_DAYS, DOMAIN

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
USAGE_DAYS_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=30, step=1, mode=NumberSelectorMode.BOX)
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
    }
)
OPTIONS_SCHEMA = vol.Schema(SETTINGS_FIELDS)
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
    """Change the usage window and rate overrides."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=_normalise_settings(user_input))

        current = {**self.config_entry.data, **self.config_entry.options}
        suggested = {key: value for key, value in current.items() if value is not None}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, suggested),
        )
