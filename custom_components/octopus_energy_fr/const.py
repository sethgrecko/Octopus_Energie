"""Constantes Octopus Energy France."""

DOMAIN = "octopus_energy_fr"
PLATFORMS = ["sensor"]

CONF_API_KEY = "api_key"
CONF_ACCOUNT_ID = "account_id"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 1440

API_BASE_URL = "https://api.octopus.energy/v1"
