"""Config flow for Octopus Energy France integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OctopusAuthError, OctopusEnergyFrApiClient
from .const import (
    CONF_ACCOUNT_NUMBER,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class OctopusEnergyFrConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Octopus Energy France."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""
        self._accounts: list[dict] = []
        self._api_client: OctopusEnergyFrApiClient | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            self._api_client = OctopusEnergyFrApiClient(
                email=self._email,
                password=self._password,
                session=async_get_clientsession(self.hass),
            )

            try:
                authenticated = await self._api_client.authenticate()
                if not authenticated:
                    errors["base"] = "invalid_auth"
                else:
                    self._accounts = await self._api_client.get_accounts()
                    if not self._accounts:
                        errors["base"] = "no_accounts"
                    elif len(self._accounts) == 1:
                        account_number = self._accounts[0]["number"]
                        await self.async_set_unique_id(account_number)
                        self._abort_if_unique_id_configured()
                        return self._create_entry(account_number, user_input)
                    else:
                        return await self.async_step_account()

            except OctopusAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected error during config flow")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
            }),
            errors=errors,
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            account_number = user_input[CONF_ACCOUNT_NUMBER]
            await self.async_set_unique_id(account_number)
            self._abort_if_unique_id_configured()
            return self._create_entry(account_number, user_input)

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema({
                vol.Required(CONF_ACCOUNT_NUMBER): vol.In(
                    {a["number"]: a["number"] for a in self._accounts}
                ),
            }),
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            client = OctopusEnergyFrApiClient(
                email=reauth_entry.data[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                session=async_get_clientsession(self.hass),
            )
            try:
                if await client.authenticate():
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    )
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"email": reauth_entry.data.get(CONF_EMAIL, "")},
        )

    def _create_entry(
        self, account_number: str, form_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title=f"Octopus Energy France — {account_number}",
            data={
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_ACCOUNT_NUMBER: account_number,
                CONF_SCAN_INTERVAL: form_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OctopusEnergyFrOptionsFlow(config_entry)


class OctopusEnergyFrOptionsFlow(config_entries.OptionsFlow):
    """Handle options (scan interval)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
            }),
        )
