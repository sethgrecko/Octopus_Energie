"""Electricity sensor entities for Octopus Energy France."""

from __future__ import annotations

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
from .descriptions import OctopusIndexSensorDescription

_LOGGER = logging.getLogger(__name__)

_CONSUMPTION_LABEL_MAP = {
    "energy_base": "BASE",
    "energy_peak_hours": "HEURES_PLEINES",
    "energy_off_peak_hours": "HEURES_CREUSES",
}
_COST_LABEL_MAP = {
    "cost_base": "BASE",
    "cost_peak_hours": "HEURES_PLEINES",
    "cost_off_peak_hours": "HEURES_CREUSES",
}


class OctopusElectricitySensor(CoordinatorEntity, SensorEntity):
    """Monthly electricity consumption / cost / tariff / contract sensor."""

    def __init__(
        self,
        coordinator: OctopusEnergyFrCoordinator,
        prm_id: str,
        sensor_config: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._prm_id = prm_id
        self._sensor_config = sensor_config
        self._attr_unique_id = f"{DOMAIN}_{prm_id}_{sensor_config.key}"
        self._attr_translation_key = sensor_config.key
        self._attr_has_entity_name = True
        self._attr_icon = sensor_config.icon
        self._attr_device_class = sensor_config.device_class
        self._attr_state_class = sensor_config.state_class
        self._attr_native_unit_of_measurement = sensor_config.native_unit_of_measurement
        self._attr_entity_category = sensor_config.entity_category
        self._attr_suggested_display_precision = sensor_config.suggested_display_precision
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, prm_id)})

        self._current_month: str | None = None
        self._last_imported_date: str | None = None
        self._statistics_imported = False

    # ------------------------------------------------------------------
    # Data accessors
    # ------------------------------------------------------------------

    def _elec_data(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("electricity", {}).get(self._prm_id, {})

    def _readings(self) -> list[dict]:
        return self._elec_data().get("readings") or []

    def _index(self) -> dict | None:
        return self._elec_data().get("index")

    def _tariffs(self) -> dict | None:
        return self._elec_data().get("tariffs")

    def _tariff_rate(self, key: str | None = None) -> float | None:
        k = key or self._sensor_config.key
        tariffs = self._tariffs() or {}
        consumption = tariffs.get("consumption") or {}
        mapping = {
            "rate_base": ("base", "price_ttc"),
            "cost_base": ("base", "price_ttc"),
            "rate_peak_hours": ("heures_pleines", "price_ttc"),
            "cost_peak_hours": ("heures_pleines", "price_ttc"),
            "rate_off_peak_hours": ("heures_creuses", "price_ttc"),
            "cost_off_peak_hours": ("heures_creuses", "price_ttc"),
        }
        if entry := mapping.get(k):
            rate_key, price_key = entry
            rate = consumption.get(rate_key) or {}
            return rate.get(price_key)
        return None

    def _active_agreement(self) -> dict | None:
        agreements = (self.coordinator.data or {}).get("agreements") or []
        return next(
            (a for a in agreements if a.get("prm") == self._prm_id and a.get("is_active")),
            None,
        )

    def _meter_data(self) -> dict | None:
        elec_points = (self.coordinator.data or {}).get("supply_points", {}).get("electricity") or []
        return next((m for m in elec_points if m.get("prm") == self._prm_id), None)

    # ------------------------------------------------------------------
    # Statistics import lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._sensor_config.key.startswith(("energy_", "cost_")):
            self.hass.async_create_task(
                self._async_import_statistics(),
                name=f"octopus_stats_elec_{self._prm_id}_{self._sensor_config.key}",
            )

    def _handle_coordinator_update(self) -> None:
        if self._sensor_config.key.startswith(("energy_", "cost_")):
            self.hass.async_create_task(
                self._async_import_statistics(),
                name=f"octopus_stats_elec_{self._prm_id}_{self._sensor_config.key}",
            )
        super()._handle_coordinator_update()

    async def _async_import_statistics(self) -> None:
        """Import historical statistics into HA recorder. Always safe to call."""
        try:
            await self._do_import_statistics()
        except Exception as err:
            _LOGGER.error(
                "Statistics import failed for %s/%s: %s",
                self._prm_id, self._sensor_config.key, err, exc_info=True,
            )

    async def _do_import_statistics(self) -> None:
        key = self._sensor_config.key
        readings = self._readings()

        if not readings or not self.entity_id:
            _LOGGER.debug("Stats [%s/%s]: no readings or entity_id not set, skipping", self._prm_id, key)
            return

        statistic_id = f"{DOMAIN}:{self._prm_id}_{key}"
        current_month = dt_util.now().strftime("%Y-%m")

        # Fast path: skip if already imported this month and no newer readings
        if self._statistics_imported and self._current_month == current_month:
            latest = readings[-1].get("startAt") if readings else None
            if latest and self._last_imported_date and latest <= self._last_imported_date:
                _LOGGER.debug("Stats [%s/%s]: up to date, skipping", self._prm_id, key)
                return

        # Resume cumulative sum from last stored statistic.
        # Store the DB's last-start as a proper UTC datetime to avoid timezone
        # string-comparison issues when reading_date uses local-time ISO format.
        cumulative_sum = 0.0
        last_start_dt: datetime | None = None
        try:
            last_stats = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, False, {"sum", "start"}
            )
            if last_stats and last_stats.get(statistic_id):
                entry = last_stats[statistic_id][0]
                cumulative_sum = float(entry.get("sum") or 0.0)
                ts = entry.get("start")
                if ts is not None:
                    last_start_dt = datetime.fromtimestamp(float(ts), tz=dt_util.UTC)
                _LOGGER.debug(
                    "Stats [%s/%s]: resuming from sum=%.3f, last_start=%s",
                    self._prm_id, key, cumulative_sum, last_start_dt,
                )
        except Exception as err:
            _LOGGER.debug("Stats [%s/%s]: could not load last stats: %s", self._prm_id, key, err)

        statistics: list[StatisticData] = []
        sorted_readings = sorted(readings, key=lambda x: x.get("startAt") or "")

        for reading in sorted_readings:
            reading_date = reading.get("startAt")
            if not reading_date:
                continue

            try:
                date_obj = datetime.fromisoformat(reading_date)
                date_local = date_obj.astimezone(dt_util.DEFAULT_TIME_ZONE)
                date_normalized = date_local.replace(hour=0, minute=0, second=0, microsecond=0)
            except (ValueError, TypeError, AttributeError):
                continue

            # Skip readings already in the DB (timezone-aware datetime comparison).
            if last_start_dt is not None and date_normalized <= last_start_dt:
                continue

            stat_list = (reading.get("metaData") or {}).get("statistics") or []
            reading_value = 0.0

            for stat in stat_list:
                label = stat.get("label") or ""
                if key in _CONSUMPTION_LABEL_MAP and label == _CONSUMPTION_LABEL_MAP[key]:
                    val = stat.get("value")
                    if val is not None:
                        reading_value = float(val)
                elif key in _COST_LABEL_MAP and label == _COST_LABEL_MAP[key]:
                    val = stat.get("value")
                    rate = self._tariff_rate()
                    if val is not None and rate:
                        reading_value = float(val) * rate

            if reading_value > 0:
                cumulative_sum += reading_value
                statistics.append(StatisticData(
                    start=date_normalized, state=reading_value, sum=cumulative_sum
                ))
                self._last_imported_date = reading_date

        if not statistics:
            _LOGGER.debug("Stats [%s/%s]: no new data points to import", self._prm_id, key)
            return

        unit_class = "energy" if key.startswith("energy_") else None
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Octopus Energy — {self._prm_id} {key}",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=unit_class,
            unit_of_measurement=self._attr_native_unit_of_measurement,
        )

        try:
            async_add_external_statistics(self.hass, metadata, statistics)
            self._statistics_imported = True
            self._current_month = current_month
            _LOGGER.debug(
                "Stats [%s/%s]: imported %d points, cumulative=%.3f, last=%s",
                self._prm_id, key, len(statistics), cumulative_sum, self._last_imported_date,
            )
        except Exception as err:
            _LOGGER.error(
                "Stats [%s/%s]: async_add_external_statistics failed: %s",
                self._prm_id, key, err, exc_info=True,
            )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def native_value(self) -> float | str | None:
        key = self._sensor_config.key

        if not self.coordinator.data:
            return None

        if key == "contract":
            meter = self._meter_data()
            if not meter:
                return None
            return (meter.get("providerCalendar") or {}).get("id") or "Inconnu"

        if key == "subscribed_power":
            meter = self._meter_data()
            if not meter:
                return None
            val = meter.get("subscribedMaxPower")
            try:
                return float(val) if val is not None else None
            except (ValueError, TypeError):
                return None

        if key == "subscription":
            return self._calculate_monthly_subscription()

        if key.startswith("rate_"):
            return self._tariff_rate()

        if key.startswith(("energy_", "cost_")):
            self._current_month = dt_util.now().strftime("%Y-%m")
            return self._calculate_monthly_total()

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        key = self._sensor_config.key
        if not self.coordinator.data:
            return {}

        if key == "contract":
            meter = self._meter_data() or {}
            return {
                "prm_id": self._prm_id,
                "distributor_status": meter.get("distributorStatus"),
                "meter_kind": meter.get("meterKind"),
                "subscribed_max_power_kva": meter.get("subscribedMaxPower"),
                "is_teleoperable": meter.get("isTeleoperable"),
                "is_smart_meter": meter.get("isSmartMeter"),
                "is_three_phase": meter.get("isThreePhase"),
                "circuit_breaker_intensity": meter.get("circuitBreakerIntensity"),
                "off_peak_label": meter.get("offPeakLabel"),
                "powered_status": meter.get("poweredStatus"),
                "provider_calendar": (meter.get("providerCalendar") or {}).get("id"),
            }

        if key == "subscription":
            agreement = self._active_agreement() or {}
            tariffs = agreement.get("tariffs") or {}
            subscription = tariffs.get("subscription") or {}
            next_pay = agreement.get("next_payment") or {}
            return {
                "current_month": self._current_month,
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

        if key.startswith(("energy_", "cost_")):
            return {
                "prm_id": self._prm_id,
                "current_month": self._current_month,
                "readings_count": len(self._readings()),
                "last_imported_date": self._last_imported_date,
            }

        if key.startswith("rate_"):
            agreement = self._active_agreement() or {}
            tariffs = (agreement.get("tariffs") or {}).get("consumption") or {}
            rate_key_map = {
                "rate_base": "base",
                "rate_peak_hours": "heures_pleines",
                "rate_off_peak_hours": "heures_creuses",
            }
            rate = tariffs.get(rate_key_map.get(key, "")) or {}
            return {
                "price_ht_eur_kwh": rate.get("price_ht"),
                "price_ttc_eur_kwh": rate.get("price_ttc"),
                "contract_number": agreement.get("contract_number"),
                "product_name": (agreement.get("product") or {}).get("display_name"),
                "valid_from": agreement.get("valid_from"),
            }

        return {}

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    def _calculate_monthly_subscription(self) -> float | None:
        tariffs = self._tariffs() or {}
        subscription = tariffs.get("subscription") or {}
        monthly = subscription.get("monthly_ttc_eur")
        if monthly is not None:
            return round(float(monthly), 2)
        return self._calculate_monthly_subscription_fallback()

    def _calculate_monthly_subscription_fallback(self) -> float | None:
        readings = self._readings()
        if not readings:
            return None
        current_month = dt_util.now().strftime("%Y-%m")
        total = 0.0
        count = 0
        for reading in readings:
            date_str = reading.get("startAt") or ""
            try:
                if datetime.fromisoformat(date_str).strftime("%Y-%m") != current_month:
                    continue
            except (ValueError, TypeError):
                continue
            for stat in (reading.get("metaData") or {}).get("statistics") or []:
                if stat.get("label") == "ABONNEMENT":
                    cost_data = stat.get("costInclTax") or {}
                    amount = cost_data.get("estimatedAmount")
                    if amount is not None:
                        total += float(amount) / 100
                        count += 1
        return round(total, 2) if count else None

    def _calculate_monthly_total(self) -> float | None:
        key = self._sensor_config.key
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

            for stat in (reading.get("metaData") or {}).get("statistics") or []:
                label = stat.get("label") or ""
                if key in _CONSUMPTION_LABEL_MAP and label == _CONSUMPTION_LABEL_MAP[key]:
                    val = stat.get("value")
                    if val is not None:
                        total += float(val)
                        found = True
                elif key in _COST_LABEL_MAP and label == _COST_LABEL_MAP[key]:
                    val = stat.get("value")
                    if val is not None:
                        total += float(val)
                        found = True

        if not found:
            return None

        if key in _COST_LABEL_MAP:
            rate = self._tariff_rate()
            if not rate:
                return None
            total = total * rate

        return round(total, 3)


class OctopusLatestReadingSensor(CoordinatorEntity, SensorEntity):
    """Last daily electricity reading (total kWh for the day)."""

    def __init__(
        self,
        coordinator: OctopusEnergyFrCoordinator,
        prm_id: str,
        sensor_config: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._prm_id = prm_id
        self._sensor_config = sensor_config
        self._attr_unique_id = f"{DOMAIN}_{prm_id}_{sensor_config.key}"
        self._attr_translation_key = sensor_config.key
        self._attr_has_entity_name = True
        self._attr_icon = sensor_config.icon
        self._attr_device_class = sensor_config.device_class
        self._attr_state_class = sensor_config.state_class
        self._attr_entity_category = sensor_config.entity_category
        self._attr_native_unit_of_measurement = sensor_config.native_unit_of_measurement
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, prm_id)})
        if sensor_config.suggested_display_precision is not None:
            self._attr_suggested_display_precision = sensor_config.suggested_display_precision

    def _readings(self) -> list[dict]:
        return (
            (self.coordinator.data or {})
            .get("electricity", {})
            .get(self._prm_id, {})
            .get("readings") or []
        )

    @property
    def native_value(self) -> float | None:
        readings = self._readings()
        if not readings:
            return None
        val = readings[-1].get("value")
        return float(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        readings = self._readings()
        if not readings:
            return {}

        reading = readings[-1]
        stats = (reading.get("metaData") or {}).get("statistics") or []
        attributes: dict[str, Any] = {
            "prm_id": self._prm_id,
            "date_releve": reading.get("startAt"),
        }

        for stat in stats:
            label = stat.get("label") or ""
            value = stat.get("value")
            cost = stat.get("costInclTax") or {}
            if label == "BASE":
                attributes["heures_base_kwh"] = float(value) if value is not None else None
            elif label == "HEURES_PLEINES":
                attributes["heures_pleines_kwh"] = float(value) if value is not None else None
            elif label == "HEURES_CREUSES":
                attributes["heures_creuses_kwh"] = float(value) if value is not None else None
            elif label == "ABONNEMENT":
                amount = cost.get("estimatedAmount")
                attributes["cout_abonnement_euro"] = float(amount) / 100 if amount is not None else None

        elec_data = (self.coordinator.data or {}).get("electricity", {}).get(self._prm_id, {})
        tariffs_consumption = (elec_data.get("tariffs") or {}).get("consumption") or {}
        for kwh_key, label, rate_key in (
            ("heures_base_kwh", "base", "base"),
            ("heures_pleines_kwh", "heures_pleines", "heures_pleines"),
            ("heures_creuses_kwh", "heures_creuses", "heures_creuses"),
        ):
            kwh = attributes.get(kwh_key)
            rate_info = tariffs_consumption.get(rate_key) or {}
            rate = rate_info.get("price_ttc")
            if kwh is not None and rate:
                attributes[f"cout_{label}_euro"] = round(float(kwh) * float(rate), 4)

        return attributes


class OctopusElectricityIndexSensor(CoordinatorEntity, SensorEntity):
    """Linky meter index (cumulative kWh counter)."""

    def __init__(
        self,
        coordinator: OctopusEnergyFrCoordinator,
        prm_id: str,
        sensor_config: OctopusIndexSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._prm_id = prm_id
        self._sensor_config = sensor_config
        self._index_type = sensor_config.index_type
        self._attr_unique_id = f"{DOMAIN}_{prm_id}_{sensor_config.key}"
        self._attr_translation_key = sensor_config.key
        self._attr_has_entity_name = True
        self._attr_icon = sensor_config.icon
        self._attr_device_class = sensor_config.device_class
        self._attr_state_class = sensor_config.state_class
        self._attr_entity_category = sensor_config.entity_category
        self._attr_native_unit_of_measurement = sensor_config.native_unit_of_measurement
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, prm_id)})
        if sensor_config.suggested_display_precision is not None:
            self._attr_suggested_display_precision = sensor_config.suggested_display_precision

    def _index_data(self) -> dict | None:
        return (
            (self.coordinator.data or {})
            .get("electricity", {})
            .get(self._prm_id, {})
            .get("index")
        )

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        index = self._index_data()
        return bool(index and self._index_type in index)

    @property
    def native_value(self) -> float | None:
        index = self._index_data()
        if not index:
            return None
        type_data = index.get(self._index_type) or {}
        val = type_data.get("index_end")
        return float(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        index = self._index_data()
        if not index:
            return {}
        type_data = index.get(self._index_type) or {}
        return {
            "prm_id": self._prm_id,
            "index_type": self._index_type,
            "index_start": type_data.get("index_start"),
            "consumption": type_data.get("consumption"),
            "period_start": index.get("period_start"),
            "period_end": index.get("period_end"),
            "index_reliability": type_data.get("index_reliability"),
            "consumption_reliability": type_data.get("consumption_reliability"),
            "status": type_data.get("status"),
        }
