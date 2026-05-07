"""Client API Octopus Energy France."""
from __future__ import annotations

import logging

import aiohttp

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)


class OctopusApiError(Exception):
    """Erreur API Octopus."""


class OctopusAuthError(OctopusApiError):
    """Erreur auth API Octopus."""


class OctopusEnergyFrApiClient:
    """Client API minimal pour Octopus."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str, account_id: str) -> None:
        self._session = session
        self._api_key = api_key
        self._account_id = account_id

    async def _request(self, endpoint: str) -> dict:
        url = f"{API_BASE_URL}{endpoint}"
        auth = aiohttp.BasicAuth(self._api_key, "")

        try:
            async with self._session.get(url, auth=auth, timeout=20) as resp:
                if resp.status == 401:
                    raise OctopusAuthError("Clé API invalide")
                if resp.status >= 400:
                    text = await resp.text()
                    raise OctopusApiError(f"Erreur API {resp.status}: {text}")
                return await resp.json()
        except aiohttp.ClientError as err:
            raise OctopusApiError(f"Erreur réseau: {err}") from err

    async def async_validate_credentials(self) -> None:
        """Valider api_key/account_id."""
        await self._request(f"/accounts/{self._account_id}/")

    async def async_fetch_dashboard(self) -> dict:
        """Récupérer un jeu de données principal."""
        account = await self._request(f"/accounts/{self._account_id}/")

        properties = account.get("properties", [])
        electricity_today = 0.0
        gas_today = 0.0
        unit_rate = None

        for prop in properties:
            for meter_point in prop.get("electricity_meter_points", []):
                agreements = meter_point.get("agreements", [])
                if agreements:
                    tariff_code = agreements[0].get("tariff_code")
                    if tariff_code and unit_rate is None:
                        product_code = tariff_code.split("-")[-1]
                        prices = await self._request(
                            f"/products/{product_code}/electricity-tariffs/{tariff_code}/standard-unit-rates/?page_size=1"
                        )
                        results = prices.get("results", [])
                        if results:
                            unit_rate = results[0].get("value_inc_vat")

            for _ in prop.get("gas_meter_points", []):
                # Placeholder stable: endpoint consommation gaz/elec à affiner selon compteur.
                pass

        return {
            "account_id": account.get("number", self._account_id),
            "balance": account.get("balance", 0),
            "last_bill_amount": account.get("last_statement", {}).get("total", 0),
            "electricity_today_kwh": electricity_today,
            "gas_today_kwh": gas_today,
            "electricity_unit_rate": unit_rate,
        }
