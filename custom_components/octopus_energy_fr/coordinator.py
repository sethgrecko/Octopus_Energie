"""Data update coordinator Octopus Energy France."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OctopusApiError, OctopusEnergyFrApiClient
from .const import CONF_ACCOUNT_ID, CONF_API_KEY, DOMAIN

_LOGGER = logging.getLogger(__name__)


class OctopusEnergyFrCoordinator(DataUpdateCoordinator):
    """Coordinator pour les données octopus."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, update_interval: timedelta) -> None:
        self.entry = entry
        self.api = OctopusEnergyFrApiClient(
            session=async_get_clientsession(hass),
            api_key=entry.data[CONF_API_KEY],
            account_id=entry.data[CONF_ACCOUNT_ID],
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        try:
            return await self.api.async_fetch_dashboard()
        except OctopusApiError as err:
            raise UpdateFailed(f"Erreur de mise à jour Octopus: {err}") from err
