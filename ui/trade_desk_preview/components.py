"""Reusable markup and rendering functions for the local Trade Desk preview."""

from __future__ import annotations

from html import escape
from textwrap import dedent

from .sample_data import ConfidenceFactor, DevelopingSetup, RecentSignal, TradeDeskPreview


_ICONS = {
    "refresh": '<path d="M20 11a8 8 0 1 0 1.3 4.4"/><path d="M20 4v7h-7"/>',
    "filter": '<path d="M4 5h16l-6.5 7.2V19l-3 1v-7.8z"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "scan": '<circle cx="11" cy="11" r="6"/><path d="m16 16 4 4M11 2v3M2 11h3"/>',
    "watch": '<path d="m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    "market": '<path d="M4 20V13M9.3 20V8M14.7 20V11M20 20V4"/>',
    "positions": '<path d="M4 8h16v12H4zM8 8V5h8v3"/>',
    "journal": '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 0-3 1z"/><path d="M5 4v17"/>',
    "tools": '<path d="M14.7 6.3a4 4 0 0 0-5-5L12 3.6 8.5 7.1 6.2 4.8a4 4 0 0 0 5 5L4 17l3 3 7.3-7.3a4 4 0 0 0 5-5L17 10l-3-3z"/>',
    "inbox": '<path d="M4 7h16l2 7v6H2v-6z"/><path d="M2 14h6l2 3h4l2-3h6"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a8 8 0 0 0-1.8-1L14.4 3h-4l-.4 3a8 8 0 0 0-1.8 1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2L4 14.5l2 3.4 2.4-1a8 8 0 0 0 1.8 1l.4 3h4l.4-3a8 8 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1z"/>',
    "bulb": '<path d="M9 18h6M10 22h4M8.5 15.5A7 7 0 1 1 15.5 15.5L15 18H9z"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v7H4V6h7"/>',
    "chevron": '<path d="m9 6 6 6-6 6"/>',
    "down": '<path d="m7 9 5 5 5-5"/>',
}


def icon_markup(name: str, *, size: int = 20, css_class: str = "") -> str:
    """Return a dependency-free SVG icon from the preview's local icon set."""
    paths = _ICONS.get(name)
    if paths is None:
        raise ValueError(f"Unknown preview icon: {name}")
    class_attr = f' class="{escape(css_class)}"' if css_class else ""
    return (
        f'<svg{class_attr} aria-hidden="true" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        f"{paths}</svg>"
    )


def logo_markup() -> str:
    """Return the replaceable Concept-4-inspired geometric beacon mark."""
    return (
        '<div class="preview-brand-mark" aria-hidden="true">'
        '<svg viewBox="0 0 48 48" role="img">'
        '<path class="preview-logo-orbit" d="M8 21c4-7 9.3-10.5 16-10.5S36 14 40 21"/>'
        '<path class="preview-logo-orbit preview-logo-orbit-inner" d="M14 22c2.8-4.1 6.1-6.2 10-6.2s7.2 2.1 10 6.2"/>'
        '<path class="preview-logo-tower" d="m20.5 23-3.8 17h14.6l-3.8-17z"/>'
        '<path class="preview-logo-cut" d="M19.2 31h9.6M18 37h12"/>'
        '<path class="preview-logo-spark" d="m24 5 2.1 3.9L30 11l-3.9 2.1L24 17l-2.1-3.9L18 11l3.9-2.1z"/>'
        "</svg></div>"
    )


def format_price(value: float) -> str:
    """Format a finite sample price consistently."""
    return f"${float(value):,.2f}"


def format_entry_zone(setup: DevelopingSetup) -> str:
    """Format the setup's entry range."""
    return f"{format_price(setup.entry_zone_low)}–{format_price(setup.entry_zone_high)}"


def status_class(status: str) -> str:
    """Map display-only status text to a semantic preview accent."""
    normalized = str(status or "").strip().upper()
    if normalized in {"WATCH"}:
        return "preview-watch"
    if normalized in {"READY", "OPEN"}:
        return "preview-positive"
    if normalized in {"WAIT", "STOP", "EXIT"}:
        return "preview-negative"
    return "preview-neutral"


def confidence_factor_markup(factor: ConfidenceFactor) -> str:
    """Render one sample confidence factor without implying production scoring."""
    state = "positive" if factor.positive else "missing"
    symbol = "✓" if factor.positive else "–"
    return (
        f'<div class="preview-factor preview-factor-{state}">'
        f'<span aria-hidden="true">{symbol}</span><span>{escape(factor.label)}</span></div>'
    )


def signal_row_markup(signal: RecentSignal) -> str:
    """Render one recent-signal row from typed sample data."""
    return (
        '<div class="preview-signal-row">'
        f'<div class="preview-signal-symbol">{escape(signal.symbol)}</div>'
        f'<div><span class="preview-badge {status_class(signal.status)}">'
        f'{escape(signal.status)}</span></div>'
        f'<div class="preview-signal-direction">{escape(signal.direction)} '
        f'{escape(signal.option_type)}</div>'
        f'<div class="preview-signal-confidence">{signal.confidence}%</div>'
        f'<div class="preview-signal-time">{escape(signal.time_label)}</div>'
        f'<div class="preview-chevron">{icon_markup("chevron", size=16)}</div>'
        "</div>"
    )


def metric_markup(label: str, value: str, treatment: str = "") -> str:
    """Render one aligned trade-plan metric."""
    treatment_class = f" preview-{treatment}" if treatment else ""
    return (
        f'<div class="preview-plan-metric{treatment_class}">'
        f'<div class="preview-metric-label">{escape(label)}</div>'
        f'<div class="preview-metric-value">{escape(value)}</div></div>'
    )


def setup_card_markup(setup: DevelopingSetup) -> str:
    """Render the featured setup using only supplied presentation data."""
    metrics = "".join(
        (
            metric_markup("Entry Zone", format_entry_zone(setup)),
            metric_markup("Confirmation", setup.confirmation),
            metric_markup("Max Entry", format_price(setup.maximum_entry)),
            metric_markup("Stop", format_price(setup.stop), "negative"),
            metric_markup("Target 1", format_price(setup.target_1), "positive"),
            metric_markup("Target 2", format_price(setup.target_2), "positive"),
            metric_markup("Confidence", f"{setup.confidence}%", "watch"),
            metric_markup("Risk / Reward", setup.risk_reward),
            metric_markup("Timing", setup.timing),
        )
    )
    factors = "".join(confidence_factor_markup(item) for item in setup.confidence_factors)
    return dedent(
        f"""
        <div class="preview-card preview-setup-card">
          <div class="preview-eyebrow-row">
            <div class="preview-eyebrow">BEST DEVELOPING SETUP</div>
            <div class="preview-sample-chip">SAMPLE DATA</div>
          </div>
          <div class="preview-setup-grid">
            <div class="preview-setup-identity">
              <div class="preview-symbol">{escape(setup.symbol)}</div>
              <div class="preview-direction">{escape(setup.direction)} {escape(setup.option_type)}</div>
              <div class="preview-setup-name">{escape(setup.setup)}</div>
              <div class="preview-status-line">
                <span class="preview-badge preview-watch">{escape(setup.status)}</span>
                <span>{escape(setup.status_detail)}</span>
              </div>
            </div>
            <div class="preview-plan-area">
              <div class="preview-plan-grid">{metrics}</div>
              <div class="preview-confidence-block">
                <div class="preview-confidence-heading">
                  <span>CONFIDENCE BREAKDOWN</span>
                  <span>Preview factors</span>
                </div>
                <div class="preview-factor-grid">{factors}</div>
              </div>
              <button class="preview-plan-link" type="button">
                View full trade plan {icon_markup("down", size=17)}
              </button>
            </div>
            <aside class="preview-reasoning">
              <div class="preview-reason-section">
                <div class="preview-reason-label">WHY THIS SETUP</div>
                <p>{escape(setup.reason)}</p>
              </div>
              <div class="preview-reason-section">
                <div class="preview-reason-label">WHAT&rsquo;S MISSING</div>
                <p>{escape(setup.missing_confirmation)}</p>
              </div>
              <div class="preview-reason-section">
                <div class="preview-reason-label">INVALIDATION</div>
                <p>{escape(setup.invalidation)}</p>
              </div>
            </aside>
          </div>
        </div>
        """
    )


def action_markup(icon: str, label: str) -> str:
    """Render a preview-only quick action with a coherent local SVG icon."""
    return (
        '<button class="preview-action" type="button">'
        f'{icon_markup(icon, size=23)}<span>{escape(label)}</span></button>'
    )


def trade_desk_markup(data: TradeDeskPreview) -> str:
    """Build the complete preview shell without accessing application state."""
    signal_rows = "".join(signal_row_markup(signal) for signal in data.recent_signals)
    actions = "".join(
        action_markup(icon, label)
        for icon, label in (
            ("scan", "New Scan"),
            ("watch", "Watchlist"),
            ("market", "Market Overview"),
            ("positions", "Open Positions"),
            ("journal", "Journal"),
            ("tools", "Developer Tools"),
        )
    )
    return dedent(
        f"""
        <main class="preview-shell">
          <div class="preview-local-notice">LOCAL UI PREVIEW</div>
          <header class="preview-header">
            <div class="preview-branding">
              <div class="preview-brand-row">
                {logo_markup()}
                <div class="preview-wordmark" aria-label="OptionBeacon">
                  <span>OPTION</span><span>BEACON</span>
                </div>
              </div>
            </div>
            <div class="preview-header-right">
              <div class="preview-market-line">
                <span class="preview-market-dot"></span>
                <span class="preview-market-status">{escape(data.market_status)}</span>
                <span class="preview-time">{escape(data.eastern_time)}</span>
              </div>
              <div class="preview-controls">
                <button type="button">{icon_markup("refresh")}<span>Refresh</span></button>
                <button type="button">{icon_markup("filter")}<span>Filters</span></button>
                <button type="button" aria-label="More options">{icon_markup("more")}</button>
              </div>
            </div>
          </header>

          <nav class="preview-tabs" aria-label="Trade Desk sections">
            <span class="preview-tab preview-tab-active">Trade Desk</span>
            <span class="preview-tab">Signals</span>
            <span class="preview-tab">Positions</span>
            <span class="preview-tab">Journal</span>
            <span class="preview-tab">Analytics</span>
            <span class="preview-tab">Settings</span>
          </nav>

          {setup_card_markup(data.setup)}

          <div class="preview-card preview-quick-actions">
            <div class="preview-eyebrow">QUICK ACTIONS</div>
            <div class="preview-action-grid">{actions}</div>
          </div>

          <div class="preview-lower-grid">
            <div class="preview-card preview-open-card">
              <div class="preview-panel-heading">
                <span>OPEN POSITIONS</span><a>View all</a>
              </div>
              <div class="preview-empty-position">
                <div class="preview-empty-icon">{icon_markup("inbox", size=48)}</div>
                <strong>No open positions</strong>
                <span>When you take a trade,<br>it will appear here.</span>
              </div>
              <button class="preview-settings" type="button">
                {icon_markup("settings", size=18)}<span>Paper Trade Settings</span>
              </button>
            </div>

            <div class="preview-card preview-signals-card">
              <div class="preview-panel-heading">
                <span>RECENT SIGNALS</span><a>View all</a>
              </div>
              <div class="preview-signal-list">{signal_rows}</div>
              <div class="preview-signal-count">
                Showing {len(data.recent_signals)} of {data.signal_count} signals
              </div>
            </div>
          </div>

          <div class="preview-card preview-focus-tip">
            <span class="preview-bulb">{icon_markup("bulb", size=28)}</span>
            <div><strong>Focus Tip:</strong> {escape(data.focus_tip)}</div>
            <a>View trading checklist {icon_markup("external", size=16)}</a>
          </div>
        </main>
        """
    )


def render_trade_desk_preview(st_module, data: TradeDeskPreview) -> None:
    """Render the complete local-only preview."""
    markup = trade_desk_markup(data).replace("\n", "")
    st_module.markdown(markup, unsafe_allow_html=True)
