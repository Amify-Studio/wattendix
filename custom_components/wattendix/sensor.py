"""Wattendix sensors: only those the configuration can feed are created."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WattendixConfigEntry
from .const import DOMAIN, MODE_PER_SOURCE, VERSION
from .controller import WattendixController
from .core.periods import PERIODS

Snapshot = dict[str, Any]
CURRENCY = "currency"  # placeholder replaced by the instance currency
HDD_UNIT = "°C·d"


@dataclass(frozen=True, kw_only=True)
class WattendixSensorDescription(SensorEntityDescription):
    """A sensor reading the controller snapshot."""

    value_fn: Callable[[Snapshot], Any]
    attrs_fn: Callable[[Snapshot, WattendixController], dict[str, Any]] | None = None
    reset_fn: Callable[[Snapshot], str | None] | None = None
    digits: int = 2


def _r(value: Any, digits: int = 2) -> Any:
    return round(value, digits) if isinstance(value, (int, float)) else value


def _period_attrs(period: str, q: str) -> Callable[[Snapshot, WattendixController], dict[str, Any]]:
    def attrs(snap: Snapshot, controller: WattendixController) -> dict[str, Any]:
        block = snap["periods"][period]
        out = {
            "estimate": _r(block.get(f"{q}_estimate")),
            "previous": _r(block.get(f"{q}_previous")),
            "average": _r(block.get(f"{q}_average")),
            "trend": block.get(f"{q}_trend"),
            "period_start": block["start"],
            "method": snap["method"],
        }
        if q == "cost":
            out["energy_cost"] = _r(block.get("cost_energy"))
            out["subscription"] = _r(block.get("subscription"), 4)
        if snap.get("delayed"):
            out["data_until"] = snap.get("data_until")
        if period == "year" and q == "kwh":
            year = snap["year"]
            out["previous_year_total"] = _r(year["previous_total"], 0)
            out["previous_year_to_date"] = _r(year["previous_to_date"], 0)
            out["gap_to_previous_year"] = year["gap"]
        return out

    return attrs


def _method_attrs(snap: Snapshot, controller: WattendixController) -> dict[str, Any]:
    model = controller.engine.d.get("model") or {}
    return {
        "reason": snap["reason"],
        "days_learned": snap["model_days"],
        "last_learned": model.get("learned_at"),
        "temperature_today": snap["temperature_today"],
        "temperature_source": snap["temperature_source"],
        "temperature_bias": snap["temperature_bias"],
        "temperature_bias_days": snap["temperature_bias_days"],
        "forecast_days": snap["forecast_days"],
        "expected_energy_today": _r(snap["expected_today"].get("kwh")),
        "expected_cost_today": _r(snap["expected_today"].get("cost")),
        "table": snap["model_bins"],
    }


def _heating_attrs(period: str) -> Callable[[Snapshot, WattendixController], dict[str, Any]]:
    def attrs(snap: Snapshot, controller: WattendixController) -> dict[str, Any]:
        block = snap["heating"].get(period) or {}
        fit = snap["heating"].get("fit") or {}
        return {
            "expected": _r(block.get("expected"), 1),
            "gap": block.get("gap"),
            "degree_days": _r(block.get("hdd"), 1),
            "per_degree_day": block.get("per_hdd"),
            "period_start": block.get("start"),
            "model_base": fit.get("base"),
            "model_slope": fit.get("slope"),
            "model_r2": fit.get("r2"),
            "model_days": fit.get("n"),
            "degree_day_base": controller.hdd_base,
        }

    return attrs


def _descriptions(controller: WattendixController) -> list[WattendixSensorDescription]:
    out: list[WattendixSensorDescription] = []
    for period in PERIODS:
        if controller.delayed and period == "hour":
            continue  # a delayed source has one total per day
        start = lambda s, p=period: s["periods"][p]["start"]  # noqa: E731
        out.append(
            WattendixSensorDescription(
                key=f"energy_{period}",
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                value_fn=lambda s, p=period: s["periods"][p]["kwh"],
                attrs_fn=_period_attrs(period, "kwh"),
                reset_fn=start,
                digits=3,
            )
        )
        estimated = not (controller.delayed and period == "day")
        if estimated:
            out.append(
                WattendixSensorDescription(
                    key=f"energy_{period}_estimate",
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                icon="mdi:chart-timeline-variant-shimmer",
                value_fn=lambda s, p=period: s["periods"][p]["kwh_estimate"],
            )
        )
        if not controller.priced:
            continue
        out.append(
            WattendixSensorDescription(
                key=f"cost_{period}",
                device_class=SensorDeviceClass.MONETARY,
                state_class=SensorStateClass.TOTAL,
                native_unit_of_measurement=CURRENCY,
                value_fn=lambda s, p=period: s["periods"][p]["cost"],
                attrs_fn=_period_attrs(period, "cost"),
                reset_fn=start,
            )
        )
        if estimated:
          out.append(
            WattendixSensorDescription(
                key=f"cost_{period}_estimate",
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=CURRENCY,
                icon="mdi:cash-clock",
                value_fn=lambda s, p=period: s["periods"][p]["cost_estimate"],
            )
        )

    # With one price per sensor there is no single current price to show.
    if controller.priced and controller.price_mode != MODE_PER_SOURCE:
        out.append(
            WattendixSensorDescription(
                key="price",
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=f"{CURRENCY}/kWh",
                icon="mdi:cash",
                value_fn=lambda s: s["price"],
                attrs_fn=lambda s, c: {
                    "mode": c.price_mode,
                    "tariff_period": None
                    if s["offpeak"] is None
                    else ("offpeak" if s["offpeak"] else "peak"),
                },
                digits=5,
            )
        )
    if controller.has_subscription:
        out.append(
            WattendixSensorDescription(
                key="subscription",
                native_unit_of_measurement=CURRENCY,
                icon="mdi:file-certificate-outline",
                value_fn=lambda s: s["subscription_month"],
                attrs_fn=lambda s, c: {
                    "per_day": _r(s["subscription_day"], 4),
                    "source_available": c.subscription_available,
                },
            )
        )
    out.append(
        WattendixSensorDescription(
            key="method",
            device_class=SensorDeviceClass.ENUM,
            options=["model", "average", "pace"],
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:head-cog-outline",
            value_fn=lambda s: s["method"],
            attrs_fn=_method_attrs,
        )
    )
    out.append(
        WattendixSensorDescription(
            key="rejected_jumps",
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:shield-alert-outline",
            value_fn=lambda s: s["meter"]["rejected"],
            attrs_fn=lambda s, c: {
                "last_rejected": s["meter"]["last_rejected"],
                "counter_resets": s["meter"]["resets"],
                "source_kind": c.source_kind,
            },
            digits=0,
        )
    )
    if controller.has_heating:
        for period in ("day", "month", "season"):
            out.append(
                WattendixSensorDescription(
                    key=f"degree_days_{period}",
                    state_class=SensorStateClass.MEASUREMENT,
                    native_unit_of_measurement=HDD_UNIT,
                    icon="mdi:thermometer-minus",
                    value_fn=lambda s, p=period: (s["heating"].get(p) or {}).get("hdd"),
                )
            )
        for period in ("month", "season"):
            out.append(
                WattendixSensorDescription(
                    key=f"heating_{period}",
                    device_class=SensorDeviceClass.ENERGY,
                    state_class=SensorStateClass.TOTAL,
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    icon="mdi:heat-pump-outline",
                    value_fn=lambda s, p=period: (s["heating"].get(p) or {}).get("kwh"),
                    attrs_fn=_heating_attrs(period),
                    reset_fn=lambda s, p=period: (s["heating"].get(p) or {}).get("start"),
                )
            )
    return out


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WattendixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors of this meter."""
    controller = entry.runtime_data
    async_add_entities(
        WattendixSensor(controller, description) for description in _descriptions(controller)
    )


class WattendixSensor(SensorEntity):
    """One value of the controller snapshot."""

    entity_description: WattendixSensorDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, controller: WattendixController, description: WattendixSensorDescription
    ) -> None:
        self.controller = controller
        self.entity_description = description
        entry = controller.entry
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_suggested_display_precision = min(description.digits, 2)
        unit = description.native_unit_of_measurement
        if unit and CURRENCY in unit:
            self._attr_native_unit_of_measurement = unit.replace(
                CURRENCY, controller.hass.config.currency
            )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Amify-Studio",
            model="Energy monitor",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    def _snapshot(self) -> Snapshot:
        return self.controller.snapshot

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self._snapshot())
        return _r(value, self.entity_description.digits)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self._snapshot(), self.controller)

    @property
    def last_reset(self) -> datetime | None:
        if self.entity_description.reset_fn is None:
            return None
        start = self.entity_description.reset_fn(self._snapshot())
        return datetime.fromisoformat(start) if start else None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.controller.async_add_listener(self.async_write_ha_state))
