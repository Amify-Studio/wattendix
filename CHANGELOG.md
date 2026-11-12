# Changelog

## 0.3.1

- The curve title no longer wraps while hovering: the tooltip stays on one line and ends with "…" when it is too long, so the curve keeps its place.
- The getting-started guides describe the default periods and the tooltip; the curve screenshot shows the hour.

## 0.3.0

- The curves lay the previous period over the current one, at the same moment (yesterday 14:00 against today 14:00), instead of a flat line at its total. The tooltip gives both values; past the current moment it shows the previous period alone. A previous period the history covers only in part keeps the flat line.
- New cards show the hour too, with its curve against the previous hour.

## 0.2.1

- A device the integration no longer provides (such as one left under the former `wattcast` domain) can be deleted from its device page.
- The version reported to the card matches the release.
- The card shows a live preview in the card picker, with a description in the dashboard's language.

## 0.2.0

- Renamed to **Wattendix** (domain `wattendix`, card `custom:wattendix-card`): the name Wattcast and its domain were already used by another integration in the catalog.
- Install instructions for the Home Assistant 2026.11 Marketplace.

## 0.1.0

- First version: period counters, estimates, self-learned weather model, peak/off-peak prices, standing charge, year comparison, heating follow-up, Lovelace card.
