"""Data update coordinator for Octopus Energy France."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import OctopusAuthError, OctopusEnergyFrApiClient
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ELECTRICITY_HISTORY_DAYS,
    GAS_HISTORY_DAYS,
    PREVIOUS_MONTH_OVERLAP_DAYS,
)

_LOGGER = logging.getLogger(__name__)


class OctopusEnergyFrCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls Octopus Energy France for all account data.

    Data schema returned by _async_update_data:
    {
        "account_id": str,
        "account_number": str,
        "ledgers": {ledger_type: {balance, name, number, id}},
        "supply_points": {
            "electricity": [meter_dict, ...],
            "gas": [meter_dict, ...],
        },
        "agreements": [agreement_dict, ...],
        "electricity": {
            prm_id: {
                "readings": [reading, ...],   # daily DAY_INTERVAL
                "index": dict | None,
                "tariffs": dict | None,
            }
        },
        "gas": {
            pce_ref: {
                "readings": [reading, ...],   # monthly
                "tariffs": dict | None,
            }
        },
        "payment_requests": {ledger_type: payment_request_dict},
    }
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: OctopusEnergyFrApiClient,
        account_number: str,
        config_entry: ConfigEntry,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
            config_entry=config_entry,
        )
        self.api_client = api_client
        self.account_number = account_number

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch_all_data()
        except OctopusAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error fetching Octopus data: {err}") from err

    async def _fetch_all_data(self) -> dict[str, Any]:
        account_data = await self.api_client.get_account_data(self.account_number)

        account_id = account_data.get("account_id")
        account_number = account_data.get("account_number") or self.account_number
        if not account_id:
            raise UpdateFailed("API returned account data without account_id")

        # Time windows
        now = dt_util.now()
        today_midnight = dt_util.start_of_local_day(now)
        first_of_month = today_midnight.replace(day=1)
        elec_start = (first_of_month - timedelta(days=PREVIOUS_MONTH_OVERLAP_DAYS + ELECTRICITY_HISTORY_DAYS)).isoformat()
        gas_start = (today_midnight - timedelta(days=GAS_HISTORY_DAYS)).isoformat()
        date_end = now.isoformat()

        agreements = account_data.get("agreements") or []
        supply_points = account_data.get("supply_points") or {}

        # Active electricity meters only
        elec_meters = [
            m for m in supply_points.get("electricity") or []
            if m.get("distributorStatus") != "RESIL"
        ]
        gas_meters = supply_points.get("gas") or []

        # Concurrent fetch tasks
        elec_tasks = [
            self._fetch_electricity_meter(account_id, account_number, m, elec_start, date_end, agreements)
            for m in elec_meters if m.get("prm")
        ]
        gas_tasks = [
            self._fetch_gas_meter(account_number, m, gas_start, date_end, agreements)
            for m in gas_meters if m.get("prm")
        ]
        payments_task = self._fetch_payments(account_data.get("ledgers") or {})

        gathered = await asyncio.gather(
            *elec_tasks, *gas_tasks, payments_task, return_exceptions=True
        )

        electricity: dict[str, Any] = {}
        gas: dict[str, Any] = {}
        payment_requests: dict[str, Any] = {}

        result_idx = 0

        for m in elec_meters:
            prm = m.get("prm")
            if not prm:
                continue
            res = gathered[result_idx]
            result_idx += 1
            if isinstance(res, Exception):
                _LOGGER.warning("Electricity fetch failed for PRM %s: %s", prm, res)
                electricity[prm] = {"readings": [], "index": None, "tariffs": _find_tariffs(agreements, prm)}
            else:
                electricity[prm] = res

        for m in gas_meters:
            pce = m.get("prm")
            if not pce:
                continue
            res = gathered[result_idx]
            result_idx += 1
            if isinstance(res, Exception):
                _LOGGER.warning("Gas fetch failed for PCE %s: %s", pce, res)
                gas[pce] = {"readings": [], "tariffs": _find_tariffs(agreements, pce)}
            else:
                gas[pce] = res

        payments_res = gathered[result_idx]
        if isinstance(payments_res, Exception):
            _LOGGER.warning("Payment requests fetch failed: %s", payments_res)
        else:
            payment_requests = payments_res

        # Keep supply_points with only active electricity meters
        account_data["supply_points"]["electricity"] = elec_meters

        assembled = {
            **account_data,
            "electricity": electricity,
            "gas": gas,
            "payment_requests": payment_requests,
        }

        _LOGGER.debug(
            "[DUMP] Full coordinator data structure for account %s:\n%s",
            self.account_number,
            json.dumps(
                {
                    "account_id": assembled.get("account_id"),
                    "account_number": assembled.get("account_number"),
                    "ledgers": assembled.get("ledgers"),
                    "supply_points": assembled.get("supply_points"),
                    "agreements": assembled.get("agreements"),
                    "electricity_prms": {
                        prm: {
                            "readings_count": len(data.get("readings") or []),
                            "latest_reading": (data.get("readings") or [{}])[-1] if data.get("readings") else None,
                            "index": data.get("index"),
                            "tariffs": data.get("tariffs"),
                        }
                        for prm, data in assembled.get("electricity", {}).items()
                    },
                    "gas_pces": {
                        pce: {
                            "readings_count": len(data.get("readings") or []),
                            "latest_reading": (data.get("readings") or [{}])[-1] if data.get("readings") else None,
                            "tariffs": data.get("tariffs"),
                        }
                        for pce, data in assembled.get("gas", {}).items()
                    },
                    "payment_requests": assembled.get("payment_requests"),
                },
                indent=2,
                default=str,
            ),
        )

        return assembled

    async def _fetch_electricity_meter(
        self,
        account_id: str,
        account_number: str,
        meter: dict,
        start_at: str,
        end_at: str,
        agreements: list,
    ) -> dict[str, Any]:
        prm = meter["prm"]
        try:
            readings, index = await asyncio.gather(
                self.api_client.get_energy_readings(
                    property_id=account_id,
                    start_at=start_at,
                    end_at=end_at,
                    market_supply_point_id=prm,
                    utility_type="electricity",
                    reading_frequency="DAY_INTERVAL",
                ),
                self.api_client.get_electricity_index(account_number, prm),
            )
        except Exception as err:
            raise RuntimeError(f"Electricity fetch error for {prm}: {err}") from err

        return {
            "readings": readings,
            "index": index,
            "tariffs": _find_tariffs(agreements, prm),
        }

    async def _fetch_gas_meter(
        self,
        account_number: str,
        meter: dict,
        start_at: str,
        end_at: str,
        agreements: list,
    ) -> dict[str, Any]:
        pce = meter["prm"]
        try:
            readings = await self.api_client.get_gas_readings(
                account_number=account_number,
                pce_ref=pce,
                start_at=start_at,
                end_at=end_at,
            )
        except Exception as err:
            raise RuntimeError(f"Gas fetch error for {pce}: {err}") from err

        return {
            "readings": readings,
            "tariffs": _find_tariffs(agreements, pce),
        }

    async def _fetch_payments(self, ledgers: dict) -> dict:
        try:
            return await self.api_client.get_all_payment_requests(ledgers)
        except Exception as err:
            _LOGGER.warning("Failed to fetch payment requests: %s", err)
            return {}


def _find_tariffs(agreements: list, prm: str) -> dict | None:
    """Return tariffs for the active agreement matching a PRM (elec or gas)."""
    for agreement in agreements:
        if agreement.get("prm") == prm and agreement.get("is_active"):
            return agreement.get("tariffs")
    return None
