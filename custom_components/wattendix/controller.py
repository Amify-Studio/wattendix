"""Glue between Home Assistant and the Wattendix engine."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

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
    DELAYED_LOOKBACK_DAYS,
    DOMAIN,
    HEATING_FIT_EXCLUDE_DAYS,
    HEATING_FIT_MIN_DAYS,
    LEARN_DAYS,
    MODE_ENTITY,
    MODE_FIXED,
    MODE_NONE,
    MODE_PEAK,
    MODE_PER_SOURCE,
    SOURCE_DAILY_VALUE,
    SOURCE_LIVE,
    SOURCE_STATISTICS,
)
from .core import model as mdl
from .core.engine import Engine, build_days, daily_temperatures, heating_points
from .core.meter import Meter, convert, kind_of
from .core.periods import end_of, previous_start, season_start, shift_to, start_of
from .core.tariff import Tariff, parse_ranges

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY = 120
TICK = timedelta(seconds=60)
FORECAST_INTERVAL = timedelta(minutes=30)
DELAYED_INTERVAL = timedelta(minutes=30)
# Share of the previous period the statistics must cover for the card to draw its curve.
PREVIOUS_COVERAGE = 0.9
NOTIFY_MIN_INTERVAL = 5.0
DEGREE_MAX_GAP = 900.0

WEATHER_DAILY, WEATHER_HOURLY, WEATHER_TWICE_DAILY = 1, 2, 4


def _number(state: State | None) -> float | None:
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None
    return value if value == value else None  # NaN


def as_list(value: Any) -> list[str]:
    """Sources were a single entity in the first version."""
    if not value:
        return []
    return [value] if isinstance(value, str) else list(value)


def _add(total: dict[int, float], part: dict[int, float]) -> None:
    for key, value in part.items():
        total[key] = total.get(key, 0.0) + value


class WattendixController:
    """Owns the engine of one config entry and feeds it."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        options = entry.options
        self.sources: list[str] = as_list(options[CONF_SOURCE])
        self.source_mode: str = options.get(CONF_SOURCE_MODE, SOURCE_LIVE)
        self.max_kw: float = float(options.get(CONF_MAX_POWER, DEFAULT_MAX_POWER))
        self.price_mode: str = options.get(CONF_PRICE_MODE, MODE_NONE)
        self.price_entity: str | None = options.get(CONF_PRICE_ENTITY)
        self.source_prices: list[float | None] = list(options.get(CONF_SOURCE_PRICES) or [])
        self.subscription_mode: str = options.get(CONF_SUBSCRIPTION_MODE, MODE_NONE)
        if self.price_mode == MODE_NONE:
            self.subscription_mode = MODE_NONE
        self.subscription_entity: str | None = options.get(CONF_SUBSCRIPTION_ENTITY)
        self.weather: str | None = options.get(CONF_WEATHER)
        self.outdoor: str | None = options.get(CONF_OUTDOOR_SENSOR)
        self.heat_pumps: list[str] = as_list(options.get(CONF_HEAT_PUMP))
        self.hdd_base: float = float(options.get(CONF_HDD_BASE, DEFAULT_HDD_BASE))
        self.season_month: int = int(options.get(CONF_SEASON_MONTH, DEFAULT_SEASON_MONTH))
        ranges: list[tuple[int, int]] = []
        try:
            ranges = parse_ranges(options.get(CONF_OFFPEAK_RANGES, ""))
        except ValueError:
            _LOGGER.warning("Invalid off-peak ranges: %s", options.get(CONF_OFFPEAK_RANGES))
        self.tariff = Tariff(
            self.price_mode,
            fixed=options.get(CONF_PRICE),
            peak=options.get(CONF_PRICE_PEAK),
            offpeak=options.get(CONF_PRICE_OFFPEAK),
            ranges=ranges,
        )
        self.engine = Engine()
        self.meters: dict[str, Meter] = {}
        self.heat_meters: dict[str, Meter] = {}
        self.snapshot: dict[str, Any] = {}
        self.learning = False
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._last_notify = 0.0
        self._notify_later: CALLBACK_TYPE | None = None
        self._last_degree_ts: float | None = None

    # ------------------------------------------------------------ features
    @property
    def priced(self) -> bool:
        return self.price_mode != MODE_NONE

    @property
    def delayed(self) -> bool:
        """True when consumption arrives late, as one total per day."""
        return self.source_mode != SOURCE_LIVE

    @property
    def has_subscription(self) -> bool:
        return self.subscription_mode != MODE_NONE

    @property
    def has_temperature(self) -> bool:
        return bool(self.weather or self.outdoor)

    @property
    def has_heating(self) -> bool:
        return bool(self.heat_pumps and self.has_temperature)

    @property
    def source_kind(self) -> str | None:
        kinds = {m.d["kind"] for m in self.meters.values() if m.d["kind"]}
        return "+".join(sorted(kinds)) if kinds else None

    def meter_summary(self) -> dict[str, Any]:
        """Guard counters of all the source sensors."""
        meters = list(self.meters.values())
        rejected = [m.d["last_rejected"] for m in meters if m.d["last_rejected"]]
        return {
            "rejected": sum(m.d["rejected"] for m in meters),
            "resets": sum(m.d["resets"] for m in meters),
            "last_rejected": max(rejected, key=lambda r: r["ts"]) if rejected else None,
        }

    # --------------------------------------------------------------- setup
    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        self.engine = Engine(data.get("engine"))
        stored = dict(data.get("meters") or {})
        if "meter" in data and self.sources:  # first version: a single source
            stored.setdefault(self.sources[0], data["meter"])
        self.meters = {s: Meter(self.max_kw, stored.get(s)) for s in self.sources}
        stored = dict(data.get("heat_meters") or {})
        if "heat_meter" in data and self.heat_pumps:
            stored.setdefault(self.heat_pumps[0], data["heat_meter"])
        self.heat_meters = {s: Meter(self.max_kw, stored.get(s)) for s in self.heat_pumps}
        self.engine.set_season_month(self.season_month if self.has_heating else None)

        if self.delayed:
            self.engine.d.setdefault("delayed", {"days": {}})
            if self.source_mode == SOURCE_DAILY_VALUE:
                for source in self.sources:
                    self._record_daily_value(source, self.hass.states.get(source))
                self._unsubs.append(
                    async_track_state_change_event(self.hass, self.sources, self._daily_value_event)
                )
            self._unsubs.append(
                async_track_time_interval(self.hass, self._delayed_job, DELAYED_INTERVAL)
            )
        else:
            self.engine.d.pop("delayed", None)
            for source in self.sources:
                self._process_source(source, self.hass.states.get(source))
            self._unsubs.append(
                async_track_state_change_event(self.hass, self.sources, self._source_event)
            )
        if self.has_heating:
            for source in self.heat_pumps:
                self._process_heat_pump(source, self.hass.states.get(source))
            self._unsubs.append(
                async_track_state_change_event(self.hass, self.heat_pumps, self._heat_event)
            )
        self._sample_temperature()
        self._refresh()

        self._unsubs.append(async_track_time_interval(self.hass, self._tick, TICK))
        if self.weather:
            self._unsubs.append(
                async_track_time_interval(self.hass, self._forecast_job, FORECAST_INTERVAL)
            )
        self._unsubs.append(
            async_track_time_change(self.hass, self._learn_job, hour=0, minute=30, second=0)
        )
        self._unsubs.append(async_at_started(self.hass, self._started))

    async def _started(self, hass: HomeAssistant) -> None:
        await self._forecast_job()
        await self._learn_job()

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._notify_later:
            self._notify_later()
            self._notify_later = None
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {
            "engine": self.engine.d,
            "meters": {s: m.d for s, m in self.meters.items()},
            "heat_meters": {s: m.d for s, m in self.heat_meters.items()},
        }

    # ----------------------------------------------------------- listeners
    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _refresh(self) -> None:
        """Recompute the snapshot and tell the entities."""
        now = dt_util.now()
        self._last_notify = now.timestamp()
        self._current_price(now)  # keeps the last known price in memory
        self.snapshot = self.engine.snapshot(
            now, priced=self.priced, subscription=self._subscription()
        )
        if not self.has_temperature and self.snapshot["reason"]:
            self.snapshot["reason"] = "no_temperature"
        self.snapshot["price"] = self.engine.d["price"] if self.priced else None
        self.snapshot["offpeak"] = self.tariff.is_offpeak(now)
        self.snapshot["meter"] = self.meter_summary()
        for listener in list(self._listeners):
            listener()
        self._store.async_delay_save(self._data, SAVE_DELAY)

    @callback
    def _refresh_soon(self) -> None:
        """Refresh now, or shortly if one just happened (chatty sources)."""
        wait = self._last_notify + NOTIFY_MIN_INTERVAL - dt_util.utcnow().timestamp()
        if wait <= 0:
            self._refresh()
        elif self._notify_later is None:

            @callback
            def _later(_: datetime) -> None:
                self._notify_later = None
                self._refresh()

            self._notify_later = async_call_later(self.hass, wait, _later)

    # -------------------------------------------------------------- prices
    def _current_price(self, now: datetime) -> float | None:
        """Price of a kWh now (per-source prices are applied in ``_source_price``)."""
        if not self.priced:
            return None
        if self.price_mode == MODE_PER_SOURCE:
            return self.engine.d["price"]
        entity_price = None
        if self.price_mode == MODE_ENTITY:
            value = _number(self.hass.states.get(self.price_entity)) if self.price_entity else None
            if value is not None and value >= 0:
                self.engine.d["price"] = value
            entity_price = self.engine.d["price"]  # last known value while unavailable
        price = self.tariff.price(now, entity_price)
        if price is not None:
            self.engine.d["price"] = price
        return price

    def _source_price(self, source: str, now: datetime) -> float | None:
        """Price applied to the energy counted by one source."""
        if self.price_mode != MODE_PER_SOURCE:
            return self._current_price(now)
        index = self.sources.index(source)
        price = self.source_prices[index] if index < len(self.source_prices) else None
        if price is not None:
            self.engine.d["price"] = price
        return price

    def _subscription(self) -> float | None:
        if self.subscription_mode == MODE_FIXED:
            return self.entry.options.get(CONF_SUBSCRIPTION)
        if self.subscription_mode == MODE_ENTITY and self.subscription_entity:
            value = _number(self.hass.states.get(self.subscription_entity))
            if value is not None and value > 0:
                self.engine.d["subscription"] = value
            return self.engine.d["subscription"]  # last known value while unavailable
        return None

    @property
    def subscription_available(self) -> bool | None:
        if self.subscription_mode != MODE_ENTITY or not self.subscription_entity:
            return None
        value = _number(self.hass.states.get(self.subscription_entity))
        return value is not None and value > 0

    # ------------------------------------------------------- live sources
    def _feed(self, meter: Meter, entity_id: str, state: State | None) -> float:
        """kWh to count for this new state of a source."""
        ts = dt_util.utcnow().timestamp()
        value = _number(state)
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
        kind = kind_of(unit) if state else meter.d["kind"]
        if kind is None:
            return 0.0
        if value is None:
            return meter.feed_power(None, ts) if kind == "power" else 0.0
        meter.bind(entity_id, kind)
        converted = convert(value, unit)
        if converted is None:
            return 0.0
        if kind == "power":
            return meter.feed_power(converted, ts)
        return meter.feed_energy(converted, ts)

    @callback
    def _process_source(self, source: str, state: State | None) -> None:
        delta = self._feed(self.meters[source], source, state)
        if delta > 0:
            now = dt_util.now()
            self.engine.add_energy(delta, now, self._source_price(source, now))

    @callback
    def _process_heat_pump(self, source: str, state: State | None) -> None:
        delta = self._feed(self.heat_meters[source], source, state)
        if delta > 0:
            self.engine.add_heating_energy(delta, dt_util.now())

    @callback
    def _source_event(self, event: Event) -> None:
        self._process_source(event.data["entity_id"], event.data.get("new_state"))
        self._refresh_soon()

    @callback
    def _heat_event(self, event: Event) -> None:
        self._process_heat_pump(event.data["entity_id"], event.data.get("new_state"))
        self._refresh_soon()

    # ---------------------------------------------------- delayed sources
    @callback
    def _record_daily_value(self, source: str, state: State | None) -> bool:
        """A daily-reading sensor changed: its value is the consumption of the day before."""
        value = _number(state)
        if value is None or state is None:
            return False
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        kwh = convert(value, unit)
        if kwh is None or kind_of(unit) != "energy":
            return False
        day = (dt_util.as_local(state.last_changed).date() - timedelta(days=1)).isoformat()
        values = self.engine.d.setdefault("daily_values", {}).setdefault(source, {})
        values[day] = round(kwh, 4)
        for key in sorted(values)[:-DELAYED_LOOKBACK_DAYS]:
            del values[key]
        return True

    async def _daily_value_event(self, event: Event) -> None:
        if self._record_daily_value(event.data["entity_id"], event.data.get("new_state")):
            await self._delayed_job()

    def _delayed_cost(self, parts: dict[str, float]) -> float | None:
        """Cost of one day, from the kWh of each source."""
        total = sum(parts.values())
        if self.price_mode == MODE_FIXED:
            price = self.entry.options.get(CONF_PRICE)
            return None if price is None else total * price
        if self.price_mode == MODE_PER_SOURCE:
            cost = 0.0
            for source, kwh in parts.items():
                index = self.sources.index(source)
                price = self.source_prices[index] if index < len(self.source_prices) else None
                if price is None:
                    return None
                cost += kwh * price
            return cost
        if self.price_mode == MODE_ENTITY:
            price = self._current_price(dt_util.now())
            return None if price is None else total * price
        return None

    async def _delayed_job(self, _: datetime | None = None, refresh: bool = True) -> None:
        """Rebuild the daily totals of a delayed source."""
        now = dt_util.now()
        today = now.date().isoformat()
        per_source: dict[str, dict[str, float]] = {}
        if self.source_mode == SOURCE_STATISTICS:
            if "recorder" not in self.hass.config.components:
                return
            start = start_of("day", now) - timedelta(days=DELAYED_LOOKBACK_DAYS)
            for source in self.sources:
                rows = await self._statistics(source, start, "day", {"change"}, {"energy": "kWh"})
                per_source[source] = {
                    dt_util.as_local(dt_util.utc_from_timestamp(row["start"])).date().isoformat(): row[
                        "change"
                    ]
                    for row in rows
                    if row.get("change") is not None
                }
        else:
            per_source = self.engine.d.get("daily_values") or {}

        old = (self.engine.d.get("delayed") or {}).get("days") or {}
        limit = self.max_kw * 24
        days: dict[str, dict[str, Any]] = {}
        for day in sorted({d for values in per_source.values() for d in values}):
            if day >= today:  # a day in progress is not a total yet
                continue
            parts = {
                source: values[day]
                for source, values in per_source.items()
                if source in self.sources and day in values and 0 <= values[day] <= limit
            }
            if not parts:
                continue
            kwh = round(sum(parts.values()), 4)
            known = old.get(day)
            # A day already priced keeps its cost: a new rate never rewrites the past.
            if known and abs(known["kwh"] - kwh) < 0.001 and (
                known.get("cost") is not None or not self.priced
            ):
                days[day] = known
            else:
                cost = self._delayed_cost(parts)
                days[day] = {"kwh": kwh, "cost": None if cost is None else round(cost, 4)}
        self.engine.set_delayed_days(days, now)
        if refresh:
            self._refresh()

    # --------------------------------------------------------- temperature
    def _outdoor_temperature(self) -> float | None:
        """Outdoor temperature in °C: the sensor if configured, the weather entity otherwise."""
        if self.outdoor:
            state = self.hass.states.get(self.outdoor)
            value = _number(state)
            if value is not None and state is not None:
                unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or UnitOfTemperature.CELSIUS
                return self._celsius(value, unit)
            # Never mix the two sources: they do not read the same temperature.
            return None
        return self._weather_temperature()

    def _weather_temperature(self) -> float | None:
        """Current temperature of the weather entity, in °C."""
        if self.weather:
            state = self.hass.states.get(self.weather)
            if state is not None and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                value = state.attributes.get("temperature")
                if isinstance(value, (int, float)):
                    return self._celsius(float(value), self._weather_unit(state))
        return None

    def _weather_unit(self, state: State) -> str:
        return state.attributes.get("temperature_unit") or self.hass.config.units.temperature_unit

    @staticmethod
    def _celsius(value: float, unit: str) -> float | None:
        try:
            return TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
        except Exception:  # noqa: BLE001 - unknown unit
            return None

    @callback
    def _sample_temperature(self) -> None:
        if not self.has_temperature:
            return
        temp = self._outdoor_temperature()
        ts = dt_util.utcnow().timestamp()
        if temp is None:
            self._last_degree_ts = None
            return
        now = dt_util.now()
        self.engine.sample_temperature(temp, now)
        if self.outdoor and self.weather:
            service = self._weather_temperature()
            if service is not None:
                self.engine.sample_weather_offset(temp, service)
        if self.has_heating and self._last_degree_ts is not None:
            gap = ts - self._last_degree_ts
            if 0 < gap <= DEGREE_MAX_GAP:
                self.engine.add_degree_time(temp, self.hdd_base, gap, now)
        self._last_degree_ts = ts

    @callback
    def _tick(self, _: datetime) -> None:
        # A power sensor that keeps the same value sends no event: integrate on the tick.
        if not self.delayed:
            for source, meter in self.meters.items():
                if meter.d["kind"] == "power":
                    self._process_source(source, self.hass.states.get(source))
        if self.has_heating:
            for source, meter in self.heat_meters.items():
                if meter.d["kind"] == "power":
                    self._process_heat_pump(source, self.hass.states.get(source))
        self._sample_temperature()
        self._refresh()

    # ------------------------------------------------------------ forecast
    async def _forecast_job(self, _: datetime | None = None) -> None:
        if not self.weather:
            return
        state = self.hass.states.get(self.weather)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        features = state.attributes.get("supported_features", 0) or 0
        kind = (
            "daily"
            if features & WEATHER_DAILY
            else "twice_daily"
            if features & WEATHER_TWICE_DAILY
            else "hourly"
            if features & WEATHER_HOURLY
            else None
        )
        if kind is None:
            return
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": self.weather, "type": kind},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - a weather outage must not break anything
            _LOGGER.debug("Forecast unavailable: %s", err)
            return
        forecast = ((response or {}).get(self.weather) or {}).get("forecast") or []
        unit = self._weather_unit(state)
        per_day: dict[str, list[float]] = {}
        for item in forecast:
            when = dt_util.parse_datetime(str(item.get("datetime", "")))
            high = item.get("temperature")
            if when is None or not isinstance(high, (int, float)):
                continue
            low = item.get("templow")
            values = [float(high)] + ([float(low)] if isinstance(low, (int, float)) else [])
            per_day.setdefault(dt_util.as_local(when).date().isoformat(), []).extend(values)
        needed = {"daily": 1, "twice_daily": 2, "hourly": 18}[kind]
        days = []
        for key, values in sorted(per_day.items()):
            if len(values) < needed:
                continue
            mean = self._celsius((min(values) + max(values)) / 2, unit)
            if mean is not None:
                days.append({"date": key, "t": round(mean, 2)})
        self.engine.set_forecast(days, dt_util.now())
        self._refresh()

    # ---------------------------------------------------------- statistics
    async def _statistics(
        self, statistic_id: str, start: datetime, period: str, types: set[str], units: dict[str, str]
    ) -> list[dict[str, Any]]:
        from homeassistant.components.recorder import get_instance  # noqa: PLC0415
        from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
            statistics_during_period,
        )

        result = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            dt_util.as_utc(start),
            None,
            {statistic_id},
            period,
            units,
            types,
        )
        return result.get(statistic_id, [])

    async def _energy_series(
        self, entity_id: str, kind: str | None, start: datetime, period: str
    ) -> dict[int, float]:
        """kWh per period start (epoch seconds) from the recorder statistics."""
        if kind == "power":
            rows = await self._statistics(entity_id, start, period, {"mean"}, {"power": "kW"})
            hours = {"5minute": 1 / 12, "hour": 1.0}.get(period)
            out = {}
            for row in rows:
                if row.get("mean") is not None:
                    length = hours or (row["end"] - row["start"]) / 3600
                    out[int(row["start"])] = row["mean"] * length
            return out
        rows = await self._statistics(entity_id, start, period, {"change"}, {"energy": "kWh"})
        return {int(r["start"]): r["change"] for r in rows if r.get("change") is not None}

    async def _series(self, meters: dict[str, Meter], start: datetime, period: str) -> dict[int, float]:
        """kWh per period start, all the sources of a group added together."""
        total: dict[int, float] = {}
        for source, meter in meters.items():
            _add(total, await self._energy_series(source, meter.d["kind"], start, period))
        return total

    async def _hourly(self, meters: dict[str, Meter], start: datetime) -> dict[int, float]:
        """Hourly kWh, completed by the 5-minute statistics for the latest hours."""
        total: dict[int, float] = {}
        recent_start = start_of("hour", dt_util.now()) - timedelta(hours=3)
        for source, meter in meters.items():
            hourly = await self._energy_series(source, meter.d["kind"], start, "hour")
            recent = await self._energy_series(source, meter.d["kind"], recent_start, "5minute")
            for ts, value in recent.items():
                hour = ts - ts % 3600
                if hour not in hourly:
                    total[hour] = total.get(hour, 0.0) + value
            _add(total, hourly)
        return total

    async def async_curve(self, period: str) -> dict[str, list[list[float | None]]]:
        """Cumulative consumption of the current and previous periods, for the card.

        Rebuilt from the source statistics, so the curves are complete from the
        first day, whenever Wattendix was installed. Each point is
        [epoch ms, kWh, cost with standing charge (None without price)].
        The previous period is laid on the current one's axis at the same
        wall-clock offset (yesterday 14:00 sits at today 14:00), so the card
        can compare both at a glance.
        """
        now = dt_util.now()
        start, end = start_of(period, now), end_of(period, now)
        before = previous_start(period, start)
        subscription = (self.snapshot.get("periods", {}).get(period) or {}).get("subscription") or 0.0
        if self.delayed and period in ("hour", "day"):
            return {"points": [], "previous": []}
        if not self.delayed and "recorder" not in self.hass.config.components:
            return {"points": [], "previous": []}

        current_raw, _ = await self._cumulative(period, start, now)
        previous_raw, covered = await self._cumulative(period, before, start)
        # A previous period known only in part would look like a frugal one: leave
        # it out (the card then keeps its total as a flat line).
        if covered < PREVIOUS_COVERAGE * (start.timestamp() - before.timestamp()):
            previous_raw = []

        # Costs follow the shape of the recorded hours, at the mean price really
        # paid: this period's mean price, and the previous period's own total.
        # Delayed sources already carry the real cost of each day.
        scale = previous_scale = 1.0
        if not self.delayed:
            current = self.engine.d["periods"][period]
            scale = previous_scale = 0.0
            if current_raw and current_raw[-1][2] > 0 and current["kwh"] > 0:
                scale = (current["cost"] / current["kwh"]) / (current_raw[-1][2] / current_raw[-1][1])
            closed = self.engine.d["previous"].get(period) or {}
            if previous_raw and previous_raw[-1][2] > 0:
                if closed.get("cost") is not None:
                    previous_scale = closed["cost"] / previous_raw[-1][2]
                elif current["kwh"] > 0:
                    previous_scale = (current["cost"] / current["kwh"]) / (
                        previous_raw[-1][2] / previous_raw[-1][1]
                    )

        def points(
            raw: list[tuple[float, float, float]], low: datetime, high: datetime, factor: float
        ) -> list[tuple[float, float, float | None]]:
            span = high.timestamp() - low.timestamp()
            return [
                (
                    ts,
                    round(k, 3),
                    round(c * factor + subscription * (ts - low.timestamp()) / span, 3)
                    if self.priced
                    else None,
                )
                for ts, k, c in raw
            ]

        return {
            "points": [[int(ts * 1000), k, c] for ts, k, c in points(current_raw, start, end, scale)],
            "previous": [
                [int(shift_to(before, start, end, ts) * 1000), k, c]
                for ts, k, c in points(previous_raw, before, start, previous_scale)
            ],
        }

    async def _cumulative(
        self, period: str, low: datetime, high: datetime
    ) -> tuple[list[tuple[float, float, float]], float]:
        """Running (end of slot, kWh, unscaled cost) from ``low`` up to ``high``.

        Also gives how many seconds of that span the recorded slots cover.
        """
        tz = low.tzinfo
        covered = 0.0
        if self.delayed:
            out: list[tuple[float, float, float]] = []
            kwh = cost = 0.0
            for key, entry in sorted(((self.engine.d.get("delayed") or {}).get("days") or {}).items()):
                day = datetime.fromisoformat(key).replace(tzinfo=tz)
                if not low.timestamp() <= day.timestamp() < high.timestamp():
                    continue
                kwh += entry["kwh"]
                cost += entry.get("cost") or 0.0
                end = end_of("day", day).timestamp()
                covered += end - day.timestamp()
                out.append((end, kwh, cost))
            return out, covered

        rows: dict[int, tuple[float, int]] = {}
        if period in ("hour", "day"):
            fine = await self._series(self.meters, low, "5minute")
            coarse = await self._series(self.meters, low, "hour")
            detailed = {ts - ts % 3600 for ts in fine}
            rows = {ts: (v, 300) for ts, v in fine.items()}
            rows.update({ts: (v, 3600) for ts, v in coarse.items() if ts not in detailed})
        elif period in ("week", "month"):
            rows = {ts: (v, 3600) for ts, v in (await self._series(self.meters, low, "hour")).items()}
        else:
            rows = {ts: (v, 86400) for ts, v in (await self._series(self.meters, low, "day")).items()}

        prices = self.tariff.hour_prices(self.engine.d["price"]) if self.priced else None
        bottom, top = low.timestamp(), high.timestamp()
        out = []
        kwh = cost = 0.0
        for ts, (value, length) in sorted(rows.items()):
            if ts < bottom or ts + length > top + 1 or not 0 <= value <= self.max_kw * length / 3600:
                continue
            kwh += value
            cost += value * (
                prices[datetime.fromtimestamp(ts, tz).hour] if prices and length <= 3600 else 1.0
            )
            covered += length
            out.append((ts + length, kwh, cost))
        return out, covered

    # ------------------------------------------------------------ learning
    async def _learn_job(self, _: datetime | None = None) -> None:
        """Rebuild the model (and seed the counters once) from the recorder."""
        if self.learning:
            return
        self.learning = True
        try:
            await self._learn()
        except Exception:  # noqa: BLE001 - learning must never break the counters
            _LOGGER.exception("Wattendix learning failed")
        finally:
            self.learning = False
        self._refresh()

    async def _temperatures(self, start: datetime) -> dict[int, tuple[float, float, float]]:
        """Hourly (min, max, mean) of the outdoor sensor, in °C."""
        if not self.outdoor or "recorder" not in self.hass.config.components:
            return {}
        rows = await self._statistics(
            self.outdoor, start, "hour", {"mean", "min", "max"}, {"temperature": "°C"}
        )
        return {
            int(r["start"]): (r["min"], r["max"], r["mean"])
            for r in rows
            if None not in (r.get("min"), r.get("max"), r.get("mean"))
        }

    async def _learn(self) -> None:
        now = dt_util.now()
        tz = now.tzinfo
        engine = self.engine
        has_recorder = "recorder" in self.hass.config.components
        lookback = DELAYED_LOOKBACK_DAYS if self.delayed else LEARN_DAYS
        start = start_of("day", now) - timedelta(days=lookback)
        temps = await self._temperatures(start)
        extremes = {ts: (v[0], v[1]) for ts, v in temps.items()}

        if self.delayed:
            await self._delayed_job(refresh=False)
            if self.has_temperature:
                by_day = daily_temperatures(extremes, tz, engine.d["day_log"])
                today = now.date().isoformat()
                days = [
                    # Only daily totals are known: the hourly shape is not used in this mode.
                    {"date": key, "t": by_day.get(key), "h": [entry["kwh"] / 24] * 24}
                    for key, entry in engine.d["delayed"]["days"].items()
                    if key < today
                ]
                model = await self.hass.async_add_executor_job(mdl.learn, days, None, self.max_kw)
                model["learned_at"] = now.isoformat()
                engine.d["model"] = model
            else:
                engine.d["model"] = None
        else:
            hourly = await self._hourly(self.meters, start) if has_recorder else {}
            prices = (
                self.tariff.hour_prices() if self.price_mode in (MODE_FIXED, MODE_PEAK) else None
            )
            if self.has_temperature:
                days = build_days(hourly, extremes, tz, engine.d["day_log"], now.date())
                model = await self.hass.async_add_executor_job(mdl.learn, days, prices, self.max_kw)
                model["learned_at"] = now.isoformat()
                engine.d["model"] = model
            else:
                engine.d["model"] = None

            # Prices used to value recorded kWh: today's rates.
            seed_prices = prices
            if seed_prices is None and self.priced:
                seed_prices = self.tariff.hour_prices(self._current_price(now))
                if seed_prices is None and engine.d["price"] is not None:
                    seed_prices = [engine.d["price"]] * 24
            if has_recorder and hourly:
                if not engine.d.get("backfilled"):
                    since = start_of("year", now).replace(year=now.year - 1) - timedelta(days=40)
                    monthly = await self._series(self.meters, since, "month")
                    engine.backfill(hourly, monthly, dt_util.now(), seed_prices, self.max_kw)
                elif seed_prices and self._has_unpriced():
                    engine.backfill(hourly, {}, dt_util.now(), seed_prices, self.max_kw, cost_only=True)

        if self.has_heating and has_recorder:
            heating_start = start_of("day", now) - timedelta(days=LEARN_DAYS)
            await self._learn_heating(now, heating_start, {ts: v[2] for ts, v in temps.items()})

    def _has_unpriced(self) -> bool:
        d = self.engine.d
        return (
            any(p.get("u", 0) > 0 for p in d["periods"].values())
            or any(e.get("cost") is None for entries in d["history"].values() for e in entries)
            or any(e and e.get("cost") is None for e in d["previous"].values())
        )

    async def _learn_heating(
        self, now: datetime, start: datetime, mean_temps: dict[int, float]
    ) -> None:
        """Fit heat pump kWh against degree-days, and seed the heating periods once."""
        tz = now.tzinfo
        low = start.timestamp()
        mean_temps = {ts: t for ts, t in mean_temps.items() if ts >= low}
        heating = self.engine.d["heating"]
        hourly = await self._hourly(self.heat_meters, start)
        points = heating_points(hourly, mean_temps, tz, self.hdd_base, now.date(), self.max_kw)
        # Own log for days the recorder does not cover (no outdoor sensor statistics).
        if not points:
            points = [
                (e["hd"], e["hk"])
                for key, e in sorted(self.engine.d["day_log"].items())
                if e.get("hd") is not None and key < now.date().isoformat()
            ]
        reference = [p for p in points[:-HEATING_FIT_EXCLUDE_DAYS] if p[0] >= 1.0]
        fit = mdl.fit_line(reference) if len(reference) >= HEATING_FIT_MIN_DAYS else None
        if fit:
            fit["hdd_base"] = self.hdd_base
        heating["fit"] = fit

        if heating.get("seeded") != self.hdd_base and mean_temps:
            self.engine.roll(dt_util.now())
            for period, begin in (
                ("month", start_of("month", now)),
                ("season", season_start(now, self.season_month)),
            ):
                lo = begin.timestamp()
                current = heating["periods"][period]
                current["hdd"] = sum(
                    max(0.0, self.hdd_base - t) / 24 for ts, t in mean_temps.items() if ts >= lo
                )
                current["kwh"] = sum(
                    v for ts, v in hourly.items() if ts >= lo and 0 <= v <= self.max_kw
                )
            heating["seeded"] = self.hdd_base
