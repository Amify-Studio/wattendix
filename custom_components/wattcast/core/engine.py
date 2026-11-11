"""Wattcast engine: period counters, estimates, year comparison, heating.

Pure Python, no Home Assistant import. ``Engine.d`` is a JSON-serialisable
dict that the integration persists as is.

Estimate of a period = energy so far + energy expected until its end
(+ the subscription of the whole period for costs):
- hour : pace of the previous hour;
- day  : expected day (temperature model) x share of the day still to come
         (hourly profile), corrected by the pace observed since midnight;
- week / month : rest of today + expected value of each remaining day
         (model while the forecast lasts, mean of the last 7 days beyond);
- year : same months as last year when known, else mean of the last months.

Delayed sources (a daily reading, statistics imported the next day) have no
live counter: periods are rebuilt from one total per day, "day" is the last
day received, and estimates add the expected value of every day not received
yet, today included.
"""

from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime, timedelta
from typing import Any

from . import model as mdl
from .periods import (
    PERIODS,
    days_in_month,
    end_of,
    fraction,
    previous_start,
    season_start,
    start_of,
)

HISTORY_SIZE = {"hour": 7, "day": 7, "week": 4, "month": 12, "year": 3}
DAY_LOG_DAYS = 400
DELAYED_DAYS = 800
BIAS_DAYS = 14
FORECAST_MAX_AGE = 36 * 3600
LIVE_BIAS_SAMPLES = 1440  # one sample a minute: about a day
LIVE_BIAS_MIN = 30
MIN_HDD = 15.0  # below this, heating ratios mean nothing
HEATING_PERIODS = ("day", "month", "season")

METHOD_MODEL = "model"
METHOD_AVERAGE = "average"
METHOD_PACE = "pace"


def new_state() -> dict[str, Any]:
    return {
        "version": 1,
        "periods": {},
        "previous": {},
        "history": {p: [] for p in PERIODS},
        "year": {"year": None, "cum": [], "prev": None, "prev_total": None, "partial": False},
        "subscription": None,
        "price": None,
        "day_log": {},
        "forecast": {"days": [], "ts": None},
        "model": None,
        "heating": {"periods": {}, "fit": None},
        "backfilled": False,
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def remaining_today(
    done: float,
    expected: float | None,
    profile: list[float] | None,
    hour: float,
    fallback: float | None,
) -> tuple[float, str]:
    """Energy still expected before midnight, and the method used."""
    hour = min(max(hour, 0.0), 24.0)
    if expected is not None and expected > 0 and profile and len(profile) == 25:
        i = min(int(hour), 23)
        share = profile[i] + (profile[i + 1] - profile[i]) * (hour - i)
        ratio = 1.0
        if share >= 0.01:
            ratio = max(0.5, min(2.0, done / (expected * share)))
        # The later in the day, the more the observed pace is trusted.
        return expected * (1 - share) * ((1 - share) + share * ratio), METHOD_MODEL
    if fallback is not None:
        return max(fallback, 0.0) * (24 - hour) / 24, METHOD_AVERAGE
    if hour >= 0.5:
        return done / hour * (24 - hour), METHOD_PACE
    return 0.0, METHOD_PACE


class Engine:
    """All the state and the arithmetic of one Wattcast entry."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.d = new_state()
        if data:
            self.d.update(data)
        for period in PERIODS:
            self.d["history"].setdefault(period, [])

    # ------------------------------------------------------------ rollover
    def roll(self, now: datetime) -> None:
        """Close the periods that ended and open the current ones."""
        d = self.d
        if d.get("delayed") is not None:
            self._rebuild_delayed(now)
            self._roll_heating(now)
            self._trim_log(now)
            return
        for period in PERIODS:
            start = start_of(period, now)
            key = start.isoformat()
            current = d["periods"].get(period)
            if current is None:
                d["periods"][period] = {"start": key, "kwh": 0.0, "cost": 0.0, "u": 0.0}
                continue
            if current["start"] == key:
                continue
            closed = {
                "start": current["start"],
                "kwh": round(current["kwh"], 4),
                "cost": None
                if current.get("u", 0) > 0.01 * max(current["kwh"], 1e-9)
                else round(current["cost"], 4),
            }
            if previous_start(period, start).isoformat() == current["start"]:
                d["previous"][period] = closed
                d["history"][period] = (d["history"][period] + [closed])[-HISTORY_SIZE[period] :]
            else:
                d["previous"][period] = None  # a gap: the last known period is not "the previous"
            d["periods"][period] = {"start": key, "kwh": 0.0, "cost": 0.0, "u": 0.0}
        self._roll_year(now)
        self._roll_heating(now)
        self._trim_log(now)

    # ----------------------------------------------------- delayed sources
    def set_delayed_days(self, days: dict[str, dict[str, Any]], now: datetime) -> None:
        """Replace the daily totals: {"YYYY-MM-DD": {"kwh": x, "cost": y or None}}."""
        self.d["delayed"] = {"days": dict(sorted(days.items())[-DELAYED_DAYS:])}
        self.roll(now)

    def _delayed_last(self) -> date | None:
        days = (self.d.get("delayed") or {}).get("days") or {}
        return date.fromisoformat(max(days)) if days else None

    def _reference(self, now: datetime) -> datetime:
        """Instant up to which consumption is known: now, or the end of the last day received."""
        if self.d.get("delayed") is None:
            return now
        last = self._delayed_last()
        if last is None:
            return start_of("year", now)
        after = last + timedelta(days=1)
        return min(now, datetime(after.year, after.month, after.day, tzinfo=now.tzinfo))

    def _rebuild_delayed(self, now: datetime) -> None:
        """Periods, previous periods and histories from the daily totals."""
        d = self.d
        days = d["delayed"]["days"]
        tz = now.tzinfo
        known = sorted(days)
        first = date.fromisoformat(known[0]) if known else None
        last = date.fromisoformat(known[-1]) if known else None
        one = timedelta(days=1)

        def midnight(day: date) -> datetime:
            return datetime(day.year, day.month, day.day, tzinfo=tz)

        def total(begin: date, end: date) -> tuple[float, float | None, int]:
            kwh, cost, priced, count = 0.0, 0.0, True, 0
            cursor = begin
            while cursor < end:
                entry = days.get(cursor.isoformat())
                if entry:
                    kwh += entry["kwh"]
                    count += 1
                    if entry.get("cost") is None:
                        priced = False
                    else:
                        cost += entry["cost"]
                cursor += one
            return kwh, (cost if priced else None), count

        def current(start: datetime, kwh: float, cost: float | None) -> dict[str, Any]:
            return {
                "start": start.isoformat(),
                "kwh": round(kwh, 4),
                "cost": 0.0 if cost is None else round(cost, 4),
                "u": kwh if cost is None else 0.0,
            }

        def closed(start: datetime, kwh: float, cost: float | None) -> dict[str, Any]:
            return {
                "start": start.isoformat(),
                "kwh": round(kwh, 4),
                "cost": None if cost is None else round(cost, 4),
            }

        periods: dict[str, Any] = {"hour": current(start_of("hour", now), 0.0, 0.0)}
        previous: dict[str, Any] = {"hour": None}
        history: dict[str, list[dict[str, Any]]] = {"hour": []}

        # "Day" is the last day received.
        entries: list[dict[str, Any]] = []
        if last is not None:
            kwh, cost, _ = total(last, last + one)
            periods["day"] = current(midnight(last), kwh, cost)
            cursor = last
            for _ in range(HISTORY_SIZE["day"]):
                cursor -= one
                entry = days.get(cursor.isoformat())
                if not entry:
                    break
                entries.insert(0, closed(midnight(cursor), entry["kwh"], entry.get("cost")))
        else:
            periods["day"] = current(start_of("day", now), 0.0, 0.0)
        history["day"] = entries
        previous["day"] = entries[-1] if entries else None

        for period in ("week", "month", "year"):
            start = start_of(period, now)
            kwh, cost, _ = total(start.date(), now.date() + one)
            periods[period] = current(start, kwh, cost)
            entries = []
            cursor = start
            for _ in range(HISTORY_SIZE[period]):
                end = cursor
                cursor = previous_start(period, cursor)
                if first is None or first > cursor.date():
                    break
                kwh, cost, count = total(cursor.date(), end.date())
                if count < 0.9 * (end.date() - cursor.date()).days:
                    break
                entries.insert(0, closed(cursor, kwh, cost))
            history[period] = entries
            previous[period] = entries[-1] if entries else None
        d["periods"], d["previous"], d["history"] = periods, previous, history

        # Year profiles: cumulative kWh at the start of each month.
        january = start_of("year", now)
        complete = first is not None and first <= january.date()
        cum: list[float | None] = [0.0 if complete else None]
        for month in range(1, now.month):
            if not complete:
                cum.append(None)
                continue
            begin = january.replace(month=month)
            cum.append(round(cum[-1] + total(begin.date(), end_of("month", begin).date())[0], 3))  # type: ignore[operator]
        year = d["year"]
        year.update(year=now.year, cum=cum, partial=not complete)
        last_january = january.replace(year=now.year - 1)
        if first is not None and first <= last_january.date():
            profile = [0.0]
            for month in range(1, 13):
                begin = last_january.replace(month=month)
                profile.append(round(profile[-1] + total(begin.date(), end_of("month", begin).date())[0], 3))
            year.update(prev=profile, prev_total=profile[-1])
        elif year.get("manual") is None:
            year.update(prev=None, prev_total=None)

    def _roll_year(self, now: datetime) -> None:
        year = self.d["year"]
        if year["year"] != now.year:
            previous = self.d["previous"].get("year")
            if year["year"] == now.year - 1 and previous and not year.get("partial"):
                cum = year["cum"]
                complete = len(cum) == 12 and None not in cum
                year["prev"] = [*cum, previous["kwh"]] if complete else None
                year["prev_total"] = previous["kwh"]
            elif year["year"] is not None:
                year["prev"], year["prev_total"] = None, None
            first_run = year["year"] is None
            year["year"] = now.year
            year["partial"] = first_run and (now.month, now.day) != (1, 1)
            year["cum"] = [0.0] if not year["partial"] else [None] * (now.month - 1)
        total = round(self.d["periods"]["year"]["kwh"], 3)
        while len(year["cum"]) < now.month:
            year["cum"].append(total)

    def _roll_heating(self, now: datetime) -> None:
        heating = self.d["heating"]
        month = heating.get("season_month")
        for period in HEATING_PERIODS:
            if period == "season":
                if not month:
                    continue
                start = season_start(now, month)
            else:
                start = start_of(period, now)
            key = start.isoformat()
            current = heating["periods"].get(period)
            if current is None or current["start"] != key:
                if current is not None and period == "day":
                    entry = self.d["day_log"].get(current["start"][:10])
                    if entry is not None:
                        entry["hk"] = round(current["kwh"], 3)
                        entry["hd"] = round(current["hdd"], 3)
                heating["periods"][period] = {"start": key, "kwh": 0.0, "hdd": 0.0}

    def _trim_log(self, now: datetime) -> None:
        log = self.d["day_log"]
        if len(log) > DAY_LOG_DAYS + 5:
            limit = (now.date() - timedelta(days=DAY_LOG_DAYS)).isoformat()
            for key in [k for k in log if k < limit]:
                del log[key]

    def _today(self, now: datetime) -> dict[str, Any]:
        return self.d["day_log"].setdefault(now.date().isoformat(), {"h": [0.0] * 24})

    # ------------------------------------------------------------- inputs
    def add_energy(self, kwh: float, now: datetime, price: float | None) -> None:
        """Count ``kwh`` consumed now, priced at ``price`` (None: no price)."""
        self.roll(now)
        if kwh <= 0:
            return
        for period in PERIODS:
            current = self.d["periods"][period]
            current["kwh"] += kwh
            if price is None:
                current["u"] = current.get("u", 0.0) + kwh
            else:
                current["cost"] += kwh * price
        hours = self._today(now)["h"]
        hours[now.hour] = round(hours[now.hour] + kwh, 5)

    def add_heating_energy(self, kwh: float, now: datetime) -> None:
        self.roll(now)
        if kwh > 0:
            for current in self.d["heating"]["periods"].values():
                current["kwh"] += kwh

    def add_degree_time(self, temp: float, base: float, seconds: float, now: datetime) -> None:
        """Integrate the heating degree-days: (base - temp) over ``seconds``."""
        self.roll(now)
        gain = max(0.0, base - temp) * seconds / 86400
        if gain > 0:
            for current in self.d["heating"]["periods"].values():
                current["hdd"] += gain

    def sample_temperature(self, temp: float, now: datetime) -> None:
        """Track the day's observed minimum and maximum."""
        self.roll(now)
        today = self._today(now)
        today["tmin"] = temp if today.get("tmin") is None else min(today["tmin"], temp)
        today["tmax"] = temp if today.get("tmax") is None else max(today["tmax"], temp)

    def set_forecast(self, days: list[dict[str, Any]], now: datetime) -> None:
        """``days``: [{"date": "YYYY-MM-DD", "t": mean temperature}]."""
        self.roll(now)
        if not days:
            return
        self.d["forecast"] = {"days": days, "ts": now.timestamp()}
        today = self._today(now)
        if today.get("tf") is None:  # keep the first forecast of the day, made before the fact
            for day in days:
                if day["date"] == now.date().isoformat():
                    today["tf"] = day["t"]

    def sample_weather_offset(self, sensor_temp: float, weather_temp: float) -> None:
        """Running mean of (thermometer - weather service), over about a day of samples.

        Used as the temperature bias until whole days allow measuring it directly.
        """
        live = self.d.setdefault("bias_live", {"mean": 0.0, "n": 0})
        live["n"] = min(live["n"] + 1, LIVE_BIAS_SAMPLES)
        live["mean"] += (sensor_temp - weather_temp - live["mean"]) / live["n"]

    def set_season_month(self, month: int | None) -> None:
        self.d["heating"]["season_month"] = month

    # ------------------------------------------------------- temperatures
    def temperature_bias(self, now: datetime) -> tuple[float, int]:
        """Mean (observed - forecast) daily temperature over the last logged days."""
        today = now.date().isoformat()
        gaps = [
            (e["tmin"] + e["tmax"]) / 2 - e["tf"]
            for key, e in sorted(self.d["day_log"].items())
            if key < today
            and e.get("tf") is not None
            and e.get("tmin") is not None
            and e.get("tmax") is not None
        ][-BIAS_DAYS:]
        if gaps:
            return sum(gaps) / len(gaps), len(gaps)
        live = self.d.get("bias_live") or {}
        if live.get("n", 0) >= LIVE_BIAS_MIN:
            return live["mean"], 0
        return 0.0, 0

    def _temperatures(self, now: datetime) -> tuple[dict[str, float], str | None, float, int]:
        """Expected mean temperature per date, its source for today, the bias."""
        bias, bias_days = self.temperature_bias(now)
        forecast = self.d["forecast"]
        temps: dict[str, float] = {}
        if forecast.get("ts") and now.timestamp() - forecast["ts"] <= FORECAST_MAX_AGE:
            temps = {day["date"]: day["t"] + bias for day in forecast["days"]}
        today = now.date().isoformat()
        source = "forecast" if today in temps else None
        if source is None:
            # No forecast: assume today resembles yesterday.
            entry = self.d["day_log"].get((now.date() - timedelta(days=1)).isoformat(), {})
            if entry.get("tmin") is not None and entry.get("tmax") is not None:
                temps[today] = (entry["tmin"] + entry["tmax"]) / 2
                source = "yesterday"
        return temps, source, bias, bias_days

    # ----------------------------------------------------------- snapshot
    def snapshot(
        self,
        now: datetime,
        *,
        priced: bool,
        subscription: float | None,
    ) -> dict[str, Any]:
        """Everything the entities and the card display."""
        self.roll(now)
        d = self.d
        model = d["model"]
        sub_month = (subscription or 0.0) if priced else 0.0
        dim = days_in_month(now)
        sub_day = sub_month / dim
        month_fraction = fraction("month", now)
        sub_period = {
            "hour": sub_day / 24,
            "day": sub_day,
            "week": sub_day * 7,
            "month": sub_month,
            "year": sub_month * 12,
        }
        # Standing charge already due: up to now, or up to the last day received.
        reference = self._reference(now)

        def elapsed(period: str) -> float:
            return fraction(period, reference) if reference >= start_of(period, now) else 0.0

        in_year = reference.year == now.year
        sub_elapsed = {
            "hour": sub_day / 24 * elapsed("hour"),
            "day": sub_day * (1.0 if d.get("delayed") is not None else elapsed("day")),
            "week": sub_day * 7 * elapsed("week"),
            "month": sub_month * elapsed("month"),
            "year": sub_month * (reference.month - 1 + fraction("month", reference)) if in_year else 0.0,
        }

        temps, temp_source, bias, bias_days = self._temperatures(now)
        delayed = d.get("delayed") is not None
        last_received = self._delayed_last()
        first_missing = (last_received + timedelta(days=1)) if last_received else now.date()
        today = now.date()
        t_today = temps.get(today.isoformat())
        hour = now.hour + now.minute / 60 + now.second / 3600
        hour_fraction = fraction("hour", now)
        days_left_week = 6 - now.weekday()
        days_left_month = dim - now.day
        year_end = end_of("year", now)
        months_left = (year_end.timestamp() - now.timestamp()) / 86400 / 30.44

        # Effective price of the recent days: turns kWh into cost when the
        # model has no cost table (price given by an entity).
        recent = [h for h in d["history"]["day"] if h.get("cost") is not None and h["kwh"] > 0]
        effective_price = (
            sum(h["cost"] for h in recent) / sum(h["kwh"] for h in recent) if recent else d["price"]
        )

        out_periods: dict[str, dict[str, Any]] = {p: {"start": d["periods"][p]["start"]} for p in PERIODS}
        methods: dict[str, str] = {}
        expected_today: dict[str, float | None] = {}
        for q in ("kwh", "cost") if priced else ("kwh",):

            def expect(temp: float | None, q: str = q) -> float | None:
                value = mdl.expected(model, temp, q)
                if value is None and q == "cost" and effective_price is not None:
                    kwh = mdl.expected(model, temp, "kwh")
                    value = None if kwh is None else kwh * effective_price
                return value

            done = {p: d["periods"][p][q] for p in PERIODS}
            history = {
                p: [h[q] for h in d["history"][p] if h.get(q) is not None] for p in PERIODS
            }
            average_day = _mean(history["day"])
            expected_today[q] = expect(t_today)
            remaining, method = remaining_today(
                done["day"], expected_today[q], mdl.profile(model, t_today, q), hour, average_day
            )
            methods[q] = method
            fallback_day = average_day if average_day is not None else done["day"] + remaining

            def day_value(offset: int) -> float:
                value = expect(temps.get((today + timedelta(days=offset)).isoformat()))
                return fallback_day if value is None else value

            estimate: dict[str, float] = {}
            previous_hour = (d["previous"].get("hour") or {}).get(q)
            if previous_hour is None:
                previous_hour = done["hour"] / hour_fraction if hour_fraction > 0.1 else done["hour"]
            estimate["hour"] = done["hour"] + previous_hour * (1 - hour_fraction)
            estimate["day"] = done["day"] + remaining
            estimate["week"] = done["week"] + remaining + sum(
                day_value(k) for k in range(1, days_left_week + 1)
            )
            estimate["month"] = done["month"] + remaining + sum(
                day_value(k) for k in range(1, days_left_month + 1)
            )
            year = self._year_comparison(now)
            average_month = _mean(history["month"])
            if q == "kwh" and year.get("previous_total") is not None:
                estimate["year"] = done["year"] + year["previous_total"] - year["previous_to_date"]
            elif average_month is not None:
                estimate["year"] = done["year"] + average_month * months_left
            else:
                days_after_today = (year_end.date() - today).days - 1
                estimate["year"] = done["year"] + remaining + fallback_day * days_after_today

            if delayed:
                # No live counter: every day after the last one received is still to come.
                def value_on(day: date, q: str = q) -> float:
                    key = day.isoformat()
                    temp = temps.get(key)
                    if temp is None:
                        seen = d["day_log"].get(key, {})
                        if seen.get("tmin") is not None and seen.get("tmax") is not None:
                            temp = (seen["tmin"] + seen["tmax"]) / 2
                    value = expect(temp)
                    if value is not None:
                        return value
                    # No model: the mean of the last days, or the only day known.
                    return average_day if average_day is not None else done["day"]

                def tail(period: str) -> float:
                    cursor = max(first_missing, start_of(period, now).date())
                    end = end_of(period, now).date()
                    amount = 0.0
                    while cursor < end:
                        amount += value_on(cursor)
                        cursor += timedelta(days=1)
                    return amount

                estimate["hour"] = 0.0
                estimate["day"] = done["day"]
                estimate["week"] = done["week"] + tail("week")
                estimate["month"] = done["month"] + tail("month")
                if not (q == "kwh" and year.get("previous_total") is not None):
                    estimate["year"] = done["year"] + tail("year")
                if expected_today[q] is not None:
                    methods[q] = METHOD_MODEL
                else:
                    methods[q] = METHOD_AVERAGE if average_day is not None else METHOD_PACE

            for period in PERIODS:
                out = out_periods[period]
                previous = (d["previous"].get(period) or {}).get(q)
                average = _mean(history[period])
                trend = None
                if previous is not None and previous > 0.001:
                    trend = round((estimate[period] - previous) / previous * 100, 1)
                if q == "kwh":
                    out.update(
                        kwh=done[period],
                        kwh_estimate=estimate[period],
                        kwh_previous=previous,
                        kwh_average=average,
                        kwh_trend=trend,
                    )
                else:
                    out.update(
                        cost=done[period] + sub_elapsed[period],
                        cost_energy=done[period],
                        cost_estimate=estimate[period] + sub_period[period],
                        cost_previous=None if previous is None else previous + sub_period[period],
                        cost_average=None if average is None else average + sub_period[period],
                        cost_trend=trend,
                        subscription=sub_period[period],
                    )

        reason = None
        if methods["kwh"] != METHOD_MODEL:
            if not model or not model.get("ready"):
                reason = "learning"
            elif t_today is None:
                reason = "no_temperature"
            else:
                reason = "out_of_range"
        return {
            "periods": out_periods,
            "method": methods["kwh"],
            "reason": reason,
            "model_days": (model or {}).get("days", 0),
            "model_bins": [
                {k: b[k] for k in ("t", "n", "kwh", "cost") if k in b}
                for b in (model or {}).get("bins", [])
            ],
            "temperature_today": None if t_today is None else round(t_today, 1),
            "temperature_source": temp_source,
            "temperature_bias": round(bias, 2),
            "temperature_bias_days": bias_days,
            "forecast_days": len(temps),
            "expected_today": expected_today,
            "subscription_month": sub_month if priced and subscription else None,
            "subscription_day": sub_day if priced and subscription else None,
            "year": self._year_comparison(now),
            "heating": self._heating(now),
            "delayed": delayed,
            "data_until": last_received.isoformat() if delayed and last_received else None,
        }

    def _year_comparison(self, now: datetime) -> dict[str, Any]:
        """Last year's consumption at the same point of the year."""
        year = self.d["year"]
        total = year.get("prev_total")
        if total is None:
            return {"previous_total": None, "previous_to_date": None, "gap": None}
        profile = year.get("prev")
        reference = self._reference(now)
        if reference.year != now.year:
            reference = start_of("year", now)
        part = fraction("month", reference)
        month = reference.month
        if profile and len(profile) == 13:
            to_date = profile[month - 1] + (profile[month] - profile[month - 1]) * part
        else:
            to_date = total * (month - 1 + part) / 12
        done = self.d["periods"]["year"]["kwh"]
        gap = round((done - to_date) / to_date * 100, 1) if to_date > 1 else None
        return {"previous_total": total, "previous_to_date": to_date, "gap": gap}

    def _heating(self, now: datetime) -> dict[str, Any]:
        heating = self.d["heating"]
        fit = heating.get("fit")
        out: dict[str, Any] = {"fit": fit}
        for period, current in heating["periods"].items():
            start = datetime.fromisoformat(current["start"])
            days = max(0.0, (now.timestamp() - start.timestamp()) / 86400)
            block: dict[str, Any] = {
                "start": current["start"],
                "kwh": current["kwh"],
                "hdd": current["hdd"],
                "expected": None,
                "gap": None,
                "per_hdd": None,
            }
            if fit:
                block["expected"] = max(0.0, fit["base"] * days + fit["slope"] * current["hdd"])
            if current["hdd"] >= MIN_HDD:
                block["per_hdd"] = round(current["kwh"] / current["hdd"], 2)
                if block["expected"]:
                    block["gap"] = round((current["kwh"] / block["expected"] - 1) * 100, 1)
            out[period] = block
        return out

    # ----------------------------------------------------------- backfill
    def backfill(
        self,
        hourly: dict[int, float],
        monthly: dict[int, float],
        now: datetime,
        hour_prices: list[float] | None,
        max_kwh: float,
        cost_only: bool = False,
    ) -> None:
        """Seed counters and histories from recorded statistics.

        ``hourly`` / ``monthly``: kWh by period start (epoch seconds). Costs are
        the kWh of each period times the mean price of its recorded hours at
        today's rates. With ``cost_only``, only missing costs are filled.
        """
        self.roll(now)
        d = self.d
        tz = now.tzinfo
        rows = sorted((ts, v) for ts, v in hourly.items() if v is not None and 0 <= v <= max_kwh)
        stamps = [r[0] for r in rows]
        first = stamps[0] if stamps else None
        # Running totals, so that any time span is two lookups.
        cum_kwh, cum_cost = [0.0], [0.0]
        for ts, value in rows:
            cum_kwh.append(cum_kwh[-1] + value)
            price = hour_prices[datetime.fromtimestamp(ts, tz).hour] if hour_prices else 0.0
            cum_cost.append(cum_cost[-1] + value * price)

        def span(start: datetime, end: datetime) -> tuple[float, float | None, int]:
            lo = bisect_left(stamps, start.timestamp())
            hi = bisect_left(stamps, end.timestamp())
            cost = cum_cost[hi] - cum_cost[lo] if hour_prices else None
            return cum_kwh[hi] - cum_kwh[lo], cost, hi - lo

        def price_ratio(start: datetime, end: datetime) -> float | None:
            kwh, cost, _ = span(start, end)
            return cost / kwh if cost is not None and kwh > 0 else None

        def covered(start: datetime, end: datetime) -> float | None:
            """kWh of a fully recorded period, else None."""
            if first is None or first > start.timestamp():
                return None
            kwh, _, count = span(start, end)
            hours = (end.timestamp() - start.timestamp()) / 3600
            return kwh if count >= 0.9 * hours else None

        months = {
            (m.year, m.month): v
            for m, v in ((datetime.fromtimestamp(ts, tz), v) for ts, v in sorted(monthly.items()))
            if v is not None and v >= 0
        }
        if months:
            months.pop(min(months))  # the first recorded month is probably incomplete

        def month_kwh(start: datetime) -> float | None:
            value = covered(start, end_of("month", start))
            return months.get((start.year, start.month)) if value is None else value

        if cost_only:
            if not hour_prices:
                return
            for period in PERIODS:
                current = d["periods"][period]
                start = datetime.fromisoformat(current["start"])
                if current.get("u", 0) > 0:
                    ratio = price_ratio(start, now)
                    if ratio is not None:
                        current["cost"] += current["u"] * ratio
                        current["u"] = 0.0
                # After a reload "previous" is a copy of the last history entry: fill both.
                for entry in [*d["history"][period], d["previous"].get(period) or {}]:
                    if entry.get("cost") is None and entry.get("start"):
                        begin = datetime.fromisoformat(entry["start"])
                        ratio = price_ratio(begin, end_of(period, begin))
                        if ratio is not None:
                            entry["cost"] = round(entry["kwh"] * ratio, 4)
            return

        def entry_for(period: str, start: datetime) -> dict[str, Any] | None:
            end = end_of(period, start)
            if period == "month":
                kwh = month_kwh(start)
            elif period == "year":
                parts = [month_kwh(start.replace(month=m)) for m in range(1, 13)]
                kwh = None if None in parts else sum(parts)  # type: ignore[arg-type]
            else:
                kwh = covered(start, end)
            if kwh is None:
                return None
            ratio = price_ratio(start, end)
            return {
                "start": start.isoformat(),
                "kwh": round(kwh, 4),
                "cost": None if ratio is None else round(kwh * ratio, 4),
            }

        for period in PERIODS:
            start = start_of(period, now)
            current = d["periods"][period]
            if period == "year":
                done = [month_kwh(start.replace(month=m)) for m in range(1, now.month)]
                to_date = span(start_of("month", now), now)[0]
                kwh = sum(v for v in done if v is not None) + to_date
            else:
                kwh = span(start, now)[0]
            ratio = price_ratio(start, now)
            current["kwh"] += kwh
            if ratio is None:
                current["u"] = current.get("u", 0.0) + kwh
            else:
                current["cost"] += kwh * ratio
            entries: list[dict[str, Any]] = []
            cursor = start
            for _ in range(HISTORY_SIZE[period]):
                cursor = previous_start(period, cursor)
                entry = entry_for(period, cursor)
                if entry is None:
                    break
                entries.insert(0, entry)
            if entries:
                d["history"][period] = entries
                d["previous"][period] = entries[-1]

        # Year profile: cumulative kWh at the start of each month.
        year = d["year"]
        january = start_of("year", now)
        cum: list[float | None] = [0.0]
        for month in range(1, now.month):
            value = month_kwh(january.replace(month=month))
            cum.append(None if value is None or cum[-1] is None else round(cum[-1] + value, 3))
        year.update(year=now.year, cum=cum, partial=None in cum)
        last = [month_kwh(january.replace(year=now.year - 1, month=m)) for m in range(1, 13)]
        if None not in last:
            profile = [0.0]
            for value in last:
                profile.append(round(profile[-1] + value, 3))  # type: ignore[operator]
            year.update(prev=profile, prev_total=profile[-1])
        d["backfilled"] = True


def build_days(
    hourly_kwh: dict[int, float],
    hourly_temp: dict[int, tuple[float, float]],
    tz: Any,
    day_log: dict[str, Any],
    today: date,
) -> list[dict[str, Any]]:
    """Days for the model: recorded statistics first, the engine's own log for the rest."""
    days: dict[str, dict[str, Any]] = {}
    for ts, value in hourly_kwh.items():
        local = datetime.fromtimestamp(ts, tz)
        day = days.setdefault(local.date().isoformat(), {"h": [None] * 24})
        if value is not None:
            day["h"][local.hour] = (day["h"][local.hour] or 0.0) + value
    extremes: dict[str, list[float]] = {}
    for ts, (low, high) in hourly_temp.items():
        key = datetime.fromtimestamp(ts, tz).date().isoformat()
        entry = extremes.setdefault(key, [low, high, 0])
        entry[0], entry[1], entry[2] = min(entry[0], low), max(entry[1], high), entry[2] + 1
    for key, (low, high, count) in extremes.items():
        if count >= 20 and key in days:
            days[key]["t"] = (low + high) / 2
    for key, entry in day_log.items():
        day = days.setdefault(key, {"h": list(entry.get("h") or [])})
        if day.get("t") is None and entry.get("tmin") is not None and entry.get("tmax") is not None:
            day["t"] = (entry["tmin"] + entry["tmax"]) / 2
    limit = today.isoformat()
    return [{"date": k, **v} for k, v in sorted(days.items()) if k < limit]


def daily_temperatures(
    hourly_temp: dict[int, tuple[float, float]], tz: Any, day_log: dict[str, Any]
) -> dict[str, float]:
    """Mean temperature of each day ((min + max) / 2): statistics first, own log otherwise."""
    extremes: dict[str, list[float]] = {}
    for ts, (low, high) in hourly_temp.items():
        key = datetime.fromtimestamp(ts, tz).date().isoformat()
        entry = extremes.setdefault(key, [low, high, 0])
        entry[0], entry[1], entry[2] = min(entry[0], low), max(entry[1], high), entry[2] + 1
    temps = {key: (low + high) / 2 for key, (low, high, count) in extremes.items() if count >= 20}
    for key, entry in day_log.items():
        if key not in temps and entry.get("tmin") is not None and entry.get("tmax") is not None:
            temps[key] = (entry["tmin"] + entry["tmax"]) / 2
    return temps


def heating_points(
    hourly_kwh: dict[int, float],
    hourly_mean_temp: dict[int, float],
    tz: Any,
    base: float,
    today: date,
    max_kwh: float,
) -> list[tuple[float, float]]:
    """(degree-days, kWh) of each fully recorded day."""
    days: dict[str, list[float]] = {}
    for ts, temp in hourly_mean_temp.items():
        value = hourly_kwh.get(ts)
        if value is None or not 0 <= value <= max_kwh:
            continue
        entry = days.setdefault(datetime.fromtimestamp(ts, tz).date().isoformat(), [0.0, 0.0, 0])
        entry[0] += max(0.0, base - temp) / 24
        entry[1] += value
        entry[2] += 1
    limit = today.isoformat()
    return [(e[0], e[1]) for k, e in sorted(days.items()) if e[2] >= 22 and k < limit]
