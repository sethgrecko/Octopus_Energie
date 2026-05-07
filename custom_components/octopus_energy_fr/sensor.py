"""Sensor platform for Octopus Energy France."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import OctopusEnergyFrCoordinator
from .coordinator_intelligent import OctopusIntelligentCoordinator
from .sensors.descriptions import (
    ELECTRICITY_INDEX_SENSORS,
    ELECTRICITY_SENSORS,
    GAS_SENSORS,
    LATEST_READING_SENSOR,
    LEDGER_SENSORS,
)
from .sensors.electricity import (
    OctopusElectricityIndexSensor,
    OctopusElectricitySensor,
    OctopusLatestReadingSensor,
)
from .sensors.gas import OctopusGasSensor
from .sensors.ledger import OctopusLedgerSensor

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all Octopus Energy France sensor entities."""
    coordinator: OctopusEnergyFrCoordinator = entry.runtime_data.coordinator
    account_number: str = entry.runtime_data.account_number
    intelligent_coordinator: OctopusIntelligentCoordinator | None = (
        entry.runtime_data.intelligent_coordinator
    )

    data = coordinator.data or {}
    supply_points = data.get("supply_points") or {}
    ledgers = data.get("ledgers") or {}
    agreements = data.get("agreements") or []

    entities: list = []

    # ---- Ledger sensors (per account) ----
    for cfg in LEDGER_SENSORS:
        if cfg.ledger_type in ledgers:
            entities.append(OctopusLedgerSensor(coordinator, account_number, cfg))

    # ---- Electricity sensors (per active PRM) ----
    for meter in supply_points.get("electricity") or []:
        prm_id = meter.get("prm")
        if not prm_id:
            continue

        tariff_type = _detect_tariff_type(data, prm_id)

        for cfg in ELECTRICITY_SENSORS:
            key = cfg.key
            if key in ("contract", "subscribed_power", "subscription"):
                entities.append(OctopusElectricitySensor(coordinator, prm_id, cfg))
            elif tariff_type == "BASE" and key in ("energy_base", "cost_base", "rate_base"):
                entities.append(OctopusElectricitySensor(coordinator, prm_id, cfg))
            elif tariff_type == "HPHC" and key in (
                "energy_peak_hours", "energy_off_peak_hours",
                "cost_peak_hours", "cost_off_peak_hours",
                "rate_peak_hours", "rate_off_peak_hours",
            ):
                entities.append(OctopusElectricitySensor(coordinator, prm_id, cfg))

        entities.append(OctopusLatestReadingSensor(coordinator, prm_id, LATEST_READING_SENSOR))

        index_data = data.get("electricity", {}).get(prm_id, {}).get("index")
        if index_data:
            tariff_type_idx = index_data.get("tariff_type")
            for idx_cfg in ELECTRICITY_INDEX_SENSORS:
                if (tariff_type_idx == "BASE" and idx_cfg.index_type == "base") or (
                    tariff_type_idx == "HPHC" and idx_cfg.index_type in ("hp", "hc")
                ):
                    entities.append(OctopusElectricityIndexSensor(coordinator, prm_id, idx_cfg))

    # ---- Gas sensors (per PCE) ----
    for meter in supply_points.get("gas") or []:
        pce_ref = meter.get("prm")
        if not pce_ref:
            continue
        for cfg in GAS_SENSORS:
            entities.append(OctopusGasSensor(coordinator, pce_ref, cfg))

    # ---- Intelligent sensors (optional, per EV device) ----
    if intelligent_coordinator and (intelligent_coordinator.data or {}).get("devices"):
        for device in intelligent_coordinator.data["devices"]:
            device_id = device.get("id")
            if not device_id:
                continue
            device_name = device.get("name") or device_id
            entities.extend([
                OctopusVehicleStatusSensor(intelligent_coordinator, account_number, device_id, device_name),
                OctopusWeekdayTargetSocSensor(intelligent_coordinator, account_number, device_id, device_name),
                OctopusWeekdayTargetTimeSensor(intelligent_coordinator, account_number, device_id, device_name),
                OctopusWeekendTargetSocSensor(intelligent_coordinator, account_number, device_id, device_name),
                OctopusWeekendTargetTimeSensor(intelligent_coordinator, account_number, device_id, device_name),
                OctopusPlannedDispatchesSensor(intelligent_coordinator, account_number, device_id, device_name),
            ])

    async_add_entities(entities)


def _detect_tariff_type(data: dict, prm_id: str) -> str:
    """Detect BASE or HPHC tariff for a given PRM."""
    elec = data.get("electricity", {}).get(prm_id, {})

    # 1. From readings statistics labels
    readings = elec.get("readings") or []
    if readings:
        stats = (readings[-1].get("metaData") or {}).get("statistics") or []
        labels = {s.get("label") for s in stats}
        if "BASE" in labels:
            return "BASE"
        if "HEURES_PLEINES" in labels or "HEURES_CREUSES" in labels:
            return "HPHC"

    # 2. From index tariff_type
    index = elec.get("index") or {}
    tariff_type = index.get("tariff_type")
    if tariff_type in ("BASE", "HPHC"):
        return tariff_type

    # 3. From agreement tariffs
    tariffs = elec.get("tariffs") or {}
    consumption = tariffs.get("consumption") or {}
    if "base" in consumption:
        return "BASE"
    if "heures_pleines" in consumption or "heures_creuses" in consumption:
        return "HPHC"

    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Intelligent vehicle sensors
# ---------------------------------------------------------------------------


def _device_info(domain: str, device_id: str, account_number: str, device_name: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(domain, device_id)},
        via_device=(domain, account_number),
        name=device_name,
        model=device_name,
    )


class OctopusVehicleStatusSensor(CoordinatorEntity, SensorEntity):
    """Current EV charging state."""

    def __init__(self, coordinator: OctopusIntelligentCoordinator, account_number: str, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_vehicle_status"
        self._attr_translation_key = "vehicle_status"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:ev-station"
        self._attr_device_info = _device_info(DOMAIN, device_id, account_number, device_name)

    def _device(self) -> dict:
        return self.coordinator.get_device(self._device_id) or {}

    @property
    def native_value(self) -> str | None:
        status = self._device().get("status") or {}
        return status.get("currentState") or status.get("current")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self._device()
        status = device.get("status") or {}
        return {
            "device_id": self._device_id,
            "name": device.get("name"),
            "is_active": self.coordinator.is_device_active(self._device_id),
            "current": status.get("current"),
        }


class OctopusWeekdayTargetSocSensor(CoordinatorEntity, SensorEntity):
    """Target battery level for weekday charging."""

    def __init__(self, coordinator: OctopusIntelligentCoordinator, account_number: str, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_weekday_target_soc"
        self._attr_translation_key = "weekday_target_soc"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:battery-charging-high"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_info = _device_info(DOMAIN, device_id, account_number, device_name)

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data or {}).get("preferences", {}).get("weekdayTargetSoc")


class OctopusWeekdayTargetTimeSensor(CoordinatorEntity, SensorEntity):
    """Target completion time for weekday charging."""

    def __init__(self, coordinator: OctopusIntelligentCoordinator, account_number: str, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_weekday_target_time"
        self._attr_translation_key = "weekday_target_time"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:clock-outline"
        self._attr_device_info = _device_info(DOMAIN, device_id, account_number, device_name)

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("preferences", {}).get("weekdayTargetTime")


class OctopusWeekendTargetSocSensor(CoordinatorEntity, SensorEntity):
    """Target battery level for weekend charging."""

    def __init__(self, coordinator: OctopusIntelligentCoordinator, account_number: str, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_weekend_target_soc"
        self._attr_translation_key = "weekend_target_soc"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:battery-charging-high"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_info = _device_info(DOMAIN, device_id, account_number, device_name)

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data or {}).get("preferences", {}).get("weekendTargetSoc")


class OctopusWeekendTargetTimeSensor(CoordinatorEntity, SensorEntity):
    """Target completion time for weekend charging."""

    def __init__(self, coordinator: OctopusIntelligentCoordinator, account_number: str, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_weekend_target_time"
        self._attr_translation_key = "weekend_target_time"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:clock-outline"
        self._attr_device_info = _device_info(DOMAIN, device_id, account_number, device_name)

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("preferences", {}).get("weekendTargetTime")


class OctopusPlannedDispatchesSensor(CoordinatorEntity, SensorEntity):
    """Upcoming smart-charge windows for an EV device."""

    def __init__(self, coordinator: OctopusIntelligentCoordinator, account_number: str, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_planned_dispatches"
        self._attr_translation_key = "planned_dispatches"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:calendar-clock"
        self._attr_device_info = _device_info(DOMAIN, device_id, account_number, device_name)

    def _dispatches(self) -> list[dict]:
        return (self.coordinator.data or {}).get("dispatches", {}).get(self._device_id) or []

    @staticmethod
    def _fmt(timestamp: str | None) -> str | None:
        if not timestamp:
            return None
        dt = dt_util.parse_datetime(timestamp)
        return dt_util.as_local(dt).strftime("%d/%m %H:%M") if dt else timestamp

    @staticmethod
    def _duration_min(d: dict) -> int | None:
        try:
            start = dt_util.parse_datetime(d.get("start") or "")
            end = dt_util.parse_datetime(d.get("end") or "")
            return int((end - start).total_seconds() / 60) if start and end else None
        except (ValueError, TypeError, AttributeError):
            return None

    @property
    def native_value(self) -> str:
        dispatches = self._dispatches()
        n = len(dispatches)
        return f"{n} programmée{'s' if n > 1 else ''}" if n else "Aucune"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dispatches = self._dispatches()
        detailed = [
            {
                "start": d.get("start"),
                "end": d.get("end"),
                "start_local": self._fmt(d.get("start")),
                "end_local": self._fmt(d.get("end")),
                "duration_minutes": self._duration_min(d),
            }
            for d in dispatches
        ]
        formatted = [
            f"{self._fmt(d.get('start'))} → {self._fmt(d.get('end'))}"
            for d in dispatches if d.get("start") and d.get("end")
        ]
        return {
            "count": len(dispatches),
            "next_dispatch": detailed[0] if detailed else None,
            "formatted_list": formatted,
            "dispatches_json": json.dumps(detailed, ensure_ascii=False),
        }
