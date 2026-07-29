"""Reusable visual shell and presentation components for primary workspaces."""

from html import escape

from ui.design_tokens import css_variables


SHARED_UI_CSS = f"""
<style>
:root {{{css_variables()}}}
[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],
[data-testid="stHeader"] {{display:none}}
[data-testid="stAppViewContainer"] {{background:var(--ob-bg)}}
[data-testid="stMainBlockContainer"] {{
  box-sizing:border-box;margin:0 !important;max-width:1024px !important;
  padding:40px 24px 28px !important;width:100% !important;
}}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{gap:16px}}
.ob-page-header {{
  align-items:flex-start;display:flex;gap:24px;justify-content:space-between;
  margin:0 0 24px;min-height:90px;
}}
.ob-page-title {{
  color:var(--ob-text);font-size:var(--ob-font-heading);font-weight:740;
  letter-spacing:-.02em;line-height:1.05;
}}
.ob-page-subtitle {{
  color:var(--ob-text-secondary);font-size:17px;line-height:1.4;margin-top:9px;
}}
.ob-page-controls {{align-items:center;display:flex;flex-wrap:wrap;gap:10px;justify-content:flex-end}}
.ob-control {{
  background:#11171e;border:1px solid var(--ob-border);border-radius:var(--ob-button-radius);
  color:var(--ob-text) !important;display:inline-flex;font-size:13px;font-weight:750;
  min-height:42px;padding:10px 14px;text-decoration:none !important;
}}
.ob-control:hover {{border-color:var(--ob-amber);color:#f8dfa0 !important}}
.ob-page-tabs {{
  border-bottom:1px solid var(--ob-border);display:flex;gap:8px;margin:-8px 0 24px;
  overflow-x:auto;
}}
.ob-page-tab {{
  color:var(--ob-text-secondary) !important;font-size:15px;font-weight:700;
  min-width:112px;padding:12px 10px;text-align:center;text-decoration:none !important;
  white-space:nowrap;
}}
.ob-page-tab-active {{border-bottom:2px solid var(--ob-amber);color:var(--ob-amber) !important}}
.ob-card {{
  background:linear-gradient(145deg,var(--ob-panel-elevated),var(--ob-panel));
  border:1px solid var(--ob-border);border-radius:var(--ob-card-radius);
  box-sizing:border-box;padding:16px;
}}
.ob-section-header {{
  align-items:end;display:flex;gap:16px;justify-content:space-between;margin:24px 0 10px;
}}
.ob-section-title {{
  color:var(--ob-text);font-size:18px;font-weight:800;letter-spacing:.01em;
}}
.ob-section-copy {{color:var(--ob-text-muted);font-size:13px;margin-top:3px}}
.ob-metric-strip {{
  display:grid;gap:0;grid-template-columns:repeat(var(--metric-count),minmax(0,1fr));
  margin:0 0 24px;overflow:hidden;padding:0;
}}
.ob-compact-metric {{
  border-right:1px solid var(--ob-border-muted);min-width:0;padding:15px 16px;
}}
.ob-compact-metric:last-child {{border-right:0}}
.ob-metric-label {{
  color:var(--ob-text-muted);font-size:var(--ob-font-label);font-weight:800;
  letter-spacing:.045em;text-transform:uppercase;
}}
.ob-metric-value {{
  color:var(--ob-text);font-size:var(--ob-font-value);font-weight:760;
  line-height:1.15;margin-top:7px;overflow-wrap:anywhere;
}}
.ob-tone-positive .ob-metric-value {{color:var(--ob-green)}}
.ob-tone-negative .ob-metric-value {{color:var(--ob-red)}}
.ob-tone-caution .ob-metric-value {{color:var(--ob-amber)}}
.ob-badge {{
  background:rgba(255,255,255,.025);border:1px solid var(--ob-border);
  border-radius:6px;color:var(--ob-text-secondary);display:inline-block;font-size:11px;
  font-weight:850;letter-spacing:.045em;padding:4px 8px;text-transform:uppercase;
}}
.ob-badge-pass,.ob-badge-active,.ob-badge-ready {{border-color:#318f51;color:var(--ob-green)}}
.ob-badge-warning,.ob-badge-watch,.ob-badge-wait {{border-color:#aa8420;color:var(--ob-amber)}}
.ob-badge-fail,.ob-badge-invalidated {{border-color:#a43c40;color:var(--ob-red)}}
.ob-badge-closed {{color:var(--ob-text-muted)}}
.ob-empty {{
  align-items:center;border:1px dashed #3b4651;border-radius:var(--ob-card-radius);
  color:var(--ob-text-secondary);display:flex;flex-direction:column;justify-content:center;
  min-height:180px;padding:28px;text-align:center;
}}
.ob-empty-icon {{color:#697582;font-size:30px;line-height:1}}
.ob-empty-title {{color:var(--ob-text);font-size:17px;font-weight:760;margin-top:12px}}
.ob-empty-copy {{color:var(--ob-text-muted);font-size:14px;line-height:1.45;margin-top:6px;max-width:420px}}
.ob-callout {{
  background:rgba(97,169,238,.06);border:1px solid rgba(97,169,238,.28);
  border-radius:var(--ob-card-radius);color:var(--ob-text-secondary);font-size:14px;
  line-height:1.45;padding:12px 14px;
}}
.ob-callout-warning {{background:rgba(228,188,62,.06);border-color:rgba(228,188,62,.32)}}
.ob-status-list {{overflow:hidden;padding:0}}
.ob-status-row {{
  align-items:center;border-bottom:1px solid var(--ob-border-muted);display:grid;
  gap:12px;grid-template-columns:minmax(150px,1fr) auto minmax(220px,1.4fr);
  min-height:52px;padding:9px 14px;
}}
.ob-status-row:last-child {{border-bottom:0}}
.ob-status-name {{color:var(--ob-text);font-size:14px;font-weight:730}}
.ob-status-detail {{color:var(--ob-text-muted);font-size:13px;overflow-wrap:anywhere}}
.ob-table-wrap {{
  background:var(--ob-panel);border:1px solid var(--ob-border);
  border-radius:var(--ob-card-radius);overflow:hidden;
}}
.ob-table {{border-collapse:collapse;table-layout:fixed;width:100%}}
.ob-table th {{
  background:rgba(255,255,255,.025);color:var(--ob-text-muted);font-size:11px;
  font-weight:850;letter-spacing:.04em;padding:10px 9px;text-align:left;text-transform:uppercase;
}}
.ob-table td {{
  border-top:1px solid var(--ob-border-muted);color:var(--ob-text-secondary);
  font-size:13px;line-height:1.35;overflow-wrap:anywhere;padding:11px 9px;vertical-align:middle;
}}
.ob-table tbody tr:hover {{background:rgba(255,255,255,.025)}}
.ob-table td:first-child {{color:var(--ob-text);font-weight:730}}
div[data-testid="stDataFrame"] {{
  background:var(--ob-panel);border:1px solid var(--ob-border);border-radius:var(--ob-card-radius);
  overflow:hidden;padding:4px;
}}
div[data-testid="stExpander"] {{
  background:var(--ob-panel);border:1px solid var(--ob-border) !important;
  border-radius:var(--ob-card-radius) !important;
}}
div[data-testid="stExpander"] summary {{color:var(--ob-text);font-size:14px;font-weight:750}}
div[data-testid="stButton"] button {{
  background:#11171e;border:1px solid var(--ob-border);border-radius:var(--ob-button-radius);
  color:var(--ob-text);font-size:13px;font-weight:740;min-height:42px;
}}
div[data-testid="stButton"] button:hover {{border-color:var(--ob-amber);color:#f8dfa0}}
div[data-testid="stSelectbox"],div[data-testid="stTextInput"] {{font-size:14px}}
.ob-helper-strip {{
  align-items:center;background:var(--ob-panel);border:1px solid var(--ob-border);
  border-radius:var(--ob-card-radius);color:var(--ob-text-secondary);display:flex;
  font-size:14px;gap:8px;margin-top:24px;padding:14px 16px;
}}
@media (max-width:760px) {{
  [data-testid="stMainBlockContainer"] {{padding:28px 16px 24px !important}}
  .ob-page-header {{flex-direction:column;min-height:0}}
  .ob-page-title {{font-size:clamp(32px,11vw,46px)}}
  .ob-page-controls {{justify-content:flex-start}}
  .ob-metric-strip {{grid-template-columns:repeat(2,minmax(0,1fr))}}
  .ob-compact-metric {{border-bottom:1px solid var(--ob-border-muted)}}
  .ob-status-row {{grid-template-columns:1fr auto}}
  .ob-status-detail {{grid-column:1/-1}}
}}
</style>
"""


def page_header_markup(title, subtitle, controls=()):
    controls_html = "".join(
        f'<a class="ob-control" href="{escape(target)}">{escape(label)}</a>'
        for label, target in controls
    )
    return (
        '<header class="ob-page-header"><div>'
        f'<div class="ob-page-title">{escape(title)}</div>'
        f'<div class="ob-page-subtitle">{escape(subtitle)}</div></div>'
        f'<div class="ob-page-controls">{controls_html}</div></header>'
    )


def tabs_markup(items, active):
    links = "".join(
        f'<a class="ob-page-tab{" ob-page-tab-active" if label == active else ""}" '
        f'href="{escape(target)}">{escape(label)}</a>'
        for label, target in items
    )
    return f'<nav class="ob-page-tabs">{links}</nav>'


def section_header_markup(title, subtitle=None, action=None):
    action_html = (
        f'<a class="ob-control" href="{escape(action[1])}">{escape(action[0])}</a>'
        if action
        else ""
    )
    copy = f'<div class="ob-section-copy">{escape(subtitle)}</div>' if subtitle else ""
    return (
        '<div class="ob-section-header"><div>'
        f'<div class="ob-section-title">{escape(title)}</div>{copy}</div>{action_html}</div>'
    )


def metric_strip_markup(metrics):
    metrics = list(metrics)
    cards = "".join(
        '<div class="ob-compact-metric ob-tone-'
        f'{escape(treatment)}"><div class="ob-metric-label">{escape(label)}</div>'
        f'<div class="ob-metric-value">{escape(str(value))}</div></div>'
        for label, value, treatment in metrics
    )
    return (
        f'<section class="ob-card ob-metric-strip" style="--metric-count:{max(1, len(metrics))}">'
        f"{cards}</section>"
    )


def badge_markup(status):
    normalized = str(status or "UNAVAILABLE").strip().lower().replace(" ", "-")
    return f'<span class="ob-badge ob-badge-{escape(normalized)}">{escape(str(status))}</span>'


def empty_state_markup(title, message, icon="◇"):
    return (
        '<div class="ob-empty">'
        f'<div class="ob-empty-icon">{escape(icon)}</div>'
        f'<div class="ob-empty-title">{escape(title)}</div>'
        f'<div class="ob-empty-copy">{escape(message)}</div></div>'
    )


def status_rows_markup(rows):
    body = "".join(
        '<div class="ob-status-row">'
        f'<div class="ob-status-name">{escape(str(name))}</div>'
        f"{badge_markup(status)}"
        f'<div class="ob-status-detail">{escape(str(detail or ""))}</div></div>'
        for name, status, detail in rows
    )
    return f'<div class="ob-card ob-status-list">{body}</div>'


def compact_table_markup(rows, columns=None):
    """Render primary tabular content without Streamlit's light dataframe canvas."""
    rows = list(rows)
    if not rows:
        return ""
    columns = list(columns or rows[0].keys())
    header = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(str(row.get(column, '—') if row.get(column) is not None else '—'))}</td>"
            for column in columns
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<div class="ob-table-wrap"><table class="ob-table">'
        f"<thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"
    )
