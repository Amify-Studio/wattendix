/* Wattendix card — your electricity bill, live and forecast.
 * Plain custom element: no build step, no dependency. */

const PERIODS = ["hour", "day", "week", "month", "year"];
const DEFAULT_PERIODS = ["day", "week", "month", "year"];
const ICONS = {
  hour: "mdi:clock-outline",
  day: "mdi:weather-sunny",
  week: "mdi:calendar-week",
  month: "mdi:calendar-month",
  year: "mdi:calendar-blank-multiple",
  heating_month: "mdi:heat-pump-outline",
  heating_season: "mdi:calendar-range",
};

const TEXT = {
  en: {
    hour: "This hour", day: "Today", week: "This week", month: "This month", year: "This year",
    prev_hour: "Prev. hour", prev_day: "Yesterday", prev_week: "Last week",
    prev_month: "Last month", prev_year: "Last year",
    estimate: "Estimate", projection: "Projection", to_date: "Last year to date",
    trend: "Energy trend against the previous period",
    gap_year: "Gap with last year at the same date",
    gap_heating: "Gap with the consumption expected for the weather",
    heating_month: "Heating (month)", heating_season: "Heating (season)",
    expected: "Expected for the weather", cold: "Cold", dd: "DD",
    peak: "Peak", offpeak: "Off-peak", subscription: "Standing charge", per_month: "/month",
    model: "Weather model", average: "7-day average", pace: "Today's pace",
    learning: "learning", no_temperature: "no temperature", out_of_range: "out of range",
    missing: "Wattendix is not set up yet. Add the integration first.",
    loading: "Loading…",
    f_title: "Title", f_entry: "Wattendix meter", f_periods: "Periods", f_display: "Display",
    f_heating: "Hide heating", f_info: "Hide price, standing charge and method",
    auto: "Automatic", cost: "Cost", energy: "Energy (kWh)",
    last_day: "Reading", received: "Data up to",
    current: "So far", avg_hour: "7-hour average", avg_day: "7-day average",
    avg_week: "4-week average", avg_month: "12-month average", avg_year: "Average",
    f_charts: "Show curves",
    f_layout: "Layout", tiles: "Tiles", table: "Summary table", mini: "Mini table",
    m_current: "Actual", s_hour: "Hour", s_day: "Day", s_week: "Week", s_month: "Month", s_year: "Year",
    s_heating_month: "Heating, month", s_heating_season: "Heating, season", f_columns: "Table columns",
    f_descending: "Longest period first",
    c_current: "So far", c_estimate: "Estimate", c_previous: "Previous", c_average: "Average", c_trend: "Trend",
  },
  fr: {
    hour: "Cette heure", day: "Aujourd'hui", week: "Cette semaine", month: "Ce mois", year: "Cette année",
    prev_hour: "Heure préc.", prev_day: "Hier", prev_week: "Sem. préc.",
    prev_month: "Mois préc.", prev_year: "Année préc.",
    estimate: "Estimation", projection: "Projection", to_date: "An dernier à date",
    trend: "Tendance de consommation par rapport à la période précédente",
    gap_year: "Écart avec l'an dernier à la même date",
    gap_heating: "Écart avec la consommation attendue pour la météo",
    heating_month: "Chauffage (mois)", heating_season: "Chauffage (saison)",
    expected: "Attendu selon météo", cold: "Froid", dd: "DJU",
    peak: "Heures pleines", offpeak: "Heures creuses", subscription: "Abonnement", per_month: "/mois",
    model: "Modèle météo", average: "Moyenne 7 jours", pace: "Rythme du jour",
    learning: "apprentissage", no_temperature: "pas de température", out_of_range: "hors plage",
    missing: "Wattendix n'est pas encore configuré. Ajoutez d'abord l'intégration.",
    loading: "Chargement…",
    f_title: "Titre", f_entry: "Compteur Wattendix", f_periods: "Périodes", f_display: "Affichage",
    f_heating: "Masquer le chauffage", f_info: "Masquer prix, abonnement et méthode",
    auto: "Automatique", cost: "Coût", energy: "Énergie (kWh)",
    last_day: "Relevé", received: "Données jusqu'au",
    current: "En cours", avg_hour: "Moyenne 7 h", avg_day: "Moyenne 7 j",
    avg_week: "Moyenne 4 sem.", avg_month: "Moyenne 12 mois", avg_year: "Moyenne",
    f_charts: "Afficher les courbes",
    f_layout: "Disposition", tiles: "Tuiles", table: "Tableau résumé", mini: "Mini tableau",
    m_current: "Réel", s_hour: "Heure", s_day: "Jour", s_week: "Semaine", s_month: "Mois", s_year: "Année",
    s_heating_month: "Chauffage, mois", s_heating_season: "Chauffage, saison", f_columns: "Colonnes du tableau",
    f_descending: "Plus longue période en premier",
    c_current: "En cours", c_estimate: "Estim.", c_previous: "Préc.", c_average: "Moy.", c_trend: "Tend.",
  },
};

const lang = (hass) => {
  const code = (hass && (hass.locale?.language || hass.language)) ||
    document.querySelector("home-assistant")?.hass?.language || navigator.language || "en";
  return String(code).toLowerCase().startsWith("fr") ? "fr" : "en";
};
const esc = (text) => String(text).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (value) => {
  const n = typeof value === "number" ? value : parseFloat(value);
  return Number.isFinite(n) ? n : null;
};

// Statistics resolution used for the curve of each period.
const COLUMNS = ["current", "estimate", "previous", "average", "trend"];
const DEFAULT_COLUMNS = ["current", "estimate", "previous", "trend"];
const RESOLUTION = { hour: "5minute", day: "5minute", week: "hour", month: "hour", year: "day" };
const CHART = { w: 320, h: 150, l: 34, r: 8, t: 8, b: 20 };

const periodEnd = (start, period) => {
  const d = new Date(start);
  if (period === "hour") return start + 3600000;
  if (period === "day") return new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).getTime();
  if (period === "week") return new Date(d.getFullYear(), d.getMonth(), d.getDate() + 7).getTime();
  if (period === "month") return new Date(d.getFullYear(), d.getMonth() + 1, 1).getTime();
  return new Date(d.getFullYear() + 1, 0, 1).getTime();
};

const niceStep = (max, count = 4) => {
  const raw = Math.max(max, 1e-6) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const n = raw / magnitude;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * magnitude;
};

const xTicks = (start, period, locale) => {
  const d = new Date(start);
  const day = (offset) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + offset);
  const out = [];
  if (period === "hour") {
    for (let m = 0; m < 60; m += 15) out.push([start + m * 60000, `:${String(m).padStart(2, "0")}`]);
  } else if (period === "day") {
    for (let h = 0; h < 24; h += 6) {
      out.push([new Date(d.getFullYear(), d.getMonth(), d.getDate(), h).getTime(), `${h} h`]);
    }
  } else if (period === "week") {
    const format = new Intl.DateTimeFormat(locale, { weekday: "short" });
    for (let i = 0; i < 7; i++) out.push([day(i).getTime(), format.format(day(i))]);
  } else if (period === "month") {
    for (let n = 1; n <= 29; n += 7) out.push([new Date(d.getFullYear(), d.getMonth(), n).getTime(), String(n)]);
  } else {
    const format = new Intl.DateTimeFormat(locale, { month: "short" });
    for (let m = 0; m < 12; m += 2) {
      const x = new Date(d.getFullYear(), m, 1);
      out.push([x.getTime(), format.format(x)]);
    }
  }
  return out;
};

const STYLE = `
  :host { display: block; }
  ha-card { padding: 14px; container-type: inline-size; }
  .title { font-size: 16px; font-weight: 500; margin: 0 2px 10px; color: var(--primary-text-color); }
  .tiles { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(205px, 1fr)); }
  .tile {
    display: grid; grid-template-columns: 1fr auto; row-gap: 8px; column-gap: 6px; align-items: center;
    padding: 12px 14px; border-radius: var(--ha-card-border-radius, 12px);
    background: color-mix(in srgb, var(--primary-text-color) 4%, transparent);
    cursor: pointer; min-width: 0; text-align: left; border: 0; font: inherit; color: inherit;
  }
  .tile:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
  .name { display: flex; align-items: center; gap: 6px; font-size: 13px; min-width: 0;
    color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .name ha-icon { --mdc-icon-size: 17px; opacity: .8; flex: none; }
  .pill { font-size: 11.5px; font-weight: 600; padding: 2px 8px; border-radius: 999px; white-space: nowrap;
    color: var(--pill); background: color-mix(in srgb, var(--pill) 16%, transparent); }
  .value { grid-column: 1 / -1; display: flex; align-items: baseline; flex-wrap: wrap; gap: 2px 8px; line-height: 1; }
  .big { font-size: 26px; font-weight: 600; letter-spacing: -.5px; white-space: nowrap; }
  .unit { font-size: 14px; opacity: .55; margin-left: 3px; font-weight: 400; letter-spacing: 0; }
  .side { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; }
  .bar { grid-column: 1 / -1; position: relative; height: 6px; border-radius: 3px; background: var(--divider-color); }
  .fill { height: 100%; border-radius: 3px; background: var(--wattendix-color, var(--primary-color)); max-width: 100%; }
  .fill.over { background: var(--warning-color, #ffa600); }
  .mark { position: absolute; top: -3px; width: 2px; height: 12px; border-radius: 1px;
    background: var(--secondary-text-color); opacity: .7; }
  .detail { grid-column: 1 / -1; font-size: 12px; color: var(--secondary-text-color); line-height: 1.45; }
  .detail b { color: var(--primary-text-color); font-weight: 600; }
  .detail span { white-space: nowrap; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; padding: 4px 10px;
    border-radius: 999px; border: 1px solid var(--divider-color); color: var(--secondary-text-color);
    background: none; cursor: pointer; font-family: inherit; }
  .chip ha-icon { --mdc-icon-size: 15px; }
  .chip.warn { color: var(--warning-color, #ffa600); }
  .scroll { overflow-x: auto; }
  .table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  .table th, .table td { padding: 9px 10px; text-align: right; white-space: nowrap;
    border-bottom: 1px solid color-mix(in srgb, var(--divider-color) 70%, transparent); }
  .table tbody tr:last-child th, .table tbody tr:last-child td { border-bottom: 0; }
  .table thead th { font-size: 11.5px; font-weight: 500; letter-spacing: .3px; text-transform: uppercase;
    color: var(--secondary-text-color); padding-top: 2px; padding-bottom: 7px; }
  .table .u { opacity: .65; text-transform: none; }
  .table tbody th { text-align: left; font-weight: 500; font-size: 13.5px; color: var(--primary-text-color);
    padding-left: 4px; }
  .table tbody th ha-icon { --mdc-icon-size: 17px; opacity: .65; margin-right: 8px; vertical-align: -3px; }
  .table td { font-size: 14px; color: var(--secondary-text-color); }
  .table td.cur { color: var(--primary-text-color); font-weight: 600; font-size: 15px; }
  .table td.est { color: var(--primary-text-color); }
  .table td small { font-size: 11px; font-weight: 400; opacity: .6; margin-left: 3px; }
  .table .bar { height: 3px; margin-top: 5px; min-width: 46px; }
  .table tbody tr { cursor: pointer; }
  .table tbody tr:hover { background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
  .table .sep th, .table .sep td { border-top: 1px solid var(--divider-color); }
  ha-card.is-mini { padding: 10px; }
  .mini th, .mini td { padding: 5px 9px; border: 1px solid var(--divider-color); }
  .mini tbody tr:last-child th, .mini tbody tr:last-child td { border-bottom: 1px solid var(--divider-color); }
  .mini thead th { font-size: 13px; font-weight: 600; text-transform: none; letter-spacing: 0;
    color: var(--primary-text-color); padding: 5px 9px; }
  .mini tbody th { font-size: 13px; font-weight: 600; padding-left: 9px; }
  .mini td, .mini td.cur { font-size: 13px; font-weight: 400; color: var(--primary-text-color); }
  .mini .up { color: var(--error-color); }
  .mini .down { color: var(--success-color); }
  @container (max-width: 330px) {
    .mini th, .mini td, .mini thead th { padding: 4px 5px; font-size: 12px; }
    .mini tbody th { padding-left: 5px; font-size: 12px; }
  }
  @container (max-width: 520px) {
    .table:not(.mini) th, .table:not(.mini) td { padding: 8px 3px; }
    .table:not(.mini) thead th { font-size: 10.5px; letter-spacing: 0; }
    .table:not(.mini) .u, .table:not(.mini) td small { display: none; }
    .table:not(.mini) tbody th { white-space: normal; font-size: 12.5px; line-height: 1.2; padding-left: 0; }
    .table tbody th ha-icon { display: none; }
    .table:not(.mini) td { font-size: 12.5px; }
    .table:not(.mini) td.cur { font-size: 13.5px; }
    .table .bar { min-width: 34px; }
    .table .pill { background: none; padding: 0; font-size: 11.5px; }
  }
  .charts { display: grid; gap: 10px; margin-top: 10px;
    grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
    --wc-cur: var(--wattendix-color, var(--primary-color)); --wc-est: #ffb300;
    --wc-prev: #90a4ae; --wc-avg: #ba68c8; }
  .chart { padding: 10px 12px; border-radius: var(--ha-card-border-radius, 12px); min-width: 0;
    background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); }
  .chart-head { display: flex; justify-content: space-between; gap: 8px; align-items: baseline;
    font-size: 13px; color: var(--secondary-text-color); margin-bottom: 4px; }
  .tip { font-size: 11.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .chart svg { display: block; width: 100%; height: auto; touch-action: pan-y; }
  .chart text { font-size: 9.5px; fill: var(--secondary-text-color); }
  .grid { stroke: var(--divider-color); stroke-width: .6; stroke-dasharray: 3 3; }
  .now { stroke: var(--secondary-text-color); stroke-width: .7; opacity: .7; }
  .cursor { stroke: var(--primary-text-color); stroke-width: .6; opacity: .5; }
  .l-cur { fill: none; stroke: var(--wc-cur); stroke-width: 1.8; stroke-linejoin: round; }
  .a-cur { fill: var(--wc-cur); opacity: .16; }
  .l-est { fill: none; stroke: var(--wc-est); stroke-width: 1.6; stroke-dasharray: 5 3; stroke-linejoin: round; }
  .l-prev { stroke: var(--wc-prev); stroke-width: 1.3; }
  .l-avg { stroke: var(--wc-avg); stroke-width: 1.3; stroke-dasharray: 2 3; }
  .legend { display: flex; flex-wrap: wrap; gap: 2px 12px; margin-top: 4px; font-size: 11.5px;
    color: var(--secondary-text-color); }
  .legend span { white-space: nowrap; }
  .legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }
  .legend b { color: var(--primary-text-color); font-weight: 600; }
  .note { color: var(--secondary-text-color); font-size: 14px; padding: 8px 2px; }
  @container (max-width: 330px) {
    .tiles { grid-template-columns: 1fr; }
  }
  @container (min-width: 331px) and (max-width: 420px) {
    ha-card { padding: 10px; }
    .tiles { gap: 8px; grid-template-columns: 1fr 1fr; }
    .tile { padding: 10px; }
    .big { font-size: 22px; }
    .name ha-icon { display: none; }
  }
`;

class WattendixCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._info = null;
    this._infoAt = 0;
    this._signature = "";
    this._series = {};
    this._geometry = {};
    this.shadowRoot.addEventListener("pointermove", (event) => this._hover(event));
    this.shadowRoot.addEventListener("click", (event) => {
      const target = event.target.closest("[data-entity]");
      if (target) this._moreInfo(target.dataset.entity);
    });
  }

  static getStubConfig() {
    return { periods: DEFAULT_PERIODS };
  }

  static getConfigForm() {
    const t = TEXT[lang()];
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        { name: "entry", selector: { config_entry: { integration: "wattendix" } } },
        {
          name: "periods",
          selector: { select: { multiple: true, mode: "list",
            options: PERIODS.map((p) => ({ value: p, label: t[p] })) } },
        },
        {
          name: "display",
          selector: { select: { mode: "dropdown",
            options: ["auto", "cost", "energy"].map((v) => ({ value: v, label: t[v] })) } },
        },
        {
          name: "layout",
          selector: { select: { mode: "dropdown",
            options: ["tiles", "table", "mini"].map((v) => ({ value: v, label: t[v] })) } },
        },
        {
          name: "columns",
          selector: { select: { multiple: true, mode: "list",
            options: COLUMNS.map((c) => ({ value: c, label: t[`c_${c}`] })) } },
        },
        { name: "descending", selector: { boolean: {} } },
        { name: "charts", selector: { boolean: {} } },
        { name: "hide_heating", selector: { boolean: {} } },
        { name: "hide_info", selector: { boolean: {} } },
      ],
      computeLabel: (field) => ({
        title: t.f_title, entry: t.f_entry, periods: t.f_periods, display: t.f_display,
        layout: t.f_layout, columns: t.f_columns, descending: t.f_descending,
        charts: t.f_charts, hide_heating: t.f_heating, hide_info: t.f_info,
      }[field.name]),
    };
  }

  setConfig(config) {
    const periods = Array.isArray(config.periods) && config.periods.length
      ? PERIODS.filter((p) => config.periods.includes(p)) : DEFAULT_PERIODS;
    this._config = { display: "auto", ...config, periods };
    this._signature = "";
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  getCardSize() {
    return 1 + Math.ceil(this._config.periods.length / 2) * 2;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      detail: { entityId }, bubbles: true, composed: true,
    }));
  }

  async _loadInfo() {
    if (this._loading || Date.now() - this._infoAt < 15000) return;
    this._loading = true;
    this._infoAt = Date.now();
    try {
      this._info = await this._hass.callWS({ type: "wattendix/info" });
    } catch (err) {
      this._info = this._info || { entries: [] };
    }
    this._loading = false;
    this._signature = "";
    this._update();
  }

  _periods(entry) {
    return entry && entry.delayed ? this._config.periods.filter((p) => p !== "hour") : this._config.periods;
  }

  _dayLabel(entry, state, t, short) {
    // A delayed source shows its last finished day, not today.
    if (!entry.delayed) return null;
    const start = state.attributes.period_start;
    const date = start ? new Intl.DateTimeFormat(this._hass.locale?.language || "en",
      { weekday: "short", day: "numeric" }).format(new Date(start)) : "";
    return short ? date : `${t.last_day} · ${date}`;
  }

  _entry() {
    const entries = this._info?.entries || [];
    return entries.find((e) => e.entry_id === this._config.entry) || entries[0] || null;
  }

  _update() {
    const hass = this._hass;
    if (!hass) return;
    const entry = this._entry();
    const ids = entry ? Object.values(entry.entities) : [];
    // (Re)ask which entities exist: first render, or an entity vanished (options changed).
    if (!this._info || !entry || ids.some((id) => !hass.states[id])) this._loadInfo();
    if (entry && this._config.charts) this._loadCharts(entry);
    const signature = [lang(hass), JSON.stringify(this._config), entry?.entry_id,
      ...ids.map((id) => hass.states[id]?.last_updated)].join("|");
    if (signature === this._signature) return;
    this._signature = signature;
    this._render(entry);
  }

  _state(entry, key) {
    const id = entry.entities[key];
    const state = id && this._hass.states[id];
    return state && !["unavailable", "unknown"].includes(state.state) ? state : null;
  }

  _fmt(value, digits) {
    if (value === null) return "–";
    const locale = this._hass.locale?.language || this._hass.language || "en";
    return new Intl.NumberFormat(locale, {
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    }).format(value);
  }

  _money(value, currency, reference) {
    const digits = Math.abs(reference ?? value ?? 0) >= 1000 ? 0 : 2;
    return { text: this._fmt(value, digits), unit: this._symbol(currency) };
  }

  _symbol(currency) {
    try {
      const locale = this._hass.locale?.language || "en";
      return new Intl.NumberFormat(locale, { style: "currency", currency, currencyDisplay: "narrowSymbol" })
        .formatToParts(0).find((p) => p.type === "currency").value;
    } catch (err) {
      return currency || "";
    }
  }

  _energy(value, reference) {
    const digits = Math.abs(reference ?? value ?? 0) >= 100 ? 0 : 1;
    return { text: this._fmt(value, digits), unit: "kWh" };
  }

  _pill(value, title) {
    if (value === null) return "";
    const color = value > 0 ? "var(--error-color)" : "var(--success-color)";
    const arrow = value > 0 ? "▲ " : value < 0 ? "▼ " : "";
    return `<span class="pill" style="--pill:${color}" title="${esc(title)}">${arrow}${this._fmt(Math.abs(value), 1)} %</span>`;
  }

  _bar(value, target, mark) {
    if (value === null || target === null || target <= 0) return `<div class="bar"></div>`;
    const scale = Math.max(target, value, mark ?? 0);
    const width = Math.max(0, Math.min(100, (value / scale) * 100));
    const over = value > target * 1.001 ? " over" : "";
    const tick = mark !== null && mark !== undefined && mark > 0
      ? `<div class="mark" style="left:calc(${Math.min(100, (mark / scale) * 100)}% - 1px)"></div>` : "";
    return `<div class="bar"><div class="fill${over}" style="width:${width}%"></div>${tick}</div>`;
  }

  _tile({ entity, icon, name, pill, value, side, bar, detail }) {
    return `<button class="tile" data-entity="${esc(entity)}">
      <div class="name"><ha-icon icon="${icon}"></ha-icon>${esc(name)}</div>${pill || "<span></span>"}
      <div class="value"><span class="big">${value.text}<span class="unit">${esc(value.unit)}</span></span>${
        side ? `<span class="side">${side}</span>` : ""}</div>
      ${bar}
      <div class="detail">${detail}</div>
    </button>`;
  }

  _periodTile(entry, period, useCost, t) {
    const state = this._state(entry, `${useCost ? "cost" : "energy"}_${period}`);
    if (!state) return "";
    const a = state.attributes;
    const value = num(state.state);
    const estimate = num(a.estimate);
    const previous = num(a.previous);
    const format = (v) => {
      const f = useCost ? this._money(v, entry.currency, estimate) : this._energy(v, estimate);
      return `${f.text} ${esc(f.unit)}`;
    };
    let pill = this._pill(num(a.trend), t.trend);
    const finished = entry.delayed && period === "day";
    let detail = finished ? "" : `<span>${t.estimate} <b>${format(estimate)}</b></span>`;
    if (previous !== null) {
      detail += `${detail ? " · " : ""}<span>${t[`prev_${period}`]} ${format(previous)}</span>`;
    }
    let mark = previous;
    let side = "";
    if (useCost) {
      const energy = this._state(entry, `energy_${period}`);
      if (energy) {
        const e = this._energy(num(energy.state), num(energy.attributes.estimate));
        side = `${e.text} ${e.unit}`;
      }
    } else if (period === "year" && num(a.previous_year_to_date) !== null) {
      // In kWh the year compares with last year at the same date.
      pill = this._pill(num(a.gap_to_previous_year), t.gap_year);
      detail = `<span>${t.projection} <b>${format(estimate)}</b></span> · <span>${t.to_date} ${format(num(a.previous_year_to_date))}</span>`;
      mark = num(a.previous_year_total);
    }
    return this._tile({
      entity: state.entity_id, icon: ICONS[period],
      name: (period === "day" && this._dayLabel(entry, state, t, false)) || t[period], pill,
      value: useCost ? this._money(value, entry.currency, estimate) : this._energy(value, estimate),
      side, bar: this._bar(value, estimate, mark), detail,
    });
  }

  _heatingTile(entry, key, t) {
    const state = this._state(entry, key);
    if (!state) return "";
    const a = state.attributes;
    const value = num(state.state);
    const expected = num(a.expected);
    const format = (v) => { const f = this._energy(v, expected ?? value); return `${f.text} ${f.unit}`; };
    const parts = [];
    if (expected !== null) parts.push(`<span>${t.expected} <b>${format(expected)}</b></span>`);
    if (num(a.degree_days) !== null) {
      parts.push(`<span>${t.cold} ${this._fmt(num(a.degree_days), 0)} ${t.dd}</span>`);
    }
    return this._tile({
      entity: state.entity_id, icon: ICONS[key], name: t[key],
      pill: this._pill(num(a.gap), t.gap_heating),
      value: this._energy(value, expected ?? value), side: "",
      bar: this._bar(value, expected, null), detail: parts.join(" · "),
    });
  }

  _chips(entry, t) {
    const chips = [];
    const chip = (state, icon, text, extra = "") =>
      `<button class="chip ${extra}" data-entity="${esc(state.entity_id)}"><ha-icon icon="${icon}"></ha-icon>${text}</button>`;
    const price = this._state(entry, "price");
    if (price) {
      const period = price.attributes.tariff_period;
      const label = period ? `${t[period]} · ` : "";
      const icon = period === "offpeak" ? "mdi:weather-night" : period === "peak" ? "mdi:white-balance-sunny" : "mdi:cash";
      chips.push(chip(price, icon, `${label}${this._fmt(num(price.state), 4)} ${esc(this._symbol(entry.currency))}/kWh`));
    }
    const subscription = this._state(entry, "subscription");
    if (subscription) {
      const m = this._money(num(subscription.state), entry.currency);
      chips.push(chip(subscription, "mdi:file-certificate-outline",
        `${t.subscription} ${m.text} ${esc(m.unit)}${t.per_month}`));
    }
    const day = entry.delayed && this._state(entry, "energy_day");
    if (day && day.attributes.data_until) {
      const date = new Intl.DateTimeFormat(this._hass.locale?.language || "en",
        { weekday: "short", day: "numeric", month: "short" }).format(new Date(`${day.attributes.data_until}T12:00:00`));
      chips.push(chip(day, "mdi:cloud-clock-outline", `${t.received} ${esc(date)}`));
    }
    const method = this._state(entry, "method");
    if (method && entry.temperature) {
      const a = method.attributes;
      let text = t[method.state] || method.state;
      if (method.state === "model" && num(a.temperature_today) !== null) {
        text += ` · ${this._fmt(num(a.temperature_today), 1)} °C`;
      } else if (a.reason && t[a.reason]) {
        text += ` (${t[a.reason]})`;
      }
      chips.push(chip(method, method.state === "model" ? "mdi:weather-partly-cloudy" : "mdi:school-outline",
        text, method.state === "model" ? "" : "warn"));
    }
    return chips.length ? `<div class="chips">${chips.join("")}</div>` : "";
  }

  _table(entry, useCost, t) {
    const config = this._config;
    const columns = Array.isArray(config.columns) && config.columns.length
      ? COLUMNS.filter((c) => config.columns.includes(c)) : DEFAULT_COLUMNS;
    const unit = useCost ? this._symbol(entry.currency) : "kWh";
    const shown = this._periods(entry);
    const periods = config.descending ? [...shown].reverse() : shown;
    const mini = config.layout === "mini";
    const head = columns.map((c) => {
      const label = mini && c === "current" ? t.m_current : t[`c_${c}`];
      const suffix = c === "trend" ? (mini ? " %" : "") : ` <span class="u">${esc(unit)}</span>`;
      return `<th>${label}${suffix}</th>`;
    }).join("");
    const row = (state, icon, name, cells, extra = "") =>
      `<tr class="${extra}" data-entity="${esc(state.entity_id)}"><th scope="row">${
        mini ? "" : `<ha-icon icon="${icon}"></ha-icon>`}${esc(name)}</th>${cells}</tr>`;
    const bar = (value, target) => (mini ? "" : this._bar(value, target, null));
    // Mini: a bare signed figure, the unit sits in the header.
    const trend = (value, title) => {
      if (value === null) return "–";
      if (!mini) return this._pill(value, title);
      const arrow = value > 0 ? "▲ " : value < 0 ? "▼ " : "";
      return `<span class="${value > 0 ? "up" : "down"}" title="${esc(title)}">${arrow}${this._fmt(Math.abs(value), 1)}</span>`;
    };

    const rows = periods.map((period) => {
      const state = this._state(entry, `${useCost ? "cost" : "energy"}_${period}`);
      if (!state) return "";
      const a = state.attributes;
      const value = num(state.state);
      const estimate = num(a.estimate);
      const text = (v) => (useCost ? this._money(v, entry.currency, estimate) : this._energy(v, estimate)).text;
      const cells = columns.map((c) => {
        if (c === "current") return `<td class="cur">${text(value)}${bar(value, estimate)}</td>`;
        if (c === "trend") return `<td>${trend(num(a.trend), t.trend)}</td>`;
        return `<td class="${c === "estimate" ? "est" : ""}">${text(num(a[c]))}</td>`;
      }).join("");
      const label = (period === "day" && this._dayLabel(entry, state, t, mini))
        || (mini ? t[`s_${period}`] : t[period]);
      return row(state, ICONS[period], label, cells);
    });

    // The mini table stays bare unless heating is asked for explicitly.
    if ((mini ? config.hide_heating === false : !config.hide_heating) && entry.heating) {
      let first = true;
      for (const key of ["heating_month", "heating_season"]) {
        const state = this._state(entry, key);
        if (!state) continue;
        const a = state.attributes;
        const value = num(state.state);
        const expected = num(a.expected);
        // Heating is always in kWh: say so when the other rows are money.
        const text = (v) => `${this._energy(v, expected ?? value).text}${useCost && v !== null ? "<small>kWh</small>" : ""}`;
        const cells = columns.map((c) => {
          if (c === "current") return `<td class="cur">${text(value)}${bar(value, expected)}</td>`;
          if (c === "estimate") return `<td class="est" title="${esc(t.expected)}">${text(expected)}</td>`;
          if (c === "trend") return `<td>${trend(num(a.gap), t.gap_heating)}</td>`;
          return "<td>–</td>";
        }).join("");
        rows.push(row(state, ICONS[key], mini ? t[`s_${key}`] : t[key], cells, first && !mini ? "sep" : ""));
        first = false;
      }
    }
    return `<div class="scroll"><table class="table${mini ? " mini" : ""}"><thead><tr><th></th>${head}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  }

  _useCost(entry) {
    return this._config.display === "energy" ? false : entry.priced;
  }

  async _loadCharts(entry) {
    const kind = this._useCost(entry) ? "cost" : "energy";
    const wanted = this._periods(entry).filter((p) => !(entry.delayed && p === "day")).map((period) => {
      const state = this._state(entry, `${kind}_${period}`);
      return state && state.attributes.period_start
        ? { period, id: state.entity_id, estimate: entry.entities[`${kind}_${period}_estimate`],
            start: new Date(state.attributes.period_start).getTime() }
        : null;
    }).filter(Boolean);
    const key = wanted.map((w) => `${w.id}@${w.start}`).join("|");
    // Reload when a period rolls over, and every 5 minutes otherwise.
    if (this._chartsLoading || (key === this._chartsKey && Date.now() - this._chartsAt < 300000)) return;
    this._chartsLoading = true;
    this._chartsKey = key;
    this._chartsAt = Date.now();
    const series = {};
    try {
      for (const w of wanted) {
        const result = await this._hass.callWS({
          type: "recorder/statistics_during_period",
          start_time: new Date(w.start).toISOString(),
          statistic_ids: [w.estimate].filter(Boolean),
          period: RESOLUTION[w.period],
          types: ["mean"],
        });
        const pick = (id, field, at) => (result[id] || [])
          .filter((row) => row[field] !== null && row[field] !== undefined && row.start >= w.start)
          .map((row) => [at(row), row[field]]);
        // The consumption curve is rebuilt by the integration from the source
        // statistics, so it is complete even right after the installation.
        const curve = await this._hass.callWS({
          type: "wattendix/curve", entry_id: entry.entry_id, period: w.period,
        });
        const column = kind === "cost" ? 2 : 1;
        series[w.period] = {
          start: w.start,
          cur: (curve.points || []).filter((p) => p[column] !== null).map((p) => [p[0], p[column]]),
          est: pick(w.estimate, "mean", (row) => (row.start + row.end) / 2),
        };
      }
      this._series = series;
    } catch (err) {
      // Recorder unavailable: the curves keep what they had and live values still draw.
    }
    this._chartsLoading = false;
    this._signature = "";
    this._update();
  }

  _chart(entry, period, useCost, t) {
    const state = this._state(entry, `${useCost ? "cost" : "energy"}_${period}`);
    if (!state || !state.attributes.period_start) return "";
    const a = state.attributes;
    const locale = this._hass.locale?.language || "en";
    const start = new Date(a.period_start).getTime();
    const end = periodEnd(start, period);
    const now = Math.min(Math.max(Date.now(), start), end);
    const value = num(state.state);
    const estimate = num(a.estimate);
    const previous = num(a.previous);
    const average = num(a.average);
    const data = this._series[period];
    const recorded = data && data.start === start ? data : { cur: [], est: [] };
    const cur = [[start, 0], ...recorded.cur.filter((p) => p[0] < now)];
    if (value !== null) cur.push([now, value]);
    const est = recorded.est.filter((p) => p[0] < now);
    if (estimate !== null) est.push([now, estimate]);

    const top = Math.max(...cur.map((p) => p[1]), ...est.map((p) => p[1]), previous ?? 0, average ?? 0, 0.01);
    const step = niceStep(top);
    const max = Math.ceil(top / step - 1e-9) * step;
    const { w, h, l, r, t: mt, b } = CHART;
    const x = (time) => l + ((time - start) / (end - start)) * (w - l - r);
    const y = (v) => mt + (h - mt - b) * (1 - v / max);
    const path = (points) => points.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join("");
    const format = (v) => {
      const f = useCost ? this._money(v, entry.currency, estimate) : this._energy(v, estimate);
      return `${f.text} ${esc(f.unit)}`;
    };
    this._geometry[period] = { start, end, cur, est, format, locale };

    let svg = "";
    const digits = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
    for (let v = 0; v <= max + 1e-9; v += step) {
      svg += `<line class="grid" x1="${l}" x2="${w - r}" y1="${y(v)}" y2="${y(v)}"></line>`
        + `<text x="${l - 4}" y="${y(v) + 3}" text-anchor="end">${this._fmt(v, digits)}</text>`;
    }
    for (const [time, label] of xTicks(start, period, locale)) {
      svg += `<text x="${x(time)}" y="${h - 6}" text-anchor="${time === start ? "start" : "middle"}">${esc(label)}</text>`;
    }
    const flat = (v, cls) => (v === null ? ""
      : `<line class="${cls}" x1="${l}" x2="${w - r}" y1="${y(v)}" y2="${y(v)}"></line>`);
    svg += flat(previous, "l-prev") + flat(average, "l-avg");
    if (cur.length > 1) {
      svg += `<path class="a-cur" d="${path(cur)}L${x(now).toFixed(1)} ${y(0)}L${x(start)} ${y(0)}Z"></path>`
        + `<path class="l-cur" d="${path(cur)}"></path>`;
    }
    if (est.length > 1) svg += `<path class="l-est" d="${path(est)}"></path>`;
    else if (est.length) svg += `<circle cx="${x(now)}" cy="${y(est[0][1])}" r="2.2" fill="var(--wc-est)"></circle>`;
    svg += `<line class="now" x1="${x(now)}" x2="${x(now)}" y1="${mt}" y2="${h - b}"></line>`
      + `<line class="cursor" x1="0" x2="0" y1="${mt}" y2="${h - b}" visibility="hidden"></line>`;

    const item = (color, label, v) => (v === null ? ""
      : `<span><i style="background:var(${color})"></i>${label} <b>${format(v)}</b></span>`);
    return `<div class="chart">
      <div class="chart-head"><span>${esc(t[period])}</span><span class="tip"></span></div>
      <svg viewBox="0 0 ${w} ${h}" data-period="${period}" role="img" aria-label="${esc(t[period])}">${svg}</svg>
      <div class="legend">${item("--wc-cur", t.current, value)}${item("--wc-est", t.estimate, estimate)}${
        item("--wc-prev", t[`prev_${period}`], previous)}${item("--wc-avg", t[`avg_${period}`], average)}</div>
    </div>`;
  }

  _hover(event) {
    const svg = event.target.closest ? event.target.closest("svg[data-period]") : null;
    if (!svg) return;
    const g = this._geometry[svg.dataset.period];
    if (!g) return;
    const box = svg.getBoundingClientRect();
    const { w, l, r } = CHART;
    const view = ((event.clientX - box.left) / box.width) * w;
    const time = g.start + ((Math.min(Math.max(view, l), w - r) - l) / (w - l - r)) * (g.end - g.start);
    const nearest = (points) => points.reduce(
      (best, p) => (best === null || Math.abs(p[0] - time) < Math.abs(best[0] - time) ? p : best), null);
    const cur = nearest(g.cur);
    if (!cur) return;
    const est = nearest(g.est);
    const period = svg.dataset.period;
    const options = period === "hour" || period === "day" ? { hour: "2-digit", minute: "2-digit" }
      : period === "week" ? { weekday: "short", hour: "2-digit", minute: "2-digit" }
      : { day: "numeric", month: "short" };
    const t = TEXT[lang(this._hass)];
    const when = new Intl.DateTimeFormat(g.locale, options).format(new Date(cur[0]));
    const tip = svg.parentElement.querySelector(".tip");
    tip.innerHTML = `${esc(when)} · ${t.current} ${g.format(cur[1])}${
      est && Math.abs(est[0] - cur[0]) < (g.end - g.start) / 20 ? ` · ${t.estimate} ${g.format(est[1])}` : ""}`;
    const cursor = svg.querySelector(".cursor");
    const cx = l + ((cur[0] - g.start) / (g.end - g.start)) * (w - l - r);
    cursor.setAttribute("x1", cx);
    cursor.setAttribute("x2", cx);
    cursor.setAttribute("visibility", "visible");
  }

  _render(entry) {
    const t = TEXT[lang(this._hass)];
    const config = this._config;
    let body;
    if (!entry) {
      body = `<div class="note">${this._info ? t.missing : t.loading}</div>`;
    } else {
      const useCost = this._useCost(entry);
      const tiles = this._periods(entry).map((p) => this._periodTile(entry, p, useCost, t));
      if (!config.hide_heating && entry.heating) {
        tiles.push(this._heatingTile(entry, "heating_month", t), this._heatingTile(entry, "heating_season", t));
      }
      const charts = config.charts
        ? `<div class="charts">${this._periods(entry).filter((p) => !(entry.delayed && p === "day"))
          .map((p) => this._chart(entry, p, useCost, t)).join("")}</div>` : "";
      const mini = config.layout === "mini";
      const main = config.layout === "table" || mini ? this._table(entry, useCost, t)
        : `<div class="tiles">${tiles.join("")}</div>`;
      body = `${main}${charts}${(mini ? config.hide_info !== false : config.hide_info) ? "" : this._chips(entry, t)}`;
    }
    const title = config.title ? `<div class="title">${esc(config.title)}</div>` : "";
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card class="${config.layout === "mini" ? "is-mini" : ""}">${title}${body}</ha-card>`;
  }
}

if (!customElements.get("wattendix-card")) {
  customElements.define("wattendix-card", WattendixCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "wattendix-card",
    name: "Wattendix",
    description: "Your electricity bill, live and forecast / Votre facture d'électricité en direct",
    preview: false,
    documentationURL: "https://github.com/Amify-Studio/wattendix",
  });
}
