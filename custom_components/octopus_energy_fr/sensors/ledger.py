"""Ledger / financial sensor entities for Octopus Energy France."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from ..coordinator import OctopusEnergyFrCoordinator
from .descriptions import OctopusLedgerSensorDescription

_LOGGER = logging.getLogger(__name__)


class OctopusLedgerSensor(CoordinatorEntity, SensorEntity):
    """Account ledger balance or last invoice amount."""

    def __init__(
        self,
        coordinator: OctopusEnergyFrCoordinator,
        account_number: str,
        sensor_config: OctopusLedgerSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._ledger_type = sensor_config.ledger_type
        self._sensor_config = sensor_config
        self._attr_unique_id = f"{DOMAIN}_{account_number}_{sensor_config.key}"
        self._attr_translation_key = sensor_config.key
        self._attr_has_entity_name = True
        self._attr_icon = sensor_config.icon
        self._attr_device_class = sensor_config.device_class
        self._attr_state_class = sensor_config.state_class
        self._attr_native_unit_of_measurement = sensor_config.native_unit_of_measurement
        self._attr_entity_category = sensor_config.entity_category
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, account_number)})
        if sensor_config.suggested_display_precision is not None:
            self._attr_suggested_display_precision = sensor_config.suggested_display_precision

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None

        key = self._sensor_config.key

        if "bill" in key:
            payment = (self.coordinator.data.get("payment_requests") or {}).get(self._ledger_type)
            if not payment:
                return None
            amount = payment.get("customerAmount")
            return amount / 100 if amount is not None else None

        # Credit/balance ledger
        ledger = (self.coordinator.data.get("ledgers") or {}).get(self._ledger_type) or {}
        balance = ledger.get("balance")
        return balance / 100 if balance is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {"ledger_type": self._ledger_type}

        key = self._sensor_config.key

        if "bill" in key:
            payment = (self.coordinator.data.get("payment_requests") or {}).get(self._ledger_type)
            if payment:
                return {
                    "ledger_type": self._ledger_type,
                    "payment_status": (payment.get("paymentStatus") or "").lower(),
                    "total_amount_eur": (payment.get("totalAmount") or 0) / 100,
                    "customer_amount_eur": (payment.get("customerAmount") or 0) / 100,
                    "expected_payment_date": payment.get("expectedPaymentDate"),
                }
            return {"ledger_type": self._ledger_type, "status": "no_data"}

        ledger = (self.coordinator.data.get("ledgers") or {}).get(self._ledger_type) or {}
        return {
            "ledger_type": self._ledger_type,
            "ledger_number": ledger.get("number"),
            "ledger_name": ledger.get("name"),
            "balance_cents": ledger.get("balance"),
        }
