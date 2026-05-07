"""Number entities for Octopus Intelligent SOC targets."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
        entities.extend([
            OctopusWeekdaySocNumber(intelligent_coordinator, account_number, device_id, device_name),
            OctopusWeekendSocNumber(intelligent_coordinator, account_number, device_id, device_name),
        ])

    async_add_entities(entities)


class _OctopusSocNumber(CoordinatorEntity, NumberEntity):
    """Base class for a SOC target number."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 10.0
    _attr_native_max_value = 100.0
    _attr_native_step = 5.0
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:battery-charging-high"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: OctopusIntelligentCoordinator,
        account_number: str,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._account_number = account_number
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            via_device=(DOMAIN, account_number),
            name=device_name,
            model=device_name,
        )

    def _preferences(self) -> dict:
        return (self.coordinator.data or {}).get("preferences") or {}


class OctopusWeekdaySocNumber(_OctopusSocNumber):
    """Weekday SOC target (%)."""

    def __init__(self, coordinator: OctopusIntelligentCoordinator, account_number: str, device_id: str, device_name: str) -> None:
        super().__init__(coordinator, account_number, device_id, device_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_weekday_soc_target"
        self._attr_translation_key = "weekday_soc_target"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float | None:
        val = self._preferences().get("weekdayTargetSoc")
        return float(val) if val is not None else None

    async def async_set_native_value(self, value: float) -> None:
        success = await self.coordinator.intelligent_client.set_target_soc(
            self._account_number, self._device_id, weekday_soc=int(value)
        )
        if success:
            await self.coordinator.async_request_refresh()


class OctopusWeekendSocNumber(_OctopusSocNumber):
    """Weekend SOC target (%)."""

    def __init__(self, coordinator: OctopusIntelligentCoordinator, account_number: str, device_id: str, device_name: str) -> None:
        super().__init__(coordinator, account_number, device_id, device_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_weekend_soc_target"
        self._attr_translation_key = "weekend_soc_target"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float | None:
        val = self._preferences().get("weekendTargetSoc")
        return float(val) if val is not None else None

    async def async_set_native_value(self, value: float) -> None:
        success = await self.coordinator.intelligent_client.set_target_soc(
            self._account_number, self._device_id, weekend_soc=int(value)
        )
        if success:
            await self.coordinator.async_request_refresh()
