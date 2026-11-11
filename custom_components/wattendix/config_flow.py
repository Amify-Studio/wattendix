"""Config flow: how consumption arrives, the sensors, then optional levels.

Levels: price, standing charge, weather, heating. The same steps serve the
initial setup and the options.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_HDD_BASE,
    CONF_HEAT_PUMP,
    CONF_MAX_POWER,
    CONF_OFFPEAK_RANGES,
    CONF_OUTDOOR_SENSOR,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    CONF_PRICE_MODE,
    CONF_PRICE_OFFPEAK,
    CONF_PRICE_PEAK,
    CONF_SEASON_MONTH,
    CONF_SOURCE,
    CONF_SOURCE_MODE,
    CONF_SOURCE_PRICES,
    CONF_SUBSCRIPTION,
    CONF_SUBSCRIPTION_ENTITY,
    CONF_SUBSCRIPTION_MODE,
    CONF_WEATHER,
    DEFAULT_HDD_BASE,
    DEFAULT_MAX_POWER,
    DEFAULT_SEASON_MONTH,
    DOMAIN,
    MAX_PRICED_SOURCES,
    MODE_ENTITY,
    MODE_FIXED,
    MODE_NONE,
    MODE_PEAK,
    MODE_PER_SOURCE,
    SOURCE_DAILY_VALUE,
    SOURCE_LIVE,
    SOURCE_STATISTICS,
)
from .controller import as_list
from .core.meter import ENERGY_FACTORS, kind_of
from .core.tariff import parse_ranges

# Any sensor can be picked (many energy sensors carry no device class): the unit is validated.
SENSORS_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", multiple=True)
)
STATISTICS_SELECTOR = selector.StatisticSelector(selector.StatisticSelectorConfig(multiple=True))
NUMERIC_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["sensor", "input_number", "number"])
)
SOURCE_PRICE = "source_price_"

# Keys owned by each step: a step replaces all of its keys, so a cleared field is forgotten.
STEP_KEYS = {
    "price": (
        CONF_PRICE,
        CONF_PRICE_PEAK,
        CONF_PRICE_OFFPEAK,
        CONF_OFFPEAK_RANGES,
        CONF_PRICE_ENTITY,
        CONF_SOURCE_PRICES,
    ),
    "subscription": (CONF_SUBSCRIPTION, CONF_SUBSCRIPTION_ENTITY),
    "weather": (CONF_WEATHER, CONF_OUTDOOR_SENSOR),
    "heating": (CONF_HEAT_PUMP, CONF_HDD_BASE, CONF_SEASON_MONTH),
}


def _number(low: float, high: float, step: float | str, unit: str | None = None) -> selector.NumberSelector:
    config: dict[str, Any] = {"min": low, "max": high, "step": step, "mode": selector.NumberSelectorMode.BOX}
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _choice(options: list[str], key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, translation_key=key, mode=selector.SelectSelectorMode.LIST
        )
    )


class WattendixSteps:
    """Steps shared by the config flow and the options flow."""

    _values: dict[str, Any]
    _with_name = False

    # Provided by the flow classes.
    hass: Any
    async_show_form: Any
    add_suggested_values_to_schema: Any

    def _finish(self) -> ConfigFlowResult:
        raise NotImplementedError

    def _form(
        self,
        step: str,
        schema: vol.Schema,
        errors: dict[str, str] | None = None,
        values: dict[str, Any] | None = None,
        placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id=step,
            data_schema=self.add_suggested_values_to_schema(schema, values or self._values),
            errors=errors or {},
            description_placeholders=placeholders,
        )

    def _store(self, step: str, user_input: dict[str, Any]) -> None:
        for key in STEP_KEYS[step]:
            self._values.pop(key, None)
        self._values.update(user_input)

    def _currency(self) -> str:
        return self.hass.config.currency

    def _mode(self) -> str:
        return self._values.get(CONF_SOURCE_MODE, SOURCE_LIVE)

    # ---------------------------------------------------------------- meter
    async def async_step_meter(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """How consumption reaches Home Assistant, and which levels to set up."""
        errors: dict[str, str] = {}
        if user_input is not None:
            delayed = user_input[CONF_SOURCE_MODE] != SOURCE_LIVE
            if delayed and user_input[CONF_PRICE_MODE] == MODE_PEAK:
                # Daily totals cannot be split by time of day.
                errors[CONF_PRICE_MODE] = "delayed_price"
            if not errors:
                self._values.update(user_input)
                return await self.async_step_source()
        fields: dict[Any, Any] = {}
        if self._with_name:
            fields[vol.Required(CONF_NAME, default="Wattendix")] = selector.TextSelector()
        fields.update(
            {
                vol.Required(CONF_SOURCE_MODE, default=SOURCE_LIVE): _choice(
                    [SOURCE_LIVE, SOURCE_STATISTICS, SOURCE_DAILY_VALUE], "source_mode"
                ),
                vol.Required(CONF_PRICE_MODE, default=MODE_NONE): _choice(
                    [MODE_NONE, MODE_FIXED, MODE_PEAK, MODE_PER_SOURCE, MODE_ENTITY], "price_mode"
                ),
                vol.Required(CONF_SUBSCRIPTION_MODE, default=MODE_NONE): _choice(
                    [MODE_NONE, MODE_FIXED, MODE_ENTITY], "subscription_mode"
                ),
            }
        )
        return self._form(
            "meter", vol.Schema(fields), errors, {**self._values, **(user_input or {})}
        )

    # --------------------------------------------------------------- source
    async def _statistic_units(self, ids: list[str]) -> dict[str, str | None]:
        from homeassistant.components.recorder import get_instance  # noqa: PLC0415
        from homeassistant.components.recorder.statistics import list_statistic_ids  # noqa: PLC0415

        if "recorder" not in self.hass.config.components:
            return {}
        found = await get_instance(self.hass).async_add_executor_job(
            list_statistic_ids, self.hass, set(ids)
        )
        return {
            item["statistic_id"]: item.get("statistics_unit_of_measurement")
            for item in found
            if item.get("has_sum")
        }

    async def _check_sources(self, sources: list[str]) -> str | None:
        """Error key if a source cannot be used in the chosen mode."""
        mode = self._mode()
        if not sources:
            return "no_source"
        if self._values.get(CONF_PRICE_MODE) == MODE_PER_SOURCE and len(sources) > MAX_PRICED_SOURCES:
            return "too_many_sources"
        if mode == SOURCE_STATISTICS:
            units = await self._statistic_units(sources)
            for source in sources:
                if (units.get(source) or "").lower() not in ENERGY_FACTORS:
                    return "bad_statistic"
            return None
        for source in sources:
            state = self.hass.states.get(source)
            if state is None:
                continue  # not available right now: accepted, checked when it comes back
            kind = kind_of(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT))
            if kind is None or (mode == SOURCE_DAILY_VALUE and kind != "energy"):
                return "bad_unit" if mode == SOURCE_LIVE else "bad_daily_unit"
        return None

    async def async_step_source(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The sensors (or statistics) measuring the home; several are added together."""
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._check_sources(as_list(user_input.get(CONF_SOURCE)))
            if error:
                errors[CONF_SOURCE] = error
            else:
                self._values.update(user_input)
                return await self.async_step_price()
        statistics = self._mode() == SOURCE_STATISTICS
        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCE): STATISTICS_SELECTOR if statistics else SENSORS_SELECTOR,
                vol.Required(CONF_MAX_POWER, default=DEFAULT_MAX_POWER): _number(1, 500, "any", "kW"),
            }
        )
        values = {**self._values, **(user_input or {})}
        values[CONF_SOURCE] = as_list(values.get(CONF_SOURCE))
        return self._form("source", schema, errors, values)

    # ---------------------------------------------------------------- price
    async def async_step_price(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        mode = self._values.get(CONF_PRICE_MODE, MODE_NONE)
        if mode == MODE_NONE:
            for step in ("price", "subscription"):
                self._store(step, {})
            return await self.async_step_weather()
        sources = as_list(self._values.get(CONF_SOURCE))
        errors: dict[str, str] = {}
        if user_input is not None:
            if mode == MODE_PEAK:
                try:
                    if not parse_ranges(user_input.get(CONF_OFFPEAK_RANGES, "")):
                        errors[CONF_OFFPEAK_RANGES] = "bad_ranges"
                except ValueError:
                    errors[CONF_OFFPEAK_RANGES] = "bad_ranges"
            if not errors:
                if mode == MODE_PER_SOURCE:
                    user_input = {
                        CONF_SOURCE_PRICES: [
                            user_input[f"{SOURCE_PRICE}{i + 1}"] for i in range(len(sources))
                        ]
                    }
                self._store("price", user_input)
                return await self.async_step_subscription()
        unit = f"{self._currency()}/kWh"
        values = {**self._values, **(user_input or {})}
        listing = ""
        if mode == MODE_FIXED:
            schema = vol.Schema({vol.Required(CONF_PRICE): _number(0, 10, "any", unit)})
        elif mode == MODE_PEAK:
            schema = vol.Schema(
                {
                    vol.Required(CONF_PRICE_PEAK): _number(0, 10, "any", unit),
                    vol.Required(CONF_PRICE_OFFPEAK): _number(0, 10, "any", unit),
                    vol.Required(CONF_OFFPEAK_RANGES, default="22:00-06:00"): selector.TextSelector(),
                }
            )
        elif mode == MODE_PER_SOURCE:
            schema = vol.Schema(
                {
                    vol.Required(f"{SOURCE_PRICE}{i + 1}"): _number(0, 10, "any", unit)
                    for i in range(len(sources))
                }
            )
            listing = "\n".join(f"{i + 1} : {source}" for i, source in enumerate(sources))
            for i, price in enumerate(self._values.get(CONF_SOURCE_PRICES) or []):
                values.setdefault(f"{SOURCE_PRICE}{i + 1}", price)
        else:
            schema = vol.Schema({vol.Required(CONF_PRICE_ENTITY): NUMERIC_SELECTOR})
        return self._form("price", schema, errors, values, {"sources": listing})

    # --------------------------------------------------------- subscription
    async def async_step_subscription(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        mode = self._values.get(CONF_SUBSCRIPTION_MODE, MODE_NONE)
        if mode == MODE_NONE:
            self._store("subscription", {})
            return await self.async_step_weather()
        if user_input is not None:
            self._store("subscription", user_input)
            return await self.async_step_weather()
        if mode == MODE_FIXED:
            schema = vol.Schema(
                {vol.Required(CONF_SUBSCRIPTION): _number(0, 10000, "any", self._currency())}
            )
        else:
            schema = vol.Schema({vol.Required(CONF_SUBSCRIPTION_ENTITY): NUMERIC_SELECTOR})
        return self._form("subscription", schema)

    # -------------------------------------------------------------- weather
    async def async_step_weather(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._store("weather", user_input)
            if not (user_input.get(CONF_WEATHER) or user_input.get(CONF_OUTDOOR_SENSOR)):
                self._store("heating", {})
                return self._finish()
            return await self.async_step_heating()
        schema = vol.Schema(
            {
                vol.Optional(CONF_WEATHER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
                vol.Optional(CONF_OUTDOOR_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
            }
        )
        values = dict(self._values)
        if self._with_name and CONF_WEATHER not in values:
            # Nearly every installation has a weather entity: propose it, the user may clear it.
            entities = sorted(self.hass.states.async_entity_ids("weather"))
            if entities:
                values[CONF_WEATHER] = entities[0]
        return self._form("weather", schema, None, values)

    # -------------------------------------------------------------- heating
    async def async_step_heating(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            heat_pumps = as_list(user_input.get(CONF_HEAT_PUMP))
            for source in heat_pumps:
                state = self.hass.states.get(source)
                if state is not None and kind_of(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)) is None:
                    errors[CONF_HEAT_PUMP] = "bad_unit"
            if not errors:
                if heat_pumps:
                    user_input[CONF_HEAT_PUMP] = heat_pumps
                    user_input[CONF_SEASON_MONTH] = int(user_input[CONF_SEASON_MONTH])
                self._store("heating", user_input if heat_pumps else {})
                return self._finish()
        schema = vol.Schema(
            {
                vol.Optional(CONF_HEAT_PUMP): SENSORS_SELECTOR,
                vol.Required(CONF_HDD_BASE, default=DEFAULT_HDD_BASE): _number(5, 25, 0.5, "°C"),
                vol.Required(CONF_SEASON_MONTH, default=DEFAULT_SEASON_MONTH): _number(1, 12, 1),
            }
        )
        values = {**self._values, **(user_input or {})}
        values[CONF_HEAT_PUMP] = as_list(values.get(CONF_HEAT_PUMP))
        return self._form("heating", schema, errors, values)


class WattendixConfigFlow(WattendixSteps, ConfigFlow, domain=DOMAIN):
    """Create a Wattendix meter."""

    VERSION = 1
    _with_name = True

    def __init__(self) -> None:
        self._values = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_meter(user_input)

    def _finish(self) -> ConfigFlowResult:
        options = dict(self._values)
        title = str(options.pop(CONF_NAME, "") or "Wattendix").strip()
        return self.async_create_entry(title=title, data={}, options=options)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WattendixOptionsFlow:
        return WattendixOptionsFlow(config_entry)


class WattendixOptionsFlow(WattendixSteps, OptionsFlowWithReload):
    """Change any level afterwards; the counters are kept."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._values = dict(config_entry.options)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_meter(user_input)

    def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(data=dict(self._values))
