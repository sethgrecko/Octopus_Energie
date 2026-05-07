"""Octopus Intelligent (EV smart-charging) API client."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..api import OctopusEnergyFrApiClient

_LOGGER = logging.getLogger(__name__)

MUTATION_BOOST_CHARGE = """
mutation updateBoostCharge($input: UpdateBoostChargeInput!) {
  updateBoostCharge(input: $input) {
    krakenflexDevice {
      id
    }
  }
}
"""

QUERY_DEVICES = """
query devices($accountNumber: String!) {
  devices(accountNumber: $accountNumber) {
    id
    name
    status {
      current
      currentState
    }
  }
}
"""

QUERY_VEHICLE_CHARGING_PREFERENCES = """
query vehicleChargingPreferences($accountNumber: String!) {
  vehicleChargingPreferences(accountNumber: $accountNumber) {
    weekdayTargetSoc
    weekdayTargetTime
    weekendTargetSoc
    weekendTargetTime
  }
}
"""

QUERY_FLEX_PLANNED_DISPATCHES = """
query flexPlannedDispatches($deviceId: String!) {
  flexPlannedDispatches(deviceId: $deviceId) {
    start
    end
  }
}
"""

MUTATION_SET_DEVICE_PREFERENCES = """
mutation setVehicleChargePreferences($input: SetVehicleChargePreferencesInput!) {
  setVehicleChargePreferences(input: $input) {
    krakenflexDevice {
      id
    }
  }
}
"""


class OctopusIntelligentApiClient:
    """Client for Octopus Intelligent EV charging features."""

    def __init__(self, api_client: OctopusEnergyFrApiClient) -> None:
        self._api = api_client

    async def get_devices(self, account_number: str) -> list[dict[str, Any]]:
        try:
            result = await self._api._execute_with_auth(
                QUERY_DEVICES, {"accountNumber": account_number}
            )
            return result.get("data", {}).get("devices") or []
        except Exception as err:
            _LOGGER.warning("Failed to fetch intelligent devices: %s", err)
            return []

    async def get_vehicle_charging_preferences(
        self, account_number: str
    ) -> dict[str, Any]:
        try:
            result = await self._api._execute_with_auth(
                QUERY_VEHICLE_CHARGING_PREFERENCES, {"accountNumber": account_number}
            )
            return result.get("data", {}).get("vehicleChargingPreferences") or {}
        except Exception as err:
            _LOGGER.warning("Failed to fetch charging preferences: %s", err)
            return {}

    async def get_flex_planned_dispatches(self, device_id: str) -> list[dict[str, Any]]:
        try:
            result = await self._api._execute_with_auth(
                QUERY_FLEX_PLANNED_DISPATCHES, {"deviceId": device_id}
            )
            return result.get("data", {}).get("flexPlannedDispatches") or []
        except Exception as err:
            _LOGGER.warning("Failed to fetch planned dispatches for %s: %s", device_id, err)
            return []

    async def trigger_boost_charge(self, device_id: str) -> bool:
        try:
            await self._api._execute_with_auth(
                MUTATION_BOOST_CHARGE,
                {"input": {"deviceId": device_id, "action": "start"}},
            )
            return True
        except Exception as err:
            _LOGGER.error("Failed to trigger boost charge for %s: %s", device_id, err)
            return False

    async def cancel_boost_charge(self, device_id: str) -> bool:
        try:
            await self._api._execute_with_auth(
                MUTATION_BOOST_CHARGE,
                {"input": {"deviceId": device_id, "action": "stop"}},
            )
            return True
        except Exception as err:
            _LOGGER.error("Failed to cancel boost charge for %s: %s", device_id, err)
            return False

    async def set_target_soc(
        self,
        account_number: str,
        device_id: str,
        weekday_soc: int | None = None,
        weekend_soc: int | None = None,
    ) -> bool:
        try:
            prefs: dict[str, Any] = {"deviceId": device_id}
            if weekday_soc is not None:
                prefs["weekdayTargetSoc"] = weekday_soc
            if weekend_soc is not None:
                prefs["weekendTargetSoc"] = weekend_soc
            await self._api._execute_with_auth(
                MUTATION_SET_DEVICE_PREFERENCES,
                {"input": {"accountNumber": account_number, "preferences": [prefs]}},
            )
            return True
        except Exception as err:
            _LOGGER.error("Failed to set target SOC: %s", err)
            return False

    async def set_target_time(
        self,
        account_number: str,
        device_id: str,
        weekday_time: str | None = None,
        weekend_time: str | None = None,
    ) -> bool:
        try:
            prefs: dict[str, Any] = {"deviceId": device_id}
            if weekday_time is not None:
                prefs["weekdayTargetTime"] = weekday_time
            if weekend_time is not None:
                prefs["weekendTargetTime"] = weekend_time
            await self._api._execute_with_auth(
                MUTATION_SET_DEVICE_PREFERENCES,
                {"input": {"accountNumber": account_number, "preferences": [prefs]}},
            )
            return True
        except Exception as err:
            _LOGGER.error("Failed to set target time: %s", err)
            return False
