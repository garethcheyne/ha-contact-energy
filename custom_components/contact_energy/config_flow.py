"""Config flow for Contact Energy integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import ContactEnergyApi
from .const import DOMAIN, CONF_USAGE_DAYS, CONF_PEAK_RATE, CONF_OFFPEAK_RATE

_LOGGER = logging.getLogger(__name__)

DEFAULT_USAGE_DAYS = 10
DEFAULT_PEAK_RATE = 0.30
DEFAULT_OFFPEAK_RATE = 0.15

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_USAGE_DAYS, default=DEFAULT_USAGE_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=30)
        ),
        vol.Optional(CONF_PEAK_RATE, description="Override peak rate (leave empty to fetch from bill)"): vol.All(
            vol.Coerce(float), vol.Range(min=0.01, max=5.0)
        ),
        vol.Optional(CONF_OFFPEAK_RATE, description="Override off-peak rate (leave empty to fetch from bill)"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=5.0)
        ),
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    api = ContactEnergyApi(data[CONF_EMAIL], data[CONF_PASSWORD])

    # Run the blocking login call in executor
    login_success = await hass.async_add_executor_job(api.login)

    if not login_success:
        raise InvalidAuth

    # Return info to store in the config entry
    return {
        "title": f"Contact Energy ({data[CONF_EMAIL]})",
        "account_id": api._accountId,
        "contract_id": api._contractId,
    }


class ContactEnergyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Contact Energy."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return ContactEnergyOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Check if already configured
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class ContactEnergyOptionsFlow(OptionsFlow):
    """Handle options flow for Contact Energy."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current values from config entry
        current_usage_days = self.config_entry.data.get(CONF_USAGE_DAYS, DEFAULT_USAGE_DAYS)
        current_peak_rate = self.config_entry.data.get(CONF_PEAK_RATE)
        current_offpeak_rate = self.config_entry.data.get(CONF_OFFPEAK_RATE)

        # Create schema with current values as defaults
        options_schema = vol.Schema({
            vol.Optional(CONF_USAGE_DAYS, default=current_usage_days): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=30)
            ),
            vol.Optional(CONF_PEAK_RATE, default=current_peak_rate): vol.All(
                vol.Coerce(float), vol.Range(min=0.01, max=5.0)
            ),
            vol.Optional(CONF_OFFPEAK_RATE, default=current_offpeak_rate): vol.All(
                vol.Coerce(float), vol.Range(min=0.0, max=5.0)
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Build options schema with current values
        current_usage_days = self.config_entry.data.get(CONF_USAGE_DAYS, DEFAULT_USAGE_DAYS)
        current_peak_rate = self.config_entry.data.get(CONF_PEAK_RATE)
        current_offpeak_rate = self.config_entry.data.get(CONF_OFFPEAK_RATE)

        options_schema = vol.Schema({
            vol.Optional(
                CONF_USAGE_DAYS,
                default=current_usage_days
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Optional(
                CONF_PEAK_RATE,
                default=current_peak_rate
            ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=5.0)),
            vol.Optional(
                CONF_OFFPEAK_RATE,
                default=current_offpeak_rate
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
