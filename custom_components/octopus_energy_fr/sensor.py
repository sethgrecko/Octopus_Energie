"""Capteurs Octopus Energy France."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


@dataclass(frozen=True, kw_only=True)
class OctopusSensorDescription(SensorEntityDescription):
    value_key: str


SENSORS = [
    OctopusSensorDescription(
        key="balance",
        name="Solde compte",
        icon="mdi:wallet",
        native_unit_of_measurement=CURRENCY_EURO,
        value_key="balance",
    ),
    OctopusSensorDescription(
        key="last_bill_amount",
        name="Dernière facture",
        icon="mdi:file-document-outline",
        native_unit_of_measurement=CURRENCY_EURO,
        value_key="last_bill_amount",
    ),
    OctopusSensorDescription(
        key="electricity_today_kwh",
        name="Électricité aujourd'hui",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_key="electricity_today_kwh",
    ),
    OctopusSensorDescription(
        key="gas_today_kwh",
        name="Gaz aujourd'hui",
        icon="mdi:fire",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_key="gas_today_kwh",
    ),
    OctopusSensorDescription(
        key="electricity_unit_rate",
        name="Prix électricité",
        icon="mdi:currency-eur",
        native_unit_of_measurement="€/kWh",
        value_key="electricity_unit_rate",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(OctopusEnergyFrSensor(coordinator, entry, desc) for desc in SENSORS)


class OctopusEnergyFrSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry: ConfigEntry, description: OctopusSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        return self.coordinator.data.get(self.entity_description.value_key)
