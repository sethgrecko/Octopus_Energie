"""Constants for Octopus Energy France integration."""

DOMAIN = "octopus_energy_fr"

CONF_ACCOUNT_NUMBER = "account_number"
CONF_SCAN_INTERVAL = "scan_interval"

LEDGER_TYPE_ELECTRICITY = "FRA_ELECTRICITY_LEDGER"
LEDGER_TYPE_GAS = "FRA_GAS_LEDGER"
LEDGER_TYPE_POT = "POT_LEDGER"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 1440

GRAPHQL_ENDPOINT = "https://api.oefr-kraken.energy/v1/graphql/"

# Linky readings can be delayed up to a week; overlap ensures we capture them.
PREVIOUS_MONTH_OVERLAP_DAYS = 7

# How far back to pull electricity readings for statistics bootstrap.
ELECTRICITY_HISTORY_DAYS = 365
GAS_HISTORY_DAYS = 730

TOKEN_EXPIRY_BUFFER = 60
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY = 1

SERVICE_FORCE_UPDATE = "force_update"
