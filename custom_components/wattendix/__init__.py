"""Wattendix: your electricity bill, live and forecast."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, VERSION
from .controller import STORAGE_VERSION, WattendixController

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_FILE = "wattendix-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"

type WattendixConfigEntry = ConfigEntry[WattendixController]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the Lovelace card shipped with the integration."""
    websocket_api.async_register_command(hass, ws_info)
    websocket_api.async_register_command(hass, ws_curve)
    card = Path(__file__).parent / "frontend" / CARD_FILE
    if "frontend" not in hass.config.components:
        return True
    digest = await hass.async_add_executor_job(_file_digest, card)
    if digest is None:
        _LOGGER.warning("Card file %s is missing; the card will not load", card)
        return True
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(card), cache_headers=False)]
    )
    # The content hash changes with every build, so browsers never keep a stale card.
    add_extra_js_url(hass, f"{CARD_URL}?v={VERSION}-{digest}")
    return True


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    except OSError:
        return None


async def async_setup_entry(hass: HomeAssistant, entry: WattendixConfigEntry) -> bool:
    """Start the controller of this meter."""
    controller = WattendixController(hass, entry)
    await controller.async_setup()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WattendixConfigEntry) -> bool:
    """Unload the sensors, then stop and save the controller."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_unload()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the stored counters with the entry."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


@websocket_api.websocket_command({vol.Required("type"): "wattendix/info"})
@callback
def ws_info(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Tell the card which entities belong to which Wattendix entry."""
    registry = er.async_get(hass)
    entries = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        controller: WattendixController = entry.runtime_data
        entities = {
            item.unique_id.removeprefix(f"{entry.entry_id}_"): item.entity_id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        entries.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "currency": hass.config.currency,
                "priced": controller.priced,
                "delayed": controller.delayed,
                "subscription": controller.has_subscription,
                "temperature": controller.has_temperature,
                "heating": controller.has_heating,
                "entities": entities,
            }
        )
    connection.send_result(msg["id"], {"version": VERSION, "entries": entries})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wattendix/curve",
        vol.Required("entry_id"): str,
        vol.Required("period"): vol.In(["hour", "day", "week", "month", "year"]),
    }
)
@websocket_api.async_response
async def ws_curve(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Cumulative consumption of the current period, for the card's curve."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown Wattendix entry")
        return
    points = await entry.runtime_data.async_curve(msg["period"])
    connection.send_result(msg["id"], {"points": points})
