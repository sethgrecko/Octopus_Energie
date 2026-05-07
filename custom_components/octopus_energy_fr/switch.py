"""Switch entities for Octopus Intelligent boost charging."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator_intelligent import OctopusIntelligentCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    intelligent_coordinator: OctopusIntelligentCoordinator | None = (
        entry.runtime_data.intelligent_coordinator
    )
    if not intelligent_coordinator:
        return

    data = intelligent_coordinator.data or {}
    account_number = entry.runtime_data.account_number
    entities = []

    for device in data.get("devices") or []:
        device_id = device.get("id")
        if not device_id:
            continue
        device_name = device.get("name") or device_id
        entities.append(
            OctopusBoostChargeSwitch(
                intelligent_coordinator, account_number, device_id, device_name
            )
        )

    async_add_entities(entities)


class OctopusBoostChargeSwitch(CoordinatorEntity, SwitchEntity):
    """Trigger or cancel a boost charge session for an EV."""

    def __init__(
        self,
        coordinator: OctopusIntelligentCoordinator,
        account_number: str,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_boost_charge"
        self._attr_translation_key = "boost_charge"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:lightning-bolt"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            via_device=(DOMAIN, account_number),
            name=device_name,
            model=device_name,
        )

    @property
    def is_on(self) -> bool:
        device = self.coordinator.get_device(self._device_id) or {}
        status = device.get("status") or {}
        state = status.get("currentState") or status.get("current")
        return state == "BOOSTING"

    async def async_turn_on(self, **kwargs: Any) -> None:
        success = await self.coordinator.intelligent_client.trigger_boost_charge(self._device_id)
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to trigger boost charge for device %s", self._device_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        success = await self.coordinator.intelligent_client.cancel_boost_charge(self._device_id)
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to cancel boost charge for device %s", self._device_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self.coordinator.get_device(self._device_id) or {}
        status = device.get("status") or {}
        return {
            "device_id": self._device_id,
            "current_state": status.get("currentState") or status.get("current"),
        }
