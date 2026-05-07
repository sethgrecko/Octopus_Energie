"""Octopus Energy France — Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform, UnitOfApparentPower
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import OctopusAuthError, OctopusEnergyFrApiClient
from .const import (
    CONF_ACCOUNT_NUMBER,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_FORCE_UPDATE,
)
from .coordinator import OctopusEnergyFrCoordinator
from .coordinator_intelligent import OctopusIntelligentCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class OctopusEnergyFrRuntimeData:
    """Runtime state stored in the config entry."""

    coordinator: OctopusEnergyFrCoordinator
    account_number: str
    intelligent_coordinator: OctopusIntelligentCoordinator | None = field(default=None)


OctopusEnergyFrConfigEntry = ConfigEntry[OctopusEnergyFrRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-level services."""

    async def _handle_force_update(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                await entry.runtime_data.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_UPDATE,
        _handle_force_update,
        schema=vol.Schema({}),
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: OctopusEnergyFrConfigEntry
) -> bool:
    """Set up Octopus Energy France from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    account_number = entry.data.get(CONF_ACCOUNT_NUMBER, "")
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    session = async_get_clientsession(hass)
    api_client = OctopusEnergyFrApiClient(email=email, password=password, session=session)

    # Authenticate — fail fast so HA can surface a reauth notification.
    try:
        authenticated = await api_client.authenticate()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot reach Octopus API: {err}") from err

    if not authenticated:
        raise ConfigEntryAuthFailed("Invalid credentials — please reconfigure the integration")

    # Resolve account number in case it changed or wasn't stored.
    account_number = await _resolve_account_number(api_client, account_number)

    # Main data coordinator.
    coordinator = OctopusEnergyFrCoordinator(
        hass=hass,
        api_client=api_client,
        account_number=account_number,
        config_entry=entry,
        scan_interval=scan_interval,
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except Exception as err:
        raise ConfigEntryNotReady(f"Initial data fetch failed: {err}") from err

    # Intelligent coordinator (optional — only for EV accounts).
    intelligent_coordinator = await _setup_intelligent_coordinator(
        hass, api_client, account_number
    )

    entry.runtime_data = OctopusEnergyFrRuntimeData(
        coordinator=coordinator,
        account_number=account_number,
        intelligent_coordinator=intelligent_coordinator,
    )

    # Register devices in the device registry.
    await _create_devices(hass, entry, coordinator, intelligent_coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OctopusEnergyFrConfigEntry
) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_account_number(
    api_client: OctopusEnergyFrApiClient, configured: str
) -> str:
    try:
        accounts = await api_client.get_accounts()
        numbers = [a["number"] for a in accounts if a.get("number")]
        if configured in numbers:
            return configured
        if numbers:
            return numbers[0]
    except Exception as err:
        _LOGGER.warning("Could not retrieve accounts list: %s", err)
    return configured


async def _setup_intelligent_coordinator(
    hass: HomeAssistant,
    api_client: OctopusEnergyFrApiClient,
    account_number: str,
) -> OctopusIntelligentCoordinator | None:
    try:
        coord = OctopusIntelligentCoordinator(
            hass=hass,
            api_client=api_client,
            account_number=account_number,
        )
        await coord.async_config_entry_first_refresh()
        if not (coord.data or {}).get("devices"):
            _LOGGER.debug("No Intelligent devices found for account %s", account_number)
            return None
        return coord
    except Exception as err:
        _LOGGER.debug("Octopus Intelligent not available: %s", err)
        return None


async def _create_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: OctopusEnergyFrCoordinator,
    intelligent_coordinator: OctopusIntelligentCoordinator | None,
) -> None:
    registry = dr.async_get(hass)
    account_number = entry.runtime_data.account_number
    data = coordinator.data or {}
    supply_points = data.get("supply_points") or {}

    # Account device (logical parent for all meters).
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, account_number)},
        name=f"Compte Octopus Energy — {account_number}",
        manufacturer="Octopus Energy France",
        model="Compte client",
    )

    for meter in supply_points.get("electricity") or []:
        prm = meter.get("prm")
        if not prm:
            continue
        kind = meter.get("meterKind", "Linky")
        power = meter.get("subscribedMaxPower", "?")
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, prm)},
            via_device=(DOMAIN, account_number),
            name=f"{kind} {prm}",
            manufacturer="Enedis",
            model=f"{kind} — {power} {UnitOfApparentPower.KILO_VOLT_AMPERE}",
        )

    for meter in supply_points.get("gas") or []:
        pce = meter.get("prm")
        if not pce:
            continue
        is_smart = meter.get("isSmartMeter", False)
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, pce)},
            via_device=(DOMAIN, account_number),
            name=f"Gazpar {pce}",
            manufacturer="GrDF",
            model="Gazpar" if is_smart else "Compteur gaz",
        )

    if intelligent_coordinator:
        for device in (intelligent_coordinator.data or {}).get("devices") or []:
            dev_id = device.get("id")
            if not dev_id:
                continue
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, dev_id)},
                via_device=(DOMAIN, account_number),
                name=device.get("name") or dev_id,
            )
