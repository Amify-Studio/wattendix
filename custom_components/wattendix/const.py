"""Constants for Wattendix."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "wattendix"
VERSION: Final = "0.1.0"

CONF_SOURCE: Final = "source"
CONF_MAX_POWER: Final = "max_power"
CONF_SOURCE_MODE: Final = "source_mode"
CONF_SOURCE_PRICES: Final = "source_prices"

CONF_PRICE_MODE: Final = "price_mode"
CONF_PRICE: Final = "price"
CONF_PRICE_PEAK: Final = "price_peak"
CONF_PRICE_OFFPEAK: Final = "price_offpeak"
CONF_OFFPEAK_RANGES: Final = "offpeak_ranges"
CONF_PRICE_ENTITY: Final = "price_entity"

CONF_SUBSCRIPTION_MODE: Final = "subscription_mode"
CONF_SUBSCRIPTION: Final = "subscription"
CONF_SUBSCRIPTION_ENTITY: Final = "subscription_entity"

CONF_WEATHER: Final = "weather"
CONF_OUTDOOR_SENSOR: Final = "outdoor_sensor"

CONF_HEAT_PUMP: Final = "heat_pump"
CONF_HDD_BASE: Final = "hdd_base"
CONF_SEASON_MONTH: Final = "season_month"

MODE_NONE: Final = "none"
MODE_FIXED: Final = "fixed"
MODE_PEAK: Final = "peak_offpeak"
MODE_ENTITY: Final = "entity"
MODE_PER_SOURCE: Final = "per_source"

# How the consumption reaches Home Assistant.
SOURCE_LIVE: Final = "live"  # a counter or a power sensor updating through the day
SOURCE_STATISTICS: Final = "statistics"  # long-term statistics imported later (cloud meter data)
SOURCE_DAILY_VALUE: Final = "daily_value"  # a sensor whose state is yesterday's consumption

MAX_PRICED_SOURCES: Final = 6
DELAYED_LOOKBACK_DAYS: Final = 800

DEFAULT_MAX_POWER: Final = 36.0  # kW
DEFAULT_HDD_BASE: Final = 18.0  # °C
DEFAULT_SEASON_MONTH: Final = 10

LEARN_DAYS: Final = 400
HEATING_FIT_EXCLUDE_DAYS: Final = 30  # recent days are compared to the fit, not part of it
HEATING_FIT_MIN_DAYS: Final = 30
