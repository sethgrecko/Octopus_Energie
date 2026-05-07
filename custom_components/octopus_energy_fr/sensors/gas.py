"""Gas sensor entities for Octopus Energy France."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..coordinator import OctopusEnergyFrCoordinator

_LOGGER = logging.getLogger(__name__)

_POWERED_STATUS_MAP = {
    "EN_SERVICE": "En service",
    "COUPE": "Coupé",
    "COUPE_DISTRIBUTEUR": "Coupé (distributeur)",
    "RESILIE": "Résilié",
}


class OctopusGasSensor(CoordinatorEntity, SensorEntity):
    """Monthly gas consumption / cost / tariff / contract sensor."""

    def __init__(
        self,
        coordinator: OctopusEnergyFrCoordinator,
        pce_ref: str,
        sensor_config: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._pce_ref = pce_ref
        self._sensor_config = sensor_config
        self._attr_unique_id = f"{DOMAIN}_{pce_ref}_{sensor_config.key}"
        self._attr_translation_key = sensor_config.key
        self._attr_has_entity_name = True
        self._attr_icon = sensor_config.icon
        self._attr_device_class = sensor_config.device_class
        self._attr_state_class = sensor_config.state_class
        self._attr_native_unit_of_measurement = sensor_config.native_unit_of_measurement
        self._attr_entity_category = sensor_config.entity_category
        self._attr_suggested_display_precision = sensor_config.suggested_display_precision
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, pce_ref)})

        self._current_month: str | None = None
        self._last_imported_date: str | None = None
        self._statistics_imported = False

    # ------------------------------------------------------------------
    # Data accessors
    # ------------------------------------------------------------------

    def _gas_data(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("gas", {}).get(self._pce_ref, {})

    def _readings(self) -> list[dict]:
        return self._gas_data().get("readings") or []

    def _tariffs(self) -> dict | None:
        return self._gas_data().get("tariffs")

    def _tariff_rate(self) -> float | None:
        tariffs = self._tariffs() or {}
        consumption = tariffs.get("consumption") or {}
        rate = consumption.get("base") or {}
        val = rate.get("price_ttc")
        return float(val) if val is not None else None

    def _meter_data(self) -> dict | None:
        gas_points = (self.coordinator.data or {}).get("supply_points", {}).get("gas") or []
        return next((m for m in gas_points if m.get("prm") == self._pce_ref), None)

    def _active_agreement(self) -> dict | None:
        agreements = (self.coordinator.data or {}).get("agreements") or []
        return next(
            (a for a in agreements if a.get("prm") == self._pce_ref and a.get("is_active")),
            None,
        )

    # ------------------------------------------------------------------
    # Statistics import lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._sensor_config.key == "gas_consumption":
            self.hass.async_create_task(self._async_import_statistics())

    def _handle_coordinator_update(self) -> None:
        if self._sensor_config.key == "gas_consumption" and not self._statistics_imported:
            self.hass.async_create_task(self._async_import_statistics())
        super()._handle_coordinator_update()

    async def _async_import_statistics(self) -> None:
        readings = self._readings()
        if not readings or not self.entity_id:
            return

        statistic_id = f"{DOMAIN}:{self._pce_ref}_gas_consumption"
        current_month = dt_util.now().strftime("%Y-%m")

        if self._statistics_imported and self._current_month == current_month:
            return

        cumulative_sum = 0.0
        with suppress(Exception):
            last_stats = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, False, {"sum", "start"}
            )
            if last_stats and last_stats.get(statistic_id):
                entry = last_stats[statistic_id][0]
                cumulative_sum = float(entry.get("sum") or 0.0)
                if not self._last_imported_date:
                    ts = entry.get("start")
                    if ts is not None:
                        self._last_imported_date = datetime.fromtimestamp(
                            float(ts), tz=dt_util.UTC
                        ).isoformat()

        statistics: list[StatisticData] = []
        sorted_readings = sorted(readings, key=lambda x: x.get("startAt") or "")

        for reading in sorted_readings:
            reading_date = reading.get("startAt")
            if not reading_date:
                continue
            if self._last_imported_date and reading_date <= self._last_imported_date:
                continue

            try:
                date_obj = datetime.fromisoformat(reading_date)
                date_local = date_obj.astimezone(dt_util.DEFAULT_TIME_ZONE)
                date_normalized = date_local.replace(hour=0, minute=0, second=0, microsecond=0)
            except (ValueError, TypeError, AttributeError):
                continue

            val = reading.get("value")
            if val is None:
                continue
            reading_value = float(val)
            if reading_value <= 0:
                continue

            cumulative_sum += reading_value
            statistics.append(StatisticData(
                start=date_normalized, state=reading_value, sum=cumulative_sum
            ))
            self._last_imported_date = reading_date

        if not statistics:
            return

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Octopus Energy — {self._pce_ref} gas",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class="energy",
            unit_of_measurement=self._attr_native_unit_of_measurement,
        )

        with suppress(Exception):
            async_add_external_statistics(self.hass, metadata, statistics)
            self._statistics_imported = True
            self._current_month = current_month
            _LOGGER.debug(
                "Imported %d gas statistics for %s", len(statistics), statistic_id
            )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def native_value(self) -> float | str | None:
        key = self._sensor_config.key
        if not self.coordinator.data:
            return None

        if key == "gas_contract":
            meter = self._meter_data()
            if not meter:
                return None
            powered = meter.get("poweredStatus") or ""
            return _POWERED_STATUS_MAP.get(powered, powered or "Inconnu")

        if key == "gas_subscription":
            return self._calculate_monthly_subscription()

        if key == "gas_rate":
            return self._tariff_rate()

        if key == "gas_consumption":
            self._current_month = dt_util.now().strftime("%Y-%m")
            return self._calculate_monthly_total()

        if key == "gas_cost":
            return self._calculate_monthly_cost()

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        key = self._sensor_config.key
        if not self.coordinator.data:
            return {}

        if key == "gas_contract":
            meter = self._meter_data() or {}
            return {
                "pce_ref": self._pce_ref,
                "gas_nature": meter.get("gasNature"),
                "annual_consumption_kwh": meter.get("annualConsumption"),
                "is_smart_meter": meter.get("isSmartMeter"),
                "powered_status": meter.get("poweredStatus"),
                "serial": meter.get("serial"),
                "contractual_status": meter.get("contractualStatus"),
                "cut_date": meter.get("cutDate"),
            }

        if key == "gas_subscription":
            agreement = self._active_agreement() or {}
            tariffs = agreement.get("tariffs") or {}
            subscription = tariffs.get("subscription") or {}
            next_pay = agreement.get("next_payment") or {}
            return {
                "contract_number": agreement.get("contract_number"),
                "product_name": (agreement.get("product") or {}).get("display_name"),
                "annual_ht_eur": subscription.get("annual_ht_eur"),
                "annual_ttc_eur": subscription.get("annual_ttc_eur"),
                "monthly_ttc_eur": subscription.get("monthly_ttc_eur"),
                "billing_frequency_months": agreement.get("billing_frequency_months"),
                "valid_from": agreement.get("valid_from"),
                "next_payment_amount": (next_pay.get("amount") / 100) if next_pay.get("amount") else None,
                "next_payment_date": next_pay.get("date"),
            }

        if key == "gas_rate":
            tariffs = (self._tariffs() or {}).get("consumption") or {}
            rate = tariffs.get("base") or {}
            agreement = self._active_agreement() or {}
            return {
                "price_ht_eur_kwh": rate.get("price_ht"),
                "price_ttc_eur_kwh": rate.get("price_ttc"),
                "contract_number": agreement.get("contract_number"),
                "product_name": (agreement.get("product") or {}).get("display_name"),
                "valid_from": agreement.get("valid_from"),
            }

        if key == "gas_consumption":
            readings = self._readings()
            last = readings[-1] if readings else {}
            return {
                "pce_ref": self._pce_ref,
                "current_month": self._current_month,
                "readings_count": len(readings),
                "last_reading_date": last.get("startAt"),
                "last_index_start": last.get("indexStartValue"),
                "last_index_end": last.get("indexEndValue"),
                "last_status": last.get("statusProcessed"),
                "last_imported_date": self._last_imported_date,
            }

        if key == "gas_cost":
            return {
                "pce_ref": self._pce_ref,
                "current_month": dt_util.now().strftime("%Y-%m"),
                "tariff_rate_ttc": self._tariff_rate(),
            }

        return {}

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    def _calculate_monthly_total(self) -> float | None:
        readings = self._readings()
        if not readings:
            return None

        current_month = dt_util.now().strftime("%Y-%m")
        total = 0.0
        found = False

        for reading in readings:
            date_str = reading.get("startAt") or ""
            try:
                if datetime.fromisoformat(date_str).strftime("%Y-%m") != current_month:
                    continue
            except (ValueError, TypeError):
                continue
            val = reading.get("value")
            if val is not None:
                total += float(val)
                found = True

        return round(total, 3) if found else None

    def _calculate_monthly_cost(self) -> float | None:
        total_kwh = self._calculate_monthly_total()
        rate = self._tariff_rate()
        if total_kwh is None or not rate:
            return None
        return round(total_kwh * rate, 2)

    def _calculate_monthly_subscription(self) -> float | None:
        tariffs = self._tariffs() or {}
        subscription = tariffs.get("subscription") or {}
        monthly = subscription.get("monthly_ttc_eur")
        if monthly is not None:
            return round(float(monthly), 2)
        return None
