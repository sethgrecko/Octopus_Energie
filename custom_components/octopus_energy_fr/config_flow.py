"""Config flow Octopus Energy France."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .api import OctopusAuthError, OctopusEnergyFrApiClient
from .const import (
    CONF_ACCOUNT_ID,
    CONF_API_KEY,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)


class OctopusEnergyFrConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Flow de configuration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_ACCOUNT_ID])
            self._abort_if_unique_id_configured()

            client = OctopusEnergyFrApiClient(
                self.hass.helpers.aiohttp_client.async_get_clientsession(),
                user_input[CONF_API_KEY],
                user_input[CONF_ACCOUNT_ID],
            )

            try:
                await client.async_validate_credentials()
            except OctopusAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=f"Octopus {user_input[CONF_ACCOUNT_ID]}", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_ACCOUNT_ID): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OctopusEnergyFrOptionsFlow(config_entry)


class OctopusEnergyFrOptionsFlow(config_entries.OptionsFlow):
    """Gestion options."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL,
                        self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL))
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
