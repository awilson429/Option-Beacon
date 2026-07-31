"""Reusable markup and rendering functions for the local Trade Desk preview."""

from __future__ import annotations

from html import escape
from textwrap import dedent

from .sample_data import DevelopingSetup, RecentSignal, TradeDeskPreview


def format_price(value: float) -> str:
    """Format a finite sample price consistently."""
    return f"${float(value):,.2f}"


def format_entry_zone(setup: DevelopingSetup) -> str:
    """Format the setup's entry range."""
    return (
        f"{format_price(setup.entry_zone_low)}–"
        f"{format_price(setup.entry_zone_high)}"
    )


def status_class(status: str) -> str:
    """Map display-only status text to an existing semantic accent."""
    normalized = str(status or "").strip().upper()
    if normalized in {"WATCH", "READY", "OPEN"}:
        return "preview-positive" if normalized in {"READY", "OPEN"} else "preview-watch"
    if normalized in {"WAIT", "STOP", "EXIT"}:
        return "preview-negative"
    return "preview-neutral"


def signal_row_markup(signal: RecentSignal) -> str:
    """Render one recent-signal row from typed sample data."""
    return (
        '<div class="preview-signal-row">'
        f'<div class="preview-signal-symbol">{escape(signal.symbol)}</div>'
        f'<div><span class="preview-badge {status_class(signal.status)}">'
        f'{escape(signal.status)}</span></div>'
        f'<div class="preview-signal-direction">'
        f'{escape(signal.direction)} {escape(signal.option_type)}</div>'
        f'<div class="preview-signal-confidence">{signal.confidence}%</div>'
        f'<div class="preview-signal-time">{escape(signal.time_label)}</div>'
        '<div class="preview-chevron">›</div>'
        "</div>"
    )


def metric_markup(label: str, value: str, treatment: str = "") -> str:
    """Render one aligned trade-plan metric."""
    treatment_class = f" preview-{treatment}" if treatment else ""
    return (
        f'<div class="preview-plan-metric{treatment_class}">'
        f'<div class="preview-metric-label">{escape(label)}</div>'
        f'<div class="preview-metric-value">{escape(value)}</div>'
        "</div>"
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
    return dedent(f"""
    <div class="preview-card preview-setup-card">
      <div class="preview-eyebrow">BEST DEVELOPING SETUP</div>
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
        <div>
          <div class="preview-plan-grid">{metrics}</div>
          <div class="preview-plan-link">View full trade plan <span>⌄</span></div>
        </div>
        <aside class="preview-reasoning">
          <div class="preview-reason-label">WHY THIS SETUP</div>
          <p>{escape(setup.reason)}</p>
          <div class="preview-reason-label">WHAT’S MISSING</div>
          <p>{escape(setup.missing_confirmation)}</p>
          <div class="preview-reason-label">INVALIDATION</div>
          <p>{escape(setup.invalidation)}</p>
        </aside>
      </div>
    </div>
    """)


def trade_desk_markup(data: TradeDeskPreview) -> str:
    """Build the complete preview shell without accessing application state."""
    signal_rows = "".join(signal_row_markup(signal) for signal in data.recent_signals)
    return dedent(f"""
    <main class="preview-shell">
      <div class="preview-local-notice">LOCAL UI PREVIEW</div>
      <header class="preview-header">
        <div>
          <h1>Trade Desk</h1>
          <p>Focus on the best setups. Trade with a plan.</p>
        </div>
        <div class="preview-header-right">
          <div class="preview-market-line">
            <span class="preview-market-dot"></span>
            <span class="preview-market-status">{escape(data.market_status)}</span>
            <span class="preview-time">{escape(data.eastern_time)}</span>
          </div>
          <div class="preview-controls">
            <button type="button"><span>↻</span> Refresh</button>
            <button type="button"><span>▽</span> Filters</button>
            <button type="button" aria-label="More options">•••</button>
          </div>
        </div>
      </header>

      <nav class="preview-tabs" aria-label="Trade Desk sections">
        <span class="preview-tab preview-tab-active">Overview</span>
        <span class="preview-tab">Signals</span>
        <span class="preview-tab">Positions</span>
        <span class="preview-tab">Journal</span>
        <span class="preview-tab">Analytics</span>
      </nav>

      {setup_card_markup(data.setup)}

      <div class="preview-card preview-quick-actions">
        <div class="preview-eyebrow">QUICK ACTIONS</div>
        <div class="preview-action-grid">
          <span>⌕ <b>New Scan</b></span>
          <span>☆ <b>Watchlist</b></span>
          <span>▥ <b>Market Overview</b></span>
          <span>▢ <b>Open Positions</b></span>
          <span>▣ <b>Journal</b></span>
          <span>⌕ <b>Developer Tools</b></span>
        </div>
      </div>

      <div class="preview-lower-grid">
        <div class="preview-card preview-open-card">
          <div class="preview-panel-heading">
            <span>OPEN POSITIONS</span><a>View all</a>
          </div>
          <div class="preview-empty-position">
            <div class="preview-empty-icon">▱</div>
            <strong>No open positions</strong>
            <span>When you take a trade,<br>it will appear here.</span>
          </div>
          <button class="preview-settings" type="button">⚙ &nbsp; Paper Trade Settings</button>
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
        <span class="preview-bulb">♧</span>
        <div><strong>Focus Tip:</strong> {escape(data.focus_tip)}</div>
        <a>View trading checklist &nbsp; ↗</a>
      </div>
    </main>
    """)


def render_trade_desk_preview(st_module, data: TradeDeskPreview) -> None:
    """Render the complete local-only preview."""
    # A single-line HTML fragment prevents Markdown from interpreting indented
    # sibling cards as code blocks when reusable component markup is composed.
    markup = trade_desk_markup(data).replace("\n", "")
    st_module.markdown(markup, unsafe_allow_html=True)
