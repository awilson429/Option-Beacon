"""Reusable presentation helpers for the four OptionBeacon workspaces."""

from datetime import datetime
from html import escape


WORKSPACE_CSS = """
<style>
[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"] {display:none}
[data-testid="stAppViewContainer"] .main .block-container {
  max-width:1024px;padding-left:24px;padding-right:24px;
}
.ob-desk-header {
  align-items:flex-start;display:flex;gap:1rem;justify-content:space-between;
  margin:.15rem 0 1.15rem;
}
.ob-desk-title {color:#f5f6f8;font-size:clamp(2rem,4vw,3rem);font-weight:760;line-height:1.05;}
.ob-desk-subtitle {color:#aeb7c2;font-size:clamp(.9rem,1.4vw,1.08rem);margin-top:.55rem;}
.ob-desk-controls {align-items:center;display:flex;flex-wrap:wrap;gap:.55rem;justify-content:flex-end;}
.ob-desk-market {color:#60d985;font-size:.8rem;font-weight:800;letter-spacing:.025em;text-transform:uppercase;}
.ob-desk-market::before {background:currentColor;border-radius:50%;content:"";display:inline-block;height:.55rem;margin-right:.45rem;width:.55rem;}
.ob-desk-market-closed {color:#9ba3ad;}
.ob-desk-clock {color:#aeb7c2;font-size:.82rem;margin-right:.35rem;}
.ob-desk-action {
  background:#11161c;border:1px solid #343c46;border-radius:8px;color:#e7eaee !important;
  font-size:.82rem;font-weight:700;padding:.55rem .8rem;text-decoration:none !important;
}
.ob-desk-action:hover {border-color:#c8a84e;color:#f7df9a !important;}
.ob-desk-tabs {
  border-bottom:1px solid #303741;display:flex;gap:clamp(1.2rem,4vw,3rem);
  margin:0 0 1.2rem;overflow-x:auto;padding:0 .05rem;
}
.ob-desk-tab {
  color:#aeb7c2;font-size:.92rem;font-weight:650;padding:.7rem .2rem .75rem;
  text-decoration:none !important;white-space:nowrap;
}
.ob-desk-tab-active {border-bottom:2px solid #e0b83f;color:#f0c84e !important;}
.ob-panel-shell {
  background:linear-gradient(145deg,#111820,#0d1319);border:1px solid #343c46;
  border-radius:11px;margin:.7rem 0;padding:1rem;
}
.ob-panel-title {
  color:#bcc4ce;font-size:.82rem;font-weight:800;letter-spacing:.04em;
  margin-bottom:.55rem;text-transform:uppercase;
}
.ob-panel-header {align-items:center;display:flex;justify-content:space-between;margin-bottom:.8rem}
.ob-panel-header .ob-panel-title {margin:0}
.ob-panel-link {color:#efc64b !important;font-size:.8rem;text-decoration:none !important}
.ob-position-empty {
  align-items:center;border:1px dashed #3c4651;border-radius:8px;color:#aeb7c2;
  display:flex;flex-direction:column;justify-content:center;min-height:13rem;padding:1rem;text-align:center;
}
.ob-position-icon {color:#67717d;font-size:2.6rem;line-height:1}
.ob-position-empty strong {color:#b8c0c9;font-size:1rem;margin-top:.75rem}
.ob-position-empty span {font-size:.84rem;line-height:1.5;margin-top:.45rem;max-width:14rem}
.ob-paper-settings {
  border:1px solid #3b4550;border-radius:8px;color:#e1e5e9 !important;display:block;
  font-size:.82rem;margin:.8rem auto 0;max-width:12rem;padding:.6rem;text-align:center;text-decoration:none !important;
}
.ob-workspace-strip {
  align-items:center;background:#10151b;border:1px solid #343c46;border-radius:10px;
  display:flex;flex-wrap:wrap;gap:.5rem 1rem;margin:.25rem 0 .85rem;padding:.55rem .75rem;
}
.ob-workspace-status {font-size:.82rem;font-weight:800;letter-spacing:.04em;text-transform:uppercase;}
.ob-workspace-status-open {color:#70d39b}.ob-workspace-status-closed {color:#b5bcc5}
.ob-workspace-time {color:#aeb7c2;font-size:.82rem}
.ob-quick-actions {
  background:linear-gradient(145deg,#111820,#0d1319);border:1px solid #343c46;border-radius:11px;
  display:grid;gap:0;grid-template-columns:repeat(6,minmax(0,1fr));margin:.5rem 0 1rem;
  padding:.7rem .55rem;
}
.ob-quick-action {
  border-right:1px solid rgba(255,255,255,.08);color:#dce1e6 !important;
  font-size:.8rem;font-weight:700;padding:.55rem .45rem;text-align:center;text-decoration:none !important;
  white-space:normal;overflow-wrap:anywhere;
}
.ob-quick-action:last-child {border-right:0}
.ob-quick-action:hover {color:#f7df9a !important}
.ob-signal-list {border:1px solid #343c46;border-radius:10px;padding:.2rem .7rem}
.ob-signal-row {
  align-items:center;border-bottom:1px solid rgba(255,255,255,.08);display:grid;gap:.55rem;
  grid-template-columns:minmax(3.5rem,.55fr) minmax(4.5rem,.7fr) minmax(7rem,1.5fr) .45fr .6fr;
  padding:.55rem 0;
}
.ob-signal-row:last-child {border-bottom:0}
.ob-signal-symbol {color:#f4f5f7;font-weight:800}
.ob-signal-status {color:#e0c56f;font-size:.72rem;font-weight:800}
.ob-signal-direction,.ob-signal-time {color:#aeb7c2;font-size:.78rem;overflow-wrap:anywhere}
.ob-signal-confidence {color:#f4f5f7;font-size:.8rem;font-weight:750}
.ob-focus-tip {
  align-items:center;background:linear-gradient(145deg,#111820,#0d1319);
  border:1px solid #343c46;border-radius:11px;color:#d8dde3;display:flex;
  flex-wrap:wrap;font-size:.88rem;gap:.5rem;margin:1rem 0;padding:.8rem 1rem;
}
.ob-focus-tip strong {color:#efc64b}.ob-focus-tip a {color:#efc64b;margin-left:auto;text-decoration:none}
@media (max-width:900px) {.ob-quick-actions{grid-template-columns:repeat(3,minmax(0,1fr));}}
@media (max-width:620px) {
  .ob-desk-header {flex-direction:column}
  .ob-desk-controls {justify-content:flex-start}
  .ob-desk-tabs {gap:1.2rem}
  .ob-quick-actions{grid-template-columns:repeat(2,minmax(0,1fr))}
  .ob-quick-action {border-bottom:1px solid rgba(255,255,255,.08);border-right:0}
  .ob-signal-row{grid-template-columns:.65fr .7fr 1.4fr .5fr}
  .ob-signal-time{display:none}
}
</style>
"""


def trade_desk_header_markup(market_open, now):
    market_label = "Market Open" if market_open else "Market Closed"
    market_class = "" if market_open else " ob-desk-market-closed"
    timestamp = now.strftime("%I:%M:%S %p ET").lstrip("0")
    return (
        '<header class="ob-desk-header"><div>'
        '<div class="ob-desk-title">Trade Desk</div>'
        '<div class="ob-desk-subtitle">Focus on the best setups. Trade with a plan.</div>'
        '</div><div class="ob-desk-controls">'
        f'<span class="ob-desk-market{market_class}">{escape(market_label)}</span>'
        f'<span class="ob-desk-clock">{escape(timestamp)}</span>'
        '<a class="ob-desk-action" href="?page=trade-desk">↻&nbsp; Refresh</a>'
        '<a class="ob-desk-action" href="?page=journal">▽&nbsp; Filters</a>'
        '<a class="ob-desk-action" href="#more">•••</a>'
        "</div></header>"
    )


def trade_desk_tabs_markup():
    tabs = (
        ("Overview", "?page=trade-desk", True),
        ("Signals", "#recent-signals", False),
        ("Positions", "?page=positions", False),
        ("Journal", "?page=journal", False),
        ("Analytics", "?page=journal#analytics", False),
    )
    links = "".join(
        f'<a class="ob-desk-tab{" ob-desk-tab-active" if active else ""}" '
        f'href="{escape(target)}">{escape(label)}</a>'
        for label, target, active in tabs
    )
    return f'<nav class="ob-desk-tabs" aria-label="Trade Desk sections">{links}</nav>'


def focus_tip_markup():
    return (
        '<div class="ob-focus-tip"><strong>Focus Tip:</strong>'
        '<span>Wait for confirmation, respect your plan, and manage risk.</span>'
        '<a href="?page=journal">View trading checklist&nbsp; ↗</a></div>'
    )


def market_status_markup(market_open, now):
    label = "Market Open" if market_open else "Market Closed"
    treatment = "open" if market_open else "closed"
    timestamp = now.strftime("%I:%M:%S %p ET").lstrip("0")
    return (
        '<div class="ob-workspace-strip">'
        f'<span class="ob-workspace-status ob-workspace-status-{treatment}">{escape(label)}</span>'
        f'<span class="ob-workspace-time">{escape(timestamp)}</span>'
        '<span class="ob-workspace-time">Refreshes on app rerun</span></div>'
    )


def quick_actions_markup():
    actions = (
        ("New Scan", "?page=trade-desk"),
        ("Watchlist", "#watchlist"),
        ("Market Overview", "#market-overview"),
        ("Open Positions", "?page=positions"),
        ("Journal", "?page=journal"),
        ("Developer Tools", "?page=developer-tools"),
    )
    links = "".join(
        f'<a class="ob-quick-action" href="{escape(target)}">{escape(label)}</a>'
        for label, target in actions
    )
    return (
        '<section class="ob-panel-shell"><div class="ob-panel-title">Quick Actions</div>'
        f'<nav class="ob-quick-actions" aria-label="Quick actions">{links}</nav></section>'
    )


def _record_time(record):
    value = getattr(record, "timestamp", None)
    return value if isinstance(value, datetime) else datetime.min


def recent_signal_records(records, limit=5):
    return sorted(records, key=_record_time, reverse=True)[:limit]


def recent_signals_markup(records):
    rows = []
    for record in recent_signal_records(records):
        entered = getattr(record, "entry_time", None)
        exited = getattr(record, "exit_time", None)
        reason = getattr(record, "exit_reason", None)
        status = (
            "NEVER TRIGGERED"
            if reason == "NEVER_TRIGGERED"
            else "CLOSED"
            if exited
            else "OPEN"
            if entered
            else "WATCH"
        )
        direction = str(getattr(record, "direction", "—") or "—")
        option_bias = "CALL" if direction == "Bullish" else "PUT" if direction == "Bearish" else ""
        confidence = getattr(record, "confidence", None)
        confidence_text = f"{float(confidence):.0f}%" if confidence is not None else "—"
        timestamp = getattr(record, "timestamp", None)
        time_text = timestamp.strftime("%I:%M %p").lstrip("0") if timestamp else "—"
        rows.append(
            '<div class="ob-signal-row">'
            f'<span class="ob-signal-symbol">{escape(str(getattr(record, "symbol", "—")))}</span>'
            f'<span class="ob-signal-status">{escape(status)}</span>'
            f'<span class="ob-signal-direction">{escape(f"{direction} {option_bias}".strip())}</span>'
            f'<span class="ob-signal-confidence">{escape(confidence_text)}</span>'
            f'<span class="ob-signal-time">{escape(time_text)}</span></div>'
        )
    return '<div class="ob-signal-list">' + "".join(rows) + "</div>"


def open_positions_panel_markup(records):
    records = list(records)
    if records:
        rows = "".join(
            '<div class="ob-signal-row">'
            f'<span class="ob-signal-symbol">{escape(str(record.symbol))}</span>'
            '<span class="ob-signal-status">OPEN</span>'
            f'<span class="ob-signal-direction">{escape(str(record.direction))}</span>'
            f'<span class="ob-signal-confidence">{escape(str(getattr(record, "confidence", "—")))}%</span>'
            '<span class="ob-signal-time">›</span></div>'
            for record in records[:5]
        )
        body = f'<div class="ob-signal-list">{rows}</div>'
    else:
        body = (
            '<div class="ob-position-empty"><div class="ob-position-icon">▱</div>'
            '<strong>No open positions</strong>'
            '<span>When you take a trade, it will appear here.</span></div>'
            '<a class="ob-paper-settings" href="?page=positions">⚙&nbsp; Paper Trade Settings</a>'
        )
    return (
        '<section class="ob-panel-shell"><div class="ob-panel-header">'
        '<div class="ob-panel-title">Open Positions</div>'
        '<a class="ob-panel-link" href="?page=positions">View all</a></div>'
        f"{body}</section>"
    )


def recent_signals_panel_markup(records):
    records = list(records)
    shown = recent_signal_records(records)
    body = recent_signals_markup(shown) if shown else (
        '<div class="ob-position-empty"><strong>No recent signals</strong></div>'
    )
    return (
        '<section class="ob-panel-shell"><div class="ob-panel-header">'
        '<div class="ob-panel-title">Recent Signals</div>'
        '<a class="ob-panel-link" href="?page=journal">View all</a></div>'
        f'{body}<div class="board-note">Showing {len(shown)} of {len(records)} signals</div></section>'
    )
