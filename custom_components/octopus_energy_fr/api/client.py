"""GraphQL API client for Octopus Energy France (Kraken backend)."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
import json
import logging
import re
from typing import Any

import aiohttp
import jwt

from ..const import (
    GRAPHQL_ENDPOINT,
    MAX_RETRY_ATTEMPTS,
    RETRY_DELAY,
    TOKEN_EXPIRY_BUFFER,
)

_LOGGER = logging.getLogger(__name__)


class OctopusAuthError(Exception):
    """Raised when authentication fails or credentials are invalid."""


# ---------------------------------------------------------------------------
# GraphQL queries & mutations
# ---------------------------------------------------------------------------

MUTATION_LOGIN = """
mutation obtainKrakenToken($input: ObtainJSONWebTokenInput!) {
    obtainKrakenToken(input: $input) {
        token
    }
}
"""

FRAGMENT_INTERVAL_MEASUREMENT = """
fragment IntervalMeasurement on IntervalMeasurementType {
  __typename
  value
  startAt
  metaData {
    statistics {
      costInclTax {
        estimatedAmount
        costCurrency
      }
      label
      value
    }
  }
}
"""

QUERY_GET_ACCOUNTS = """
{
  viewer {
    accounts {
      number
      ledgers {
        balance
        ledgerType
        name
        number
        id
      }
    }
  }
}
"""

QUERY_GET_ACCOUNT_DATA = """
query getAccountData($accountNumber: String!, $activeAt: DateTime!) {
  account(accountNumber: $accountNumber) {
    number
    ledgers {
      balance
      ledgerType
      name
      number
      id
    }
    properties {
      id
      address
      supplyPoints(first: 10) {
        edges {
          node {
            id
            externalIdentifier
            marketName
            meterPoint {
              ... on ElectricityMeterPoint {
                id
                distributorStatus
                meterKind
                subscribedMaxPower
                isTeleoperable
                offPeakLabel
                poweredStatus
                isSmartMeter
                isThreePhase
                circuitBreakerIntensity
                providerCalendar {
                  id
                  name
                }
              }
              ... on GasMeterPoint {
                id
                gasNature
                annualConsumption
                isSmartMeter
                poweredStatus
                serial
                contractualStatus
                cutDate
              }
            }
          }
        }
      }
    }
    creditStorage {
      ledger {
        currentBalance
        ledgerType
        name
        number
      }
    }
    agreements(activeAt: $activeAt, first: 20) {
      edges {
        node {
          id
          validFrom
          validTo
          isActive
          supplyContractNumber
          supplyPoint {
            id
            externalIdentifier
          }
          product {
            code
            fullName
            displayName
          }
          energySupplyRate {
            standingRate {
              currency
              pricePerUnit
              unitType
              pricePerUnitWithTaxes
            }
            consumptionRates(first: 10) {
              edges {
                node {
                  currency
                  pricePerUnit
                  unitType
                  pricePerUnitWithTaxes
                }
              }
            }
          }
          billingFrequency
          nextPaymentForecast {
            amount
            date
          }
        }
      }
    }
  }
}
"""

QUERY_GET_BILLS = """
query paiement($ledgerNumber: String!) {
  paymentRequests(ledgerNumber: $ledgerNumber) {
    paymentRequest(first: 1) {
      edges {
        node {
          paymentStatus
          totalAmount
          customerAmount
          expectedPaymentDate
        }
      }
    }
  }
}
"""

QUERY_GET_INDEX_ELECTRICITY = """
query getElectricityIndex($accountNumber: String!, $prmId: String!) {
  electricityReading(
    accountNumber: $accountNumber
    prmId: $prmId
    first: 2
    calendarType: PROVIDER
  ) {
    edges {
      node {
        consumption
        periodStartAt
        periodEndAt
        indexStartValue
        indexEndValue
        statusProcessed
        calendarType
        calendarTempClass
        consumptionReliability
        indexReliability
      }
    }
  }
}
"""

QUERY_GET_MEASUREMENTS = """
query GetPropertyMeasurements(
  $propertyId: ID!
  $startAt: DateTime!
  $endAt: DateTime!
  $utilityFilters: [UtilityFiltersInput]!
  $first: Int
  $after: String
) {
  property(id: $propertyId) {
    measurements(
      startAt: $startAt
      endAt: $endAt
      first: $first
      after: $after
      utilityFilters: $utilityFilters
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      edges {
        node {
          ...IntervalMeasurement
        }
      }
    }
  }
}
"""

QUERY_GET_GAS_READINGS = """
query getGasReadings(
  $accountNumber: String!
  $pceRef: String!
  $periodStartAt: Date
  $periodEndAt: Date
  $first: Int
  $after: String
) {
  gasReading(
    accountNumber: $accountNumber
    pceRef: $pceRef
    periodStartAt: $periodStartAt
    periodEndAt: $periodEndAt
    energyQualification: M
    first: $first
    after: $after
  ) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        consumption
        periodStartAt
        periodEndAt
        indexStartValue
        indexEndValue
        statusProcessed
        energyQualification
      }
    }
  }
}
"""


# ---------------------------------------------------------------------------
# Token manager
# ---------------------------------------------------------------------------


class TokenManager:
    """JWT token holder with automatic expiry tracking."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expiry: float | None = None

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def is_valid(self) -> bool:
        if not self._token or not self._expiry:
            return False
        return datetime.now(UTC).timestamp() < (self._expiry - TOKEN_EXPIRY_BUFFER)

    def set_token(self, token: str) -> None:
        self._token = token
        with suppress(Exception):
            decoded = jwt.decode(token, options={"verify_signature": False})
            if exp := decoded.get("exp"):
                self._expiry = float(exp)
                return
        self._expiry = datetime.now(UTC).timestamp() + 3600

    def clear(self) -> None:
        self._token = None
        self._expiry = None


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------


class OctopusEnergyFrApiClient:
    """Octopus Energy France GraphQL client.

    Authenticates via email/password → JWT, then performs all data queries.
    All methods are safe to call concurrently (auth is lock-protected).
    """

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self._email = email
        self._password = password
        self._session = session
        self.token_manager = TokenManager()
        self._auth_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Low-level HTTP + GraphQL
    # ------------------------------------------------------------------

    async def _async_execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        payload = {"query": query, "variables": variables or {}}
        req_headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if headers:
            req_headers.update(headers)

        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                async with self._session.post(
                    GRAPHQL_ENDPOINT,
                    json=payload,
                    headers=req_headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    _LOGGER.warning(
                        "GraphQL HTTP %s (attempt %d/%d)",
                        resp.status,
                        attempt + 1,
                        MAX_RETRY_ATTEMPTS,
                    )
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.warning("Network error (attempt %d/%d): %s", attempt + 1, MAX_RETRY_ATTEMPTS, err)

            if attempt < MAX_RETRY_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_DELAY * (2**attempt))

        return None

    async def _execute_with_auth(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        _retry: int = 0,
    ) -> dict[str, Any]:
        if not self.token_manager.is_valid:
            if not await self.authenticate():
                raise OctopusAuthError("Authentication failed — invalid credentials")

        result = await self._async_execute(
            query, variables, {"Authorization": f"JWT {self.token_manager.token}"}
        )
        if result is None:
            raise RuntimeError("API returned an empty response after retries")

        if "errors" in result and _retry == 0:
            msgs = [e.get("message", "").lower() for e in result["errors"]]
            auth_terms = {"authentication", "unauthorized", "token", "expired", "invalid"}
            if any(term in msg for msg in msgs for term in auth_terms):
                _LOGGER.warning("Token rejected by API — re-authenticating")
                self.token_manager.clear()
                return await self._execute_with_auth(query, variables, _retry=1)

        return result

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Obtain a JWT from the Kraken API (thread-safe)."""
        async with self._auth_lock:
            if self.token_manager.is_valid:
                return True

            result = await self._async_execute(
                MUTATION_LOGIN,
                {"input": {"email": self._email, "password": self._password}},
            )
            if not result:
                _LOGGER.error("Authentication request failed — no response")
                return False

            token = result.get("data", {}).get("obtainKrakenToken", {}).get("token")
            if not token:
                errors = [e.get("message", "?") for e in result.get("errors", [])]
                _LOGGER.error("Authentication failed: %s", ", ".join(errors) or "no token returned")
                return False

            self.token_manager.set_token(token)
            _LOGGER.debug("Authentication successful")
            return True

    # ------------------------------------------------------------------
    # Account queries
    # ------------------------------------------------------------------

    async def get_accounts(self) -> list[dict[str, Any]]:
        result = await self._execute_with_auth(QUERY_GET_ACCOUNTS)
        return result.get("data", {}).get("viewer", {}).get("accounts", []) or []

    async def get_account_data(self, account_number: str) -> dict[str, Any]:
        """Return normalised account data (supply points, ledgers, agreements)."""
        variables = {
            "accountNumber": account_number,
            "activeAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        result = await self._execute_with_auth(QUERY_GET_ACCOUNT_DATA, variables)
        account = result.get("data", {}).get("account") or {}

        _LOGGER.debug(
            "[DUMP] RAW account GraphQL response for %s:\n%s",
            account_number,
            json.dumps(account, indent=2, default=str),
        )

        if not account:
            _LOGGER.warning("No account data for %s", account_number)
            return {}

        properties = account.get("properties") or []
        account_id = properties[0].get("id") if properties else None

        return {
            "account_id": account_id,
            "account_number": account.get("number", ""),
            "ledgers": self._extract_ledgers(account),
            "supply_points": self._extract_supply_points(properties),
            "agreements": self._extract_agreements(account),
        }

    # ------------------------------------------------------------------
    # Internal parsers
    # ------------------------------------------------------------------

    def _extract_ledgers(self, account: dict) -> dict[str, dict]:
        ledgers: dict[str, dict] = {}

        # Determine active PRMs to filter out terminated meter ledgers.
        active_prms: set[str] = set()
        for prop in account.get("properties") or []:
            for edge in (prop.get("supplyPoints") or {}).get("edges") or []:
                node = edge.get("node") or {}
                mp = node.get("meterPoint") or {}
                if mp.get("distributorStatus") == "RESIL":
                    continue
                prm = node.get("externalIdentifier")
                if prm:
                    active_prms.add(prm)

        for ledger in account.get("ledgers") or []:
            if not ledger:
                continue
            ltype = ledger.get("ledgerType")
            if not ltype:
                continue
            if ltype in (("FRA_ELECTRICITY_LEDGER", "FRA_GAS_LEDGER")):
                match = re.search(r"\((\d+)\)", ledger.get("name") or "")
                if match and match.group(1) not in active_prms:
                    continue
            ledgers[ltype] = {
                "balance": ledger.get("balance", 0),
                "name": ledger.get("name", ""),
                "number": ledger.get("number", ""),
                "id": ledger.get("id", ""),
            }

        credit_raw = (account.get("creditStorage") or {}).get("ledger")
        if credit_raw:
            items = credit_raw if isinstance(credit_raw, list) else [credit_raw]
            for item in items:
                if item and (ltype := item.get("ledgerType")) and ltype not in ledgers:
                    ledgers[ltype] = {
                        "balance": item.get("currentBalance", 0),
                        "name": item.get("name", ""),
                        "number": item.get("number", ""),
                        "id": "",
                    }

        return ledgers

    def _extract_supply_points(self, properties: list) -> dict[str, list]:
        supply_points: dict[str, list] = {"electricity": [], "gas": []}
        if not isinstance(properties, list):
            return supply_points

        for prop in properties:
            if not isinstance(prop, dict):
                continue
            for edge in (prop.get("supplyPoints") or {}).get("edges") or []:
                node = edge.get("node") or {}
                mp = dict(node.get("meterPoint") or {})
                mp["prm"] = node.get("externalIdentifier")
                mp["supply_point_id"] = node.get("id")
                mp["market_name"] = node.get("marketName")

                if "meterKind" in mp or "distributorStatus" in mp:
                    supply_points["electricity"].append(mp)
                elif "gasNature" in mp or "annualConsumption" in mp:
                    supply_points["gas"].append(mp)

        return supply_points

    def _extract_agreements(self, account: dict) -> list[dict]:
        agreements = []
        for edge in (account.get("agreements") or {}).get("edges") or []:
            node = edge.get("node") or {}
            rate = node.get("energySupplyRate") or {}
            tariffs = self._extract_tariffs(rate) if rate else None

            next_pay = node.get("nextPaymentForecast") or {}
            sp = node.get("supplyPoint") or {}

            agreements.append({
                "id": node.get("id"),
                "valid_from": node.get("validFrom"),
                "valid_to": node.get("validTo"),
                "is_active": node.get("isActive", False),
                "contract_number": node.get("supplyContractNumber"),
                "supply_point_id": sp.get("id"),
                "prm": sp.get("externalIdentifier"),
                "product": {
                    "code": (node.get("product") or {}).get("code"),
                    "name": (node.get("product") or {}).get("fullName"),
                    "display_name": (node.get("product") or {}).get("displayName"),
                },
                "tariffs": tariffs,
                "billing_frequency_months": node.get("billingFrequency"),
                "next_payment": {
                    "amount": next_pay.get("amount"),
                    "date": next_pay.get("date"),
                } if next_pay else None,
            })
        return agreements

    def _extract_tariffs(self, energy_rate: dict) -> dict:
        tariffs: dict[str, Any] = {
            "subscription": None,
            "consumption": {},
        }

        standing = energy_rate.get("standingRate") or {}
        if standing:
            try:
                tariffs["subscription"] = {
                    "annual_ht_eur": round(float(standing.get("pricePerUnit", 0)) / 100, 2),
                    "annual_ttc_eur": round(float(standing.get("pricePerUnitWithTaxes", 0)) / 100, 2),
                    "monthly_ttc_eur": round(float(standing.get("pricePerUnitWithTaxes", 0)) / 100 / 12, 2),
                    "currency": standing.get("currency"),
                    "unit_type": standing.get("unitType"),
                }
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Error parsing standing rate: %s", err)

        rates = []
        for edge in (energy_rate.get("consumptionRates") or {}).get("edges") or []:
            rate = edge.get("node") or {}
            try:
                rates.append({
                    "price_ht": round(float(rate.get("pricePerUnit", 0)) / 100, 4),
                    "price_ttc": round(float(rate.get("pricePerUnitWithTaxes", 0)) / 100, 4),
                    "currency": rate.get("currency"),
                    "unit_type": rate.get("unitType"),
                })
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Error parsing consumption rate: %s", err)

        rates.sort(key=lambda x: x["price_ttc"], reverse=True)

        if len(rates) >= 2:
            tariffs["consumption"]["heures_pleines"] = rates[0]
            tariffs["consumption"]["heures_creuses"] = rates[1]
        elif len(rates) == 1:
            tariffs["consumption"]["base"] = rates[0]

        return tariffs

    # ------------------------------------------------------------------
    # Energy readings
    # ------------------------------------------------------------------

    async def get_energy_readings(
        self,
        property_id: str,
        start_at: str,
        end_at: str,
        market_supply_point_id: str,
        utility_type: str = "electricity",
        reading_frequency: str = "DAY_INTERVAL",
        first: int = 500,
    ) -> list[dict]:
        """Fetch paged electricity measurements via the measurements API."""
        filter_key = f"{utility_type}Filters"
        utility_filters = [{
            filter_key: {
                "readingFrequencyType": reading_frequency,
                "marketSupplyPointId": market_supply_point_id,
            }
        }]
        query = FRAGMENT_INTERVAL_MEASUREMENT + "\n" + QUERY_GET_MEASUREMENTS

        all_nodes: list[dict] = []
        after: str | None = None
        page_num = 0

        while True:
            variables = {
                "propertyId": property_id,
                "startAt": start_at,
                "endAt": end_at,
                "utilityFilters": utility_filters,
                "first": first,
                "after": after,
            }
            result = await self._execute_with_auth(query, variables)
            measurements = (
                result.get("data", {}).get("property", {}).get("measurements") or {}
            )
            edges = measurements.get("edges") or []

            if page_num == 0 and edges:
                _LOGGER.debug(
                    "[DUMP] RAW electricity measurement sample (PRM=%s, first node of page 1):\n%s",
                    market_supply_point_id,
                    json.dumps(edges[0].get("node"), indent=2, default=str),
                )

            for edge in edges:
                node = edge.get("node")
                if node:
                    all_nodes.append(node)

            page_info = measurements.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")
            page_num += 1

        _LOGGER.debug(
            "[DUMP] Electricity readings fetch complete: PRM=%s, total=%d nodes",
            market_supply_point_id,
            len(all_nodes),
        )
        return all_nodes

    async def get_gas_readings(
        self,
        account_number: str,
        pce_ref: str,
        start_at: str,
        end_at: str,
        first: int = 200,
    ) -> list[dict]:
        """Fetch paged gas readings via the dedicated gasReading API."""
        all_nodes: list[dict] = []
        after: str | None = None
        first_page = True

        while True:
            variables = {
                "accountNumber": account_number,
                "pceRef": pce_ref,
                "periodStartAt": start_at[:10],
                "periodEndAt": end_at[:10],
                "first": first,
                "after": after,
            }
            result = await self._execute_with_auth(QUERY_GET_GAS_READINGS, variables)
            gas_reading = result.get("data", {}).get("gasReading") or {}
            edges = gas_reading.get("edges") or []

            if first_page and edges:
                _LOGGER.debug(
                    "[DUMP] RAW gas reading sample (PCE=%s, first node of page 1):\n%s",
                    pce_ref,
                    json.dumps(edges[0].get("node"), indent=2, default=str),
                )
                first_page = False

            for edge in edges:
                node = edge.get("node") or {}
                all_nodes.append({
                    "value": node.get("consumption"),
                    "startAt": node.get("periodStartAt"),
                    "endAt": node.get("periodEndAt"),
                    "indexStartValue": node.get("indexStartValue"),
                    "indexEndValue": node.get("indexEndValue"),
                    "statusProcessed": node.get("statusProcessed"),
                    "energyQualification": node.get("energyQualification"),
                })

            page_info = gas_reading.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")

        _LOGGER.debug(
            "[DUMP] Gas readings fetch complete: PCE=%s, total=%d nodes",
            pce_ref,
            len(all_nodes),
        )
        return all_nodes

    async def get_electricity_index(
        self,
        account_number: str,
        prm_id: str,
    ) -> dict[str, Any] | None:
        """Fetch latest Linky index (cumulative counter values)."""
        result = await self._execute_with_auth(
            QUERY_GET_INDEX_ELECTRICITY,
            {"accountNumber": account_number, "prmId": prm_id},
        )
        edges = (result.get("data", {}).get("electricityReading") or {}).get("edges") or []
        _LOGGER.debug(
            "[DUMP] RAW electricity index (PRM=%s):\n%s",
            prm_id,
            json.dumps(edges, indent=2, default=str),
        )
        if not edges:
            return None

        index_data: dict[str, Any] = {}
        period_start: str | None = None
        period_end: str | None = None
        tariff_type: str | None = None

        for edge in edges:
            node = edge.get("node") or {}
            temp_class = node.get("calendarTempClass")
            if temp_class not in ("HP", "HC", "BASE"):
                continue

            key = temp_class.lower()
            index_data[key] = {
                "consumption": node.get("consumption"),
                "index_start": node.get("indexStartValue"),
                "index_end": node.get("indexEndValue"),
                "status": node.get("statusProcessed"),
                "consumption_reliability": node.get("consumptionReliability"),
                "index_reliability": node.get("indexReliability"),
            }
            if temp_class == "BASE":
                tariff_type = "BASE"
            elif temp_class in ("HP", "HC") and tariff_type != "BASE":
                tariff_type = "HPHC"
            if period_start is None:
                period_start = node.get("periodStartAt")
                period_end = node.get("periodEndAt")

        if not index_data:
            return None

        return {"tariff_type": tariff_type, "period_start": period_start, "period_end": period_end, **index_data}

    # ------------------------------------------------------------------
    # Financial queries
    # ------------------------------------------------------------------

    async def get_payment_request(self, ledger_number: str) -> dict | None:
        variables = {"ledgerNumber": ledger_number}
        result = await self._execute_with_auth(QUERY_GET_BILLS, variables)
        edges = (
            (result.get("data", {}).get("paymentRequests") or {})
            .get("paymentRequest", {})
            .get("edges") or []
        )
        return edges[0].get("node") if edges else None

    async def get_all_payment_requests(
        self, ledgers: dict[str, dict]
    ) -> dict[str, dict]:
        results: dict[str, dict] = {}
        for ltype, info in ledgers.items():
            number = info.get("number")
            if not number:
                continue
            try:
                pr = await self.get_payment_request(number)
                if pr:
                    results[ltype] = pr
            except Exception as err:
                _LOGGER.warning("Payment request failed for ledger %s: %s", ltype, err)
        return results
