"""Data update coordinator for Octopus Intelligent (EV charging) features."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.intelligent import OctopusIntelligentApiClient

if TYPE_CHECKING:
    from .api import OctopusEnergyFrApiClient

_LOGGER = logging.getLogger(__name__)

ACTIVE_CHARGING_STATES = frozenset({
    "BOOSTING",
    "SMART_CONTROL_IN_PROGRESS",
    "TEST_CHARGE_IN_PROGRESS",
})


class OctopusIntelligentCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls Octopus Intelligent for EV device state, preferences and dispatches."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: OctopusEnergyFrApiClient,
        account_number: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Octopus Intelligent",
            update_interval=timedelta(minutes=1),
        )
        self.intelligent_client = OctopusIntelligentApiClient(api_client)
        self.account_number = account_number

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        if not self.data:
            return None
        for device in self.data.get("devices") or []:
            if device.get("id") == device_id:
                return device
        return None

    def is_device_active(self, device_id: str) -> bool:
        device = self.get_device(device_id) or {}
        status = device.get("status") or {}
        state = status.get("currentState") or status.get("current")
        return state in ACTIVE_CHARGING_STATES

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            devices = await self.intelligent_client.get_devices(self.account_number)

            preferences: dict[str, Any] = {}
            dispatches: dict[str, list] = {}

            if devices:
                preferences = await self.intelligent_client.get_vehicle_charging_preferences(
                    self.account_number
                )
                dispatch_tasks = {
                    d["id"]: self.intelligent_client.get_flex_planned_dispatches(d["id"])
                    for d in devices if d.get("id")
                }
                if dispatch_tasks:
                    results = await asyncio.gather(
                        *dispatch_tasks.values(), return_exceptions=True
                    )
                    for (device_id, _), result in zip(dispatch_tasks.items(), results):
                        dispatches[device_id] = result if not isinstance(result, Exception) else []

            return {
                "devices": devices,
                "preferences": preferences,
                "dispatches": dispatches,
            }
        except Exception as err:
            raise UpdateFailed(f"Intelligent API error: {err}") from err
