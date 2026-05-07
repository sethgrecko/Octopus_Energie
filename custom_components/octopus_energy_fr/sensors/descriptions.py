"""Sensor entity description dataclasses for Octopus Energy France."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CURRENCY_EURO,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
)

# ---------------------------------------------------------------------------
# Custom description types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class OctopusIndexSensorDescription(SensorEntityDescription):
    """Sensor description for Linky index (cumulative counter)."""

    index_type: str = ""


@dataclass(frozen=True, kw_only=True)
class OctopusLedgerSensorDescription(SensorEntityDescription):
    """Sensor description for an account ledger."""

    ledger_type: str = ""


# ---------------------------------------------------------------------------
# Electricity sensors (per PRM)
# ---------------------------------------------------------------------------

ELECTRICITY_SENSORS: list[SensorEntityDescription] = [
    SensorEntityDescription(
        key="contract",
        translation_key="contract",
        icon="mdi:file-sign",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="subscribed_power",
        translation_key="subscribed_power",
        icon="mdi:lightning-bolt-circle",
        native_unit_of_measurement="kVA",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="subscription",
        translation_key="subscription",
        icon="mdi:calendar-month",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    # ---- Base tariff ----
    SensorEntityDescription(
        key="energy_base",
        translation_key="energy_base",
        icon="mdi:flash",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="cost_base",
        translation_key="cost_base",
        icon="mdi:currency-eur",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="rate_base",
        translation_key="rate_base",
        icon="mdi:tag",
        native_unit_of_measurement="€/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=4,
    ),
    # ---- HP/HC tariff ----
    SensorEntityDescription(
        key="energy_peak_hours",
        translation_key="energy_peak_hours",
        icon="mdi:flash",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="energy_off_peak_hours",
        translation_key="energy_off_peak_hours",
        icon="mdi:flash-off",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="cost_peak_hours",
        translation_key="cost_peak_hours",
        icon="mdi:currency-eur",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="cost_off_peak_hours",
        translation_key="cost_off_peak_hours",
        icon="mdi:currency-eur",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="rate_peak_hours",
        translation_key="rate_peak_hours",
        icon="mdi:tag",
        native_unit_of_measurement="€/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=4,
    ),
    SensorEntityDescription(
        key="rate_off_peak_hours",
        translation_key="rate_off_peak_hours",
        icon="mdi:tag-off",
        native_unit_of_measurement="€/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=4,
    ),
]

LATEST_READING_SENSOR = SensorEntityDescription(
    key="latest_reading",
    translation_key="latest_reading",
    icon="mdi:counter",
    device_class=SensorDeviceClass.ENERGY,
    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    suggested_display_precision=3,
)

ELECTRICITY_INDEX_SENSORS: list[OctopusIndexSensorDescription] = [
    OctopusIndexSensorDescription(
        key="index_base",
        translation_key="index_base",
        index_type="base",
        icon="mdi:counter",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
    OctopusIndexSensorDescription(
        key="index_hp",
        translation_key="index_hp",
        index_type="hp",
        icon="mdi:counter",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
    OctopusIndexSensorDescription(
        key="index_hc",
        translation_key="index_hc",
        index_type="hc",
        icon="mdi:counter",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
]

# ---------------------------------------------------------------------------
# Gas sensors (per PCE)
# ---------------------------------------------------------------------------

GAS_SENSORS: list[SensorEntityDescription] = [
    SensorEntityDescription(
        key="gas_consumption",
        translation_key="gas_consumption",
        icon="mdi:fire",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="gas_cost",
        translation_key="gas_cost",
        icon="mdi:currency-eur",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="gas_contract",
        translation_key="gas_contract",
        icon="mdi:file-sign",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="gas_subscription",
        translation_key="gas_subscription",
        icon="mdi:calendar-month",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="gas_rate",
        translation_key="gas_rate",
        icon="mdi:tag",
        native_unit_of_measurement="€/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=4,
    ),
]

# ---------------------------------------------------------------------------
# Ledger / financial sensors (per account)
# ---------------------------------------------------------------------------

LEDGER_SENSORS: list[OctopusLedgerSensorDescription] = [
    OctopusLedgerSensorDescription(
        key="credit_balance",
        translation_key="credit_balance",
        ledger_type="POT_LEDGER",
        icon="mdi:piggy-bank-outline",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    OctopusLedgerSensorDescription(
        key="electricity_bill",
        translation_key="electricity_bill",
        ledger_type="FRA_ELECTRICITY_LEDGER",
        icon="mdi:file-document-outline",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    OctopusLedgerSensorDescription(
        key="gas_bill",
        translation_key="gas_bill",
        ledger_type="FRA_GAS_LEDGER",
        icon="mdi:file-document-outline",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
]
