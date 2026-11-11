"""Tests of the pure calculation code."""

from __future__ import annotations

import importlib.util
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Load the core package without importing Home Assistant.
CORE = Path(__file__).parent.parent / "custom_components" / "wattendix" / "core"
spec = importlib.util.spec_from_file_location(
    "wattendix_core", CORE / "__init__.py", submodule_search_locations=[str(CORE)]
)
package = importlib.util.module_from_spec(spec)
sys.modules["wattendix_core"] = package
spec.loader.exec_module(package)

from wattendix_core import model as mdl  # noqa: E402
from wattendix_core.engine import Engine, build_days, remaining_today  # noqa: E402
from wattendix_core.meter import Meter, convert, kind_of  # noqa: E402
from wattendix_core.periods import days_in_month, end_of, fraction, start_of  # noqa: E402
from wattendix_core.tariff import MODE_PEAK, Tariff, parse_ranges  # noqa: E402

TZ = ZoneInfo("Europe/Paris")


def at(*args: int) -> datetime:
    return datetime(*args, tzinfo=TZ)


# ------------------------------------------------------------------ meter
def test_units() -> None:
    assert kind_of("kWh") == "energy" and kind_of("W") == "power" and kind_of("°C") is None
    assert convert(1500, "Wh") == 1.5 and convert(2, "MWh") == 2000 and convert(450, "W") == 0.45


def test_meter_counts_normal_increments() -> None:
    meter = Meter(36)
    assert meter.feed_energy(100.0, 0) == 0
    assert meter.feed_energy(100.5, 600) == pytest.approx(0.5)
    assert meter.feed_energy(100.5, 1200) == 0


def test_meter_glitch_to_zero_and_back() -> None:
    meter = Meter(36)
    meter.feed_energy(20000.0, 0)
    assert meter.feed_energy(0.0, 60) == 0  # glitch
    assert meter.feed_energy(20000.2, 180) == pytest.approx(0.2)  # only the real difference
    assert meter.d["rejected"] == 0
    assert meter.feed_energy(0.0, 240) == 0
    assert meter.feed_energy(20000.2, 300) == 0  # back to the very same value: nothing, no alarm
    assert meter.d["rejected"] == 0 and meter.d["resets"] == 2
    assert meter.feed_energy(20000.7, 780) == pytest.approx(0.5)


def test_meter_real_reset_keeps_counting() -> None:
    meter = Meter(36)
    meter.feed_energy(500.0, 0)
    assert meter.feed_energy(0.0, 60) == 0
    assert meter.feed_energy(0.3, 660) == pytest.approx(0.3)
    assert meter.feed_energy(0.9, 1260) == pytest.approx(0.6)


def test_meter_rejects_impossible_jump() -> None:
    meter = Meter(9)
    meter.feed_energy(100.0, 0)
    assert meter.feed_energy(900.0, 300) == 0  # 800 kWh in 5 minutes
    assert meter.d["rejected"] == 1 and meter.d["last_rejected"]["to"] == 900.0
    assert meter.feed_energy(900.4, 900) == pytest.approx(0.4)


def test_meter_jitter_is_not_counted_twice() -> None:
    meter = Meter(36)
    meter.feed_energy(100.00, 0)
    meter.feed_energy(100.10, 600)
    assert meter.feed_energy(100.08, 660) == 0
    assert meter.feed_energy(100.12, 720) == pytest.approx(0.02)


def test_meter_slow_integer_counter() -> None:
    meter = Meter(36)
    meter.feed_energy(1000.0, 0)
    for ts in range(60, 3600, 60):
        assert meter.feed_energy(1000.0, ts) == 0
    assert meter.feed_energy(1001.0, 3600) == 1.0  # the window runs since the last change


def test_meter_downtime_is_counted() -> None:
    meter = Meter(36)
    meter.feed_energy(1000.0, 0)
    assert meter.feed_energy(1012.0, 6 * 3600) == 12.0


def test_meter_rebinds_on_new_source() -> None:
    meter = Meter(36)
    meter.bind("sensor.a", "energy")
    meter.feed_energy(1000.0, 0)
    meter.bind("sensor.b", "energy")
    assert meter.feed_energy(5.0, 60) == 0


def test_power_integration() -> None:
    meter = Meter(36)
    assert meter.feed_power(1.2, 0) == 0
    assert meter.feed_power(1.2, 60) == pytest.approx(0.02)
    assert meter.feed_power(None, 120) == pytest.approx(0.02)
    assert meter.feed_power(2.0, 180) == 0  # was unavailable
    assert meter.feed_power(2.0, 4000) == 0  # too long a silence
    assert meter.feed_power(500.0, 4060) == pytest.approx(2.0 * 60 / 3600)
    assert meter.d["rejected"] == 1


# ----------------------------------------------------------------- tariff
def test_ranges() -> None:
    assert parse_ranges("23:10-07:11, 12h30-14h") == [(1390, 431), (750, 840)]
    with pytest.raises(ValueError):
        parse_ranges("25:00-07:00")
    with pytest.raises(ValueError):
        parse_ranges("night")


def test_peak_offpeak() -> None:
    tariff = Tariff(MODE_PEAK, peak=0.20, offpeak=0.10, ranges=parse_ranges("23:10-07:11"))
    assert tariff.price(at(2026, 11, 11, 3, 0)) == 0.10
    assert tariff.price(at(2026, 11, 11, 7, 11)) == 0.20
    assert tariff.price(at(2026, 11, 11, 23, 30)) == 0.10
    prices = tariff.hour_prices()
    assert prices[3] == pytest.approx(0.10) and prices[12] == pytest.approx(0.20)
    assert prices[23] == pytest.approx(0.10 * 50 / 60 + 0.20 * 10 / 60)


# ---------------------------------------------------------------- periods
def test_periods() -> None:
    now = at(2026, 11, 11, 10, 30)  # a Wednesday
    assert start_of("week", now) == at(2026, 11, 9)
    assert end_of("month", now) == at(2026, 12, 1)
    assert end_of("year", now) == at(2027, 1, 1)
    assert days_in_month(now) == 30
    assert fraction("hour", now) == pytest.approx(0.5)
    # Daylight saving: 25 October 2026 lasts 25 hours.
    assert (end_of("day", at(2026, 10, 25, 12)).timestamp() - start_of("day", at(2026, 10, 25, 12)).timestamp()) == 25 * 3600


# ------------------------------------------------------------------ model
def u_shape(temp: float) -> float:
    return 10 + 1.5 * max(0, 15 - temp) + 0.8 * max(0, temp - 22)


def synthetic_days(n: int = 300) -> list[dict]:
    days = []
    shape = [0.6] * 7 + [1.2] * 16 + [0.6]
    total = sum(shape)
    for i in range(n):
        temp = 12 + 14 * math.sin(i / 58)
        kwh = u_shape(temp)
        days.append({"date": f"d{i:03d}", "t": temp, "h": [kwh * s / total for s in shape]})
    return days


def test_model_learns_u_shape() -> None:
    model = mdl.learn(synthetic_days(), [0.2] * 24, 36)
    assert model["ready"]
    for temp in (0, 6, 14, 20, 25):
        assert mdl.expected(model, temp, "kwh") == pytest.approx(u_shape(temp), rel=0.08)
        assert mdl.expected(model, temp, "cost") == pytest.approx(u_shape(temp) * 0.2, rel=0.08)
    profile = mdl.profile(model, 5, "kwh")
    assert len(profile) == 25 and profile[0] == 0 and profile[-1] == 1
    assert profile[7] == pytest.approx(7 * 0.6 / (0.6 * 8 + 1.2 * 16), abs=0.01)


def test_model_not_ready_without_history() -> None:
    model = mdl.learn(synthetic_days(5), None, 36)
    assert not model["ready"]
    assert mdl.expected(model, 10, "kwh") is None


def test_model_ignores_absurd_hours() -> None:
    days = synthetic_days()
    days[10]["h"][3] = 5000.0
    model = mdl.learn(days, None, 36)
    assert max(b["kwh"] for b in model["bins"]) < 60


def test_fit_line() -> None:
    fit = mdl.fit_line([(x, 0.2 + 1.94 * x) for x in range(0, 15)])
    assert fit["slope"] == pytest.approx(1.94) and fit["base"] == pytest.approx(0.2)
    assert fit["r2"] == pytest.approx(1.0)


def test_fit_line_never_has_a_negative_base() -> None:
    # Mild days where the heating stays off pull an ordinary fit below zero.
    points = [(x, 0.0) for x in (1, 2, 3)] + [(x, 2.0 * x) for x in range(8, 16)]
    fit = mdl.fit_line(points)
    assert fit["base"] == 0 and 1.8 < fit["slope"] < 2.0


def test_live_bias_bootstraps_the_daily_one() -> None:
    engine = Engine()
    now = at(2026, 3, 6, 9, 0)
    assert engine.temperature_bias(now) == (0.0, 0)
    for _ in range(40):
        engine.sample_weather_offset(12.5, 10.0)
    assert engine.temperature_bias(now) == (pytest.approx(2.5), 0)


# ----------------------------------------------------------------- engine
def test_remaining_today_matches_v29_formula() -> None:
    # Values of the validated YAML package: expected 3.14, profile share 0.42, done 1.60.
    profile = [0, 0.028, 0.053, 0.078, 0.101, 0.123, 0.151, 0.185, 0.22, 0.254, 0.29, 0.328, 0.372,
               0.413, 0.454, 0.496, 0.541, 0.589, 0.638, 0.688, 0.74, 0.787, 0.828, 0.933, 1]
    hour = 10.5
    share = 0.29 + (0.328 - 0.29) * 0.5
    ratio = max(0.5, min(2, 1.60 / (3.14 * share)))
    wanted = 3.14 * (1 - share) * ((1 - share) + share * ratio)
    value, method = remaining_today(1.60, 3.14, profile, hour, 6.0)
    assert value == pytest.approx(wanted) and method == "model"
    value, method = remaining_today(1.60, None, None, 12, 6.0)
    assert value == pytest.approx(3.0) and method == "average"
    value, method = remaining_today(2.0, None, None, 6, None)
    assert value == pytest.approx(6.0) and method == "pace"


def run(engine: Engine, start: datetime, hours: int, kwh_per_hour: float, price: float | None):
    now = start
    for _ in range(hours * 4):
        engine.add_energy(kwh_per_hour / 4, now, price)
        now += timedelta(minutes=15)
    return now


def test_engine_periods_and_history() -> None:
    engine = Engine()
    now = run(engine, at(2026, 3, 2, 0, 0), 24 * 9, 1.0, 0.2)  # Monday 2 March, 9 days
    snap = engine.snapshot(now, priced=True, subscription=31.0)
    day = snap["periods"]["day"]
    assert day["kwh_previous"] == pytest.approx(24.0)
    assert day["cost_previous"] == pytest.approx(24 * 0.2 + 1.0)  # 31 € / 31 days
    assert snap["periods"]["week"]["kwh_previous"] == pytest.approx(168.0)
    assert len(engine.d["history"]["day"]) == 7
    assert snap["method"] == "average" and snap["reason"] == "learning"
    # Midnight of the 11th: nothing done yet today, estimate = mean of the last days.
    assert day["kwh_estimate"] == pytest.approx(24.0)
    assert day["cost_estimate"] == pytest.approx(24 * 0.2 + 1.0)
    assert day["kwh_trend"] == pytest.approx(0.0)
    month = snap["periods"]["month"]
    assert month["kwh_estimate"] == pytest.approx(30 * 24.0)  # started on the 2nd
    assert month["cost_estimate"] == pytest.approx(30 * 24 * 0.2 + 31.0)
    assert month["cost"] == pytest.approx(9 * 24 * 0.2 + 10.0, abs=0.02)  # 743-hour month


def test_engine_price_change_does_not_rewrite_the_past() -> None:
    engine = Engine()
    now = run(engine, at(2026, 3, 2, 0, 0), 12, 1.0, 0.10)
    now = run(engine, now, 6, 1.0, 0.30)
    snap = engine.snapshot(now, priced=True, subscription=None)
    assert snap["periods"]["day"]["cost"] == pytest.approx(12 * 0.10 + 6 * 0.30)


def test_engine_without_price_is_kwh_only() -> None:
    engine = Engine()
    now = run(engine, at(2026, 3, 2, 0, 0), 30, 2.0, None)
    snap = engine.snapshot(now, priced=False, subscription=None)
    assert "cost" not in snap["periods"]["day"]
    assert snap["periods"]["day"]["kwh"] == pytest.approx(12.0)
    assert snap["periods"]["day"]["kwh_previous"] == pytest.approx(48.0)


def test_engine_gap_has_no_previous() -> None:
    engine = Engine()
    now = run(engine, at(2026, 3, 2, 0, 0), 30, 1.0, None)
    snap = engine.snapshot(now + timedelta(days=3), priced=False, subscription=None)
    assert snap["periods"]["day"]["kwh_previous"] is None


def test_engine_uses_model_and_forecast() -> None:
    engine = Engine()
    engine.d["model"] = mdl.learn(synthetic_days(), [0.2] * 24, 36)
    now = at(2026, 3, 4, 12, 0)  # Wednesday
    engine.set_forecast(
        [{"date": (now.date() + timedelta(days=k)).isoformat(), "t": 5.0} for k in range(5)], now
    )
    snap = engine.snapshot(now, priced=True, subscription=None)
    assert snap["method"] == "model" and snap["temperature_today"] == 5.0
    expected = mdl.expected(engine.d["model"], 5.0, "kwh")
    share = mdl.profile(engine.d["model"], 5.0, "kwh")[12]
    assert snap["periods"]["day"]["kwh_estimate"] == pytest.approx(
        expected * (1 - share) * ((1 - share) + share * 0.5)  # nothing consumed: ratio floor
    )
    # Week: rest of today + 4 forecast days (Thu..Sun).
    assert snap["periods"]["week"]["kwh_estimate"] == pytest.approx(
        snap["periods"]["day"]["kwh_estimate"] + 4 * expected
    )


def test_temperature_bias_is_learned() -> None:
    engine = Engine()
    for day in range(1, 6):
        morning = at(2026, 3, day, 6, 0)
        engine.set_forecast([{"date": morning.date().isoformat(), "t": 8.0}], morning)
        engine.sample_temperature(6.0, morning)
        engine.sample_temperature(15.0, morning.replace(hour=15))
    bias, days = engine.temperature_bias(at(2026, 3, 6, 9, 0))
    assert bias == pytest.approx(2.5) and days == 5


def test_year_profile_and_comparison() -> None:
    engine = Engine()
    now = at(2026, 1, 1, 0, 0)
    engine.roll(now)
    while now < at(2027, 3, 1):
        engine.add_energy(6.0, now, None)  # 1 kWh per hour
        now += timedelta(hours=6)
    year = engine.d["year"]
    assert year["prev_total"] == pytest.approx(8760.0)
    assert year["prev"][1] == pytest.approx(31 * 24.0)
    snap = engine.snapshot(now, priced=False, subscription=None)
    assert snap["year"]["previous_to_date"] == pytest.approx(59 * 24.0)
    assert snap["year"]["gap"] == pytest.approx(0.0, abs=0.1)
    assert snap["periods"]["year"]["kwh_estimate"] == pytest.approx(8760.0, rel=0.001)


def test_heating() -> None:
    engine = Engine()
    engine.set_season_month(10)
    engine.d["heating"]["fit"] = {"base": 0.2, "slope": 2.0, "r2": 0.9, "n": 100}
    now = at(2026, 11, 1, 0, 0)
    engine.roll(now)
    for _ in range(10 * 24):
        now += timedelta(hours=1)
        engine.add_degree_time(8.0, 18.0, 3600, now)
        engine.add_heating_energy(1.0, now)
    heating = engine.snapshot(now, priced=False, subscription=None)["heating"]
    assert heating["month"]["hdd"] == pytest.approx(100.0)
    assert heating["month"]["expected"] == pytest.approx(0.2 * 10 + 200.0)
    assert heating["month"]["gap"] == pytest.approx((240 / 202 - 1) * 100, abs=0.1)
    assert heating["season"]["start"].startswith("2026-10-01")


def test_backfill() -> None:
    now = at(2026, 11, 11, 10, 30)
    start = at(2025, 11, 1, 0, 0)
    hourly = {}
    ts = start.timestamp()
    while ts < now.timestamp() - 1800:
        hourly[int(ts)] = 1.0
        ts += 3600
    hourly[int(at(2026, 11, 11, 10).timestamp())] = 0.5  # the hour in progress
    monthly = {}
    month = at(2024, 12, 1)
    while month < now:
        monthly[int(month.timestamp())] = days_in_month(month) * 24.0
        month = end_of("month", month)
    engine = Engine()
    engine.backfill(hourly, monthly, now, [0.2] * 24, 36)
    snap = engine.snapshot(now, priced=True, subscription=None)
    periods = snap["periods"]
    assert periods["day"]["kwh"] == pytest.approx(10.5)
    assert periods["day"]["cost"] == pytest.approx(2.1)
    assert periods["week"]["kwh"] == pytest.approx(2 * 24 + 10.5)
    assert periods["month"]["kwh_previous"] == pytest.approx(31 * 24.0 + 1)  # 25-hour day
    assert len(engine.d["history"]["month"]) == 12 and len(engine.d["history"]["day"]) == 7
    assert periods["year"]["kwh"] == pytest.approx((304 + 10) * 24 + 10.5, abs=1.5)
    assert engine.d["year"]["prev_total"] == pytest.approx(8760.0)
    assert snap["year"]["gap"] == pytest.approx(0.0, abs=0.2)


def test_build_days() -> None:
    hourly, temps = {}, {}
    base = at(2026, 11, 9, 0, 0).timestamp()
    for i in range(48):
        hourly[int(base + i * 3600)] = 1.0
        temps[int(base + i * 3600)] = (5.0 + i % 24 * 0.1, 6.0 + i % 24 * 0.1)
    days = build_days(hourly, temps, TZ, {"2026-11-08": {"h": [2.0] * 24, "tmin": 1, "tmax": 9}},
                      at(2026, 11, 10, 12).date())
    assert [d["date"] for d in days] == ["2026-11-08", "2026-11-09"]
    assert days[0]["t"] == 5.0 and days[1]["t"] == pytest.approx((5.0 + 8.3) / 2)


def test_cost_backfill_after_adding_a_price() -> None:
    import json

    engine = Engine()
    now = run(engine, at(2026, 3, 2, 0, 0), 60, 1.0, None)  # no price yet
    engine = Engine(json.loads(json.dumps(engine.d)))  # as after a restart
    hourly = {int((at(2026, 3, 2, 0, 0) + timedelta(hours=i)).timestamp()): 1.0 for i in range(60)}
    engine.backfill(hourly, {}, now, [0.25] * 24, 36, cost_only=True)
    snap = engine.snapshot(now, priced=True, subscription=None)
    assert snap["periods"]["day"]["cost"] == pytest.approx(12 * 0.25)
    assert snap["periods"]["day"]["cost_previous"] == pytest.approx(24 * 0.25)
    assert snap["periods"]["day"]["kwh"] == pytest.approx(12.0)  # kWh untouched


# -------------------------------------------------------- delayed sources
def daily(start: datetime, count: int, kwh: float, price: float | None = 0.2) -> dict:
    return {
        (start.date() + timedelta(days=i)).isoformat(): {
            "kwh": kwh, "cost": None if price is None else kwh * price}
        for i in range(count)
    }


def test_delayed_periods_from_daily_totals() -> None:
    engine = Engine()
    now = at(2026, 11, 11, 10, 0)  # Wednesday; data received up to Monday 9th
    engine.set_delayed_days(daily(at(2025, 12, 1), 344, 30.0), now)
    snap = engine.snapshot(now, priced=True, subscription=None)
    assert snap["delayed"] and snap["data_until"] == "2026-11-09"
    periods = snap["periods"]
    assert periods["day"]["kwh"] == 30.0 and periods["day"]["kwh_previous"] == 30.0
    assert periods["day"]["start"].startswith("2026-11-09")
    assert periods["week"]["kwh"] == 30.0  # only Monday so far
    assert periods["month"]["kwh"] == 9 * 30.0
    assert periods["month"]["kwh_previous"] == 31 * 30.0
    # Tuesday and today are not received yet: they are part of what is still to come.
    assert periods["week"]["kwh_estimate"] == pytest.approx(7 * 30.0)
    assert periods["month"]["kwh_estimate"] == pytest.approx(30 * 30.0)
    assert periods["month"]["cost_estimate"] == pytest.approx(30 * 30.0 * 0.2)
    assert periods["day"]["kwh_estimate"] == 30.0
    assert snap["method"] == "average"


def test_delayed_uses_model_for_missing_and_future_days() -> None:
    engine = Engine()
    engine.d["model"] = mdl.learn(synthetic_days(), None, 36)
    now = at(2026, 3, 4, 9, 0)  # Wednesday; last day received: Monday
    engine.set_delayed_days(daily(at(2026, 2, 1), 30, 20.0), now)
    engine.set_forecast(
        [{"date": (now.date() + timedelta(days=k)).isoformat(), "t": 5.0} for k in range(6)], now
    )
    engine.d["day_log"]["2026-03-03"] = {"h": [0.0] * 24, "tmin": 3.0, "tmax": 7.0}  # yesterday, observed
    snap = engine.snapshot(now, priced=False, subscription=None)
    expected = mdl.expected(engine.d["model"], 5.0, "kwh")
    assert snap["method"] == "model"
    # Monday received (20) + Tuesday..Sunday from the model (6 days at 5 °C).
    assert snap["periods"]["week"]["kwh_estimate"] == pytest.approx(20.0 + 6 * expected)


def test_delayed_year_comparison_stops_at_last_day_received() -> None:
    engine = Engine()
    now = at(2026, 3, 11, 9, 0)
    engine.set_delayed_days(daily(at(2025, 1, 1), 365 + 59 + 8, 24.0), now)  # up to 8 March
    snap = engine.snapshot(now, priced=False, subscription=None)
    assert snap["data_until"] == "2026-03-08"
    assert snap["year"]["previous_total"] == pytest.approx(8760.0)
    assert snap["year"]["previous_to_date"] == pytest.approx((59 + 8) * 24.0, abs=0.5)  # 743-hour March
    assert snap["year"]["gap"] == pytest.approx(0.0, abs=0.1)


def test_delayed_standing_charge_follows_the_data() -> None:
    engine = Engine()
    now = at(2026, 11, 11, 18, 0)  # data up to the 9th
    engine.set_delayed_days(daily(at(2026, 10, 1), 40, 10.0), now)
    snap = engine.snapshot(now, priced=True, subscription=30.0)  # 1 per day in November
    periods = snap["periods"]
    assert periods["day"]["cost"] == pytest.approx(10 * 0.2 + 1.0)  # a finished day: its whole share
    assert periods["day"]["cost"] == pytest.approx(periods["day"]["cost_estimate"])
    assert periods["month"]["cost"] == pytest.approx(9 * 10 * 0.2 + 9.0)  # 9 days received


def test_delayed_with_a_single_day_known() -> None:
    engine = Engine()
    now = at(2026, 11, 11, 9, 0)  # Wednesday
    engine.set_delayed_days({"2026-11-10": {"kwh": 30.0, "cost": None}}, now)
    snap = engine.snapshot(now, priced=False, subscription=None)
    # Tuesday received; Wednesday to Sunday assumed alike.
    assert snap["periods"]["week"]["kwh_estimate"] == pytest.approx(30.0 * 6)
