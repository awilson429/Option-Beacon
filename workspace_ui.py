"""Reusable presentation helpers for the four OptionBeacon workspaces."""

from datetime import datetime
from html import escape


WORKSPACE_CSS = """
<style>
.ob-workspace-strip {
  align-items:center;background:#10151b;border:1px solid #343c46;border-radius:10px;
  display:flex;flex-wrap:wrap;gap:.5rem 1rem;margin:.25rem 0 .85rem;padding:.55rem .75rem;
}
.ob-workspace-status {font-size:.82rem;font-weight:800;letter-spacing:.04em;text-transform:uppercase;}
.ob-workspace-status-open {color:#70d39b}.ob-workspace-status-closed {color:#b5bcc5}
.ob-workspace-time {color:#aeb7c2;font-size:.82rem}
.ob-quick-actions {
  display:grid;gap:.45rem;grid-template-columns:repeat(6,minmax(0,1fr));margin:.5rem 0 1rem;
}
.ob-quick-action {
  background:#11161c;border:1px solid #39414b;border-radius:8px;color:#dce1e6 !important;
  font-size:.8rem;font-weight:700;padding:.55rem .45rem;text-align:center;text-decoration:none !important;
  white-space:normal;overflow-wrap:anywhere;
}
.ob-quick-action:hover {border-color:#c8a84e;color:#f7df9a !important}
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
@media (max-width:900px) {.ob-quick-actions{grid-template-columns:repeat(3,minmax(0,1fr));}}
@media (max-width:620px) {
  .ob-quick-actions{grid-template-columns:repeat(2,minmax(0,1fr))}
  .ob-signal-row{grid-template-columns:.65fr .7fr 1.4fr .5fr}
  .ob-signal-time{display:none}
}
</style>
"""


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
    return f'<nav class="ob-quick-actions" aria-label="Quick actions">{links}</nav>'


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
