"""Binary sensors for Octopus Intelligent (EV charging) features."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator_intelligent import OctopusIntelligentCoordinator

PARALLEL_UPDATES = 0


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
            OctopusChargingBinarySensor(
                intelligent_coordinator, account_number, device_id, device_name
            )
        )

    async_add_entities(entities)


class OctopusChargingBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Is the EV currently charging (smart-controlled or boosted)?"""

    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(
        self,
        coordinator: OctopusIntelligentCoordinator,
        account_number: str,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_is_charging"
        self._attr_translation_key = "is_charging"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:ev-plug-type2"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            via_device=(DOMAIN, account_number),
            name=device_name,
            model=device_name,
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_device_active(self._device_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self.coordinator.get_device(self._device_id) or {}
        status = device.get("status") or {}
        return {
            "device_id": self._device_id,
            "current_state": status.get("currentState") or status.get("current"),
        }
