"""Reusable markup and rendering functions for the local Trade Desk preview."""

from __future__ import annotations

from datetime import datetime
from html import escape
from textwrap import dedent

from .sample_data import (
    ConfidenceFactor,
    DevelopingSetup,
    EASTERN,
    OpeningChecklistItem,
    PremarketSetup,
    PremarketWatchlistItem,
    RecentSignal,
    SessionMode,
    TradeDeskPreview,
    format_gap,
    format_relative_activity,
    preview_data,
    readiness_explanation,
    resolve_session_mode,
)


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


def readiness_class(status: str) -> str:
    """Map a premarket readiness label to its semantic presentation class."""
    normalized = str(status or "").strip().upper()
    return {
        "EARLY": "preview-readiness-early",
        "DEVELOPING": "preview-readiness-developing",
        "NEAR CONFIRMATION": "preview-readiness-near",
        "READY FOR OPEN": "preview-readiness-ready",
        "INVALIDATED": "preview-readiness-invalid",
    }.get(normalized, "preview-neutral")


def readiness_badge_markup(status: str) -> str:
    """Render a reusable readiness badge with a concise explanation."""
    normalized = str(status).strip().upper()
    return (
        f'<span class="preview-readiness-badge {readiness_class(normalized)}" '
        f'title="{escape(readiness_explanation(normalized))}">{escape(normalized)}</span>'
    )


def confidence_factor_markup(factor: ConfidenceFactor) -> str:
    """Render one sample confidence factor without implying production scoring."""
    state = "positive" if factor.positive else "missing"
    symbol = "✓" if factor.positive else "–"
    return (
        f'<div class="preview-factor preview-factor-{state}">'
        f'<span aria-hidden="true">{symbol}</span><span>{escape(factor.label)}</span></div>'
    )


def opening_checklist_markup(item: OpeningChecklistItem) -> str:
    """Render one preview-only opening checklist item."""
    return (
        '<div class="preview-opening-item"><span aria-hidden="true">✓</span>'
        f'<span>{escape(item.label)}</span></div>'
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
                <div class="preview-confidence-heading"><span>CONFIDENCE BREAKDOWN</span><span>Preview factors</span></div>
                <div class="preview-factor-grid">{factors}</div>
              </div>
              <button class="preview-plan-link" type="button">View full trade plan {icon_markup("down", size=17)}</button>
            </div>
            <aside class="preview-reasoning">
              <div class="preview-reason-section"><div class="preview-reason-label">WHY THIS SETUP</div><p>{escape(setup.reason)}</p></div>
              <div class="preview-reason-section"><div class="preview-reason-label">WHAT&rsquo;S MISSING</div><p>{escape(setup.missing_confirmation)}</p></div>
              <div class="preview-reason-section"><div class="preview-reason-label">INVALIDATION</div><p>{escape(setup.invalidation)}</p></div>
            </aside>
          </div>
        </div>
        """
    )


def premarket_setup_markup(setup: PremarketSetup) -> str:
    """Render the dedicated local-only premarket planning hero."""
    overview = "".join(
        (
            metric_markup("Premarket Price", format_price(setup.premarket_price)),
            metric_markup("Prior Close", format_price(setup.prior_close)),
            metric_markup("Gap", format_gap(setup.gap_percent), "positive" if setup.gap_percent > 0 else "negative"),
            metric_markup("Premarket High", format_price(setup.premarket_high)),
            metric_markup("Premarket Low", format_price(setup.premarket_low)),
            metric_markup("Premarket Range", format_price(setup.premarket_high - setup.premarket_low)),
            metric_markup("Premarket Volume", f"{setup.premarket_volume / 1_000_000:.2f}M"),
            metric_markup("Relative Activity", format_relative_activity(setup.relative_activity), "info"),
            metric_markup("Readiness", f"{setup.readiness_score}%", "watch"),
        )
    )
    plan = "".join(
        (
            metric_markup("Key Support", format_price(setup.key_support)),
            metric_markup("Key Resistance", format_price(setup.key_resistance)),
            metric_markup("Opening Trigger", setup.opening_trigger),
            metric_markup("Confirmation", setup.confirmation),
            metric_markup("Maximum Chase", format_price(setup.maximum_chase), "watch"),
            metric_markup("Invalidation", format_price(setup.invalidation), "negative"),
            metric_markup("Target 1", format_price(setup.target_1), "positive"),
            metric_markup("Target 2", format_price(setup.target_2), "positive"),
            metric_markup("Risk / Reward", setup.risk_reward),
        )
    )
    factors = "".join(confidence_factor_markup(item) for item in setup.readiness_factors)
    checklist = "".join(opening_checklist_markup(item) for item in setup.opening_checklist)
    return dedent(
        f"""
        <div class="preview-card preview-premarket-card">
          <div class="preview-eyebrow-row">
            <div class="preview-eyebrow">BEST PREMARKET SETUP</div>
            <div class="preview-sample-chip">SYNTHETIC PREVIEW</div>
          </div>
          <div class="preview-premarket-top">
            <div class="preview-premarket-identity">
              <div class="preview-symbol">{escape(setup.symbol)}</div>
              <div class="preview-direction preview-bullish">{escape(setup.direction)} {escape(setup.option_type)}</div>
              <div class="preview-setup-name">{escape(setup.setup)}</div>
              <div class="preview-status-stack">
                {readiness_badge_markup(setup.status)}
                <span>{escape(readiness_explanation(setup.status))}</span>
              </div>
            </div>
            <div class="preview-premarket-overview">
              <div class="preview-plan-grid">{overview}</div>
              <div class="preview-expected-open">
                <span>EXPECTED OPENING BEHAVIOR</span><p>{escape(setup.expected_open)}</p>
              </div>
            </div>
          </div>
          <div class="preview-premarket-details">
            <div class="preview-premarket-plan">
              <div class="preview-subheading">OPENING TRADE PLAN</div>
              <div class="preview-plan-grid">{plan}</div>
              <div class="preview-confidence-block preview-readiness-block">
                <div class="preview-confidence-heading">
                  <span>PREMARKET READINESS</span><span>Preview factors · {setup.readiness_score}%</span>
                </div>
                <div class="preview-factor-grid">{factors}</div>
              </div>
            </div>
            <aside class="preview-opening-panel">
              <div class="preview-subheading">WHAT TO WATCH AT THE OPEN</div>
              <div class="preview-opening-list">{checklist}</div>
              <div class="preview-opening-note">Plan only. Wait for regular-session confirmation before considering entry.</div>
            </aside>
          </div>
        </div>
        """
    )


def premarket_watchlist_row_markup(item: PremarketWatchlistItem) -> str:
    """Render one aligned synthetic premarket watchlist row."""
    return (
        '<div class="preview-premarket-row">'
        f'<strong>{escape(item.symbol)}</strong>'
        f'<span>{escape(item.direction)} {escape(item.option_type)}</span>'
        f'<span class="preview-gap {"preview-positive" if item.gap_percent > 0 else "preview-negative"}">{format_gap(item.gap_percent)}</span>'
        f'<span>{escape(item.volume_label)}</span>'
        f'{readiness_badge_markup(item.readiness)}'
        f'<span>{escape(item.trigger)}</span>'
        f'<span class="preview-signal-time">{escape(item.updated_time)}</span>'
        '</div>'
    )


def after_hours_markup(data: TradeDeskPreview) -> str:
    """Render the restrained end-of-session review surface."""
    summary = data.after_hours
    return dedent(
        f"""
        <div class="preview-card preview-after-card">
          <div class="preview-eyebrow-row"><div class="preview-eyebrow">AFTER-HOURS REVIEW</div><div class="preview-sample-chip">SAMPLE REVIEW</div></div>
          <div class="preview-after-heading"><div><span>SESSION COMPLETE</span><h2>Review, journal, prepare.</h2></div><div class="preview-after-result"><span>BEST CLOSED RESULT</span><strong>{summary.closed_trade_result:+.2f}%</strong></div></div>
          <div class="preview-after-grid">
            <div><span>STRONGEST SETUP</span><p>{escape(summary.strongest_setup)}</p></div>
            <div><span>MISSED SETUP</span><p>{escape(summary.missed_setup)}</p></div>
            <div><span>NEXT-SESSION WATCH</span><p>{escape(summary.next_session_watch)}</p></div>
            <div><span>JOURNAL REMINDER</span><p>{escape(summary.journal_reminder)}</p></div>
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
    if data.session_mode is SessionMode.PREMARKET:
        action_specs = (
            ("refresh", "Refresh Premarket"), ("watch", "Premarket Watchlist"),
            ("market", "Market Overview"), ("positions", "Opening Plan"),
            ("journal", "Journal"), ("tools", "Developer Tools"),
        )
        hero = premarket_setup_markup(data.premarket_setup)
        watchlist_rows = "".join(
            premarket_watchlist_row_markup(item) for item in data.premarket_watchlist
        )
        lower = dedent(f"""
          <div class="preview-lower-grid preview-premarket-lower">
            <div class="preview-card preview-open-card">
              <div class="preview-panel-heading"><span>OPENING PLAN</span><a>Preview only</a></div>
              <div class="preview-empty-position">
                <div class="preview-empty-icon">{icon_markup("positions", size=43)}</div>
                <strong>No opening plan selected.</strong>
                <span>Choose a premarket setup to prepare<br>an opening-session checklist.</span>
              </div>
              <button class="preview-settings" type="button">{icon_markup("watch", size=18)}<span>Review Premarket Setups</span></button>
            </div>
            <div class="preview-card preview-watchlist-card">
              <div class="preview-panel-heading"><span>PREMARKET WATCHLIST</span><a>Synthetic data</a></div>
              <div class="preview-premarket-head"><span>Ticker</span><span>Bias</span><span>Gap</span><span>Activity</span><span>Readiness</span><span>Trigger</span><span>Updated</span></div>
              <div class="preview-premarket-list">{watchlist_rows}</div>
            </div>
          </div>
        """)
        footer_label = "Opening Focus"
        footer_tip = "Build the plan before the bell, then wait for regular-session confirmation."
    elif data.session_mode is SessionMode.AFTER_HOURS:
        action_specs = (
            ("journal", "Review Journal"), ("watch", "Tomorrow's Watchlist"),
            ("market", "Session Summary"), ("positions", "Closed Positions"),
            ("scan", "Missed Setups"), ("tools", "Developer Tools"),
        )
        hero = after_hours_markup(data)
        lower = dedent(f"""
          <div class="preview-lower-grid">
            <div class="preview-card preview-open-card"><div class="preview-panel-heading"><span>POSITIONS</span><a>Session closed</a></div><div class="preview-empty-position"><div class="preview-empty-icon">{icon_markup("positions", size=43)}</div><strong>No positions carried overnight.</strong><span>Review closed trades and prepare<br>tomorrow's risk plan.</span></div></div>
            <div class="preview-card preview-signals-card"><div class="preview-panel-heading"><span>FINAL SIGNALS</span><a>View journal</a></div><div class="preview-signal-list">{signal_rows}</div><div class="preview-signal-count">Final sample signals from today's session</div></div>
          </div>
        """)
        footer_label = "Review Focus"
        footer_tip = data.after_hours.journal_reminder
    else:
        action_specs = (
            ("scan", "New Scan"), ("watch", "Watchlist"),
            ("market", "Market Overview"), ("positions", "Open Positions"),
            ("journal", "Journal"), ("tools", "Developer Tools"),
        )
        hero = setup_card_markup(data.setup)
        lower = dedent(f"""
          <div class="preview-lower-grid">
            <div class="preview-card preview-open-card">
              <div class="preview-panel-heading"><span>OPEN POSITIONS</span><a>View all</a></div>
              <div class="preview-empty-position"><div class="preview-empty-icon">{icon_markup("inbox", size=48)}</div><strong>No open positions</strong><span>When you take a trade,<br>it will appear here.</span></div>
              <button class="preview-settings" type="button">{icon_markup("settings", size=18)}<span>Paper Trade Settings</span></button>
            </div>
            <div class="preview-card preview-signals-card">
              <div class="preview-panel-heading"><span>RECENT SIGNALS</span><a>View all</a></div>
              <div class="preview-signal-list">{signal_rows}</div>
              <div class="preview-signal-count">Showing {len(data.recent_signals)} of {data.signal_count} signals</div>
            </div>
          </div>
        """)
        footer_label = "Focus Tip"
        footer_tip = data.focus_tip
    actions = "".join(
        action_markup(icon, label)
        for icon, label in action_specs
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
              <div class="preview-market-line preview-session-{data.session_mode.name.lower().replace('_', '-')}">
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

          {hero}

          <div class="preview-card preview-quick-actions">
            <div class="preview-eyebrow">QUICK ACTIONS</div>
            <div class="preview-action-grid">{actions}</div>
          </div>

          {lower}

          <div class="preview-card preview-focus-tip">
            <span class="preview-bulb">{icon_markup("bulb", size=28)}</span>
            <div><strong>{escape(footer_label)}:</strong> {escape(footer_tip)}</div>
            <a>View trading checklist {icon_markup("external", size=16)}</a>
          </div>
        </main>
        """
    )


def render_trade_desk_preview(st_module, data: TradeDeskPreview) -> None:
    """Render the complete local-only preview."""
    markup = trade_desk_markup(data).replace("\n", "")
    st_module.markdown(markup, unsafe_allow_html=True)


def render_session_selector(st_module, now: datetime | None = None) -> SessionMode:
    """Render the isolated browser-session mode selector and return its mode."""
    now = now or datetime.now(EASTERN)
    automatic = resolve_session_mode(now)
    selected = st_module.segmented_control(
        "Local preview session",
        options=[mode.value for mode in SessionMode],
        default=automatic.value,
        key="trade_desk_preview_session",
        help="Preview-only control. It does not change scanner or production state.",
    )
    return resolve_session_mode(now, selected)
