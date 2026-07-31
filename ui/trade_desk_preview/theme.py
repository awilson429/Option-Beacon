"""Isolated Streamlit configuration and CSS for the local Trade Desk preview."""

from __future__ import annotations


PREVIEW_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --preview-bg: #080d11;
  --preview-panel: #10171d;
  --preview-panel-soft: #0d141a;
  --preview-border: #2b3740;
  --preview-border-soft: #202b33;
  --preview-text: #f2f4f6;
  --preview-muted: #aeb6bf;
  --preview-yellow: #f4c719;
  --preview-green: #31d268;
  --preview-red: #ff4e53;
}

[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"] {
  display: none !important;
}

html, body, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 48% 27%, rgba(35, 58, 70, .12), transparent 38rem),
    var(--preview-bg);
  color: var(--preview-text);
  font-family: Inter, system-ui, sans-serif;
}

[data-testid="stMainBlockContainer"] {
  box-sizing: border-box;
  max-width: 1240px !important;
  padding: 36px 28px 54px !important;
}

.preview-shell { position: relative; width: 100%; }
.preview-local-notice {
  color: #79848e;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .11em;
  position: absolute;
  right: 0;
  text-transform: uppercase;
  top: -18px;
}

.preview-header {
  align-items: flex-start;
  display: flex;
  justify-content: space-between;
  min-height: 130px;
}
.preview-header h1 {
  color: var(--preview-text);
  font-size: clamp(38px, 4vw, 54px);
  font-weight: 650;
  letter-spacing: -.035em;
  line-height: 1;
  margin: 0;
}
.preview-header p {
  color: var(--preview-muted);
  font-size: 17px;
  margin: 17px 0 0;
}
.preview-header-right { align-items: flex-end; display: flex; flex-direction: column; gap: 27px; }
.preview-market-line { align-items: center; display: flex; font-size: 16px; gap: 10px; }
.preview-market-dot { background: var(--preview-green); border-radius: 50%; height: 13px; width: 13px; }
.preview-market-status { color: var(--preview-green); font-weight: 600; }
.preview-time { color: var(--preview-muted); margin-left: 22px; }
.preview-controls { display: flex; gap: 16px; }
.preview-controls button, .preview-settings {
  align-items: center;
  background: linear-gradient(180deg, #10171d, #0d1318);
  border: 1px solid var(--preview-border);
  border-radius: 8px;
  color: var(--preview-text);
  display: inline-flex;
  font: inherit;
  font-size: 16px;
  gap: 10px;
  justify-content: center;
  min-height: 50px;
  padding: 0 22px;
}
.preview-controls button:last-child { min-width: 70px; padding: 0 16px; }

.preview-tabs {
  border-bottom: 1px solid var(--preview-border-soft);
  display: flex;
  gap: 0;
  margin-bottom: 25px;
}
.preview-tab {
  color: #c2c8cf;
  font-size: 16px;
  min-width: 140px;
  padding: 17px 25px 19px;
  position: relative;
  text-align: left;
}
.preview-tab-active { color: var(--preview-yellow); }
.preview-tab-active::after {
  background: var(--preview-yellow);
  bottom: -1px;
  content: "";
  height: 2px;
  left: 0;
  position: absolute;
  width: 126px;
}

.preview-card {
  background: linear-gradient(145deg, rgba(17, 25, 31, .98), rgba(13, 20, 26, .98));
  border: 1px solid var(--preview-border);
  border-radius: 10px;
  box-sizing: border-box;
}
.preview-eyebrow, .preview-panel-heading {
  color: #bdc5ce;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: .015em;
}

.preview-setup-card { min-height: 465px; padding: 28px 22px 22px; }
.preview-setup-grid {
  display: grid;
  gap: 24px;
  grid-template-columns: 210px minmax(0, 1fr) 285px;
  margin-top: 28px;
}
.preview-setup-identity {
  border-right: 1px solid var(--preview-border-soft);
  min-height: 290px;
  padding-right: 20px;
}
.preview-symbol { font-size: 48px; font-weight: 600; line-height: 1; }
.preview-direction { color: var(--preview-red); font-size: 20px; font-weight: 600; margin-top: 17px; }
.preview-setup-name { color: var(--preview-muted); font-size: 18px; margin-top: 12px; }
.preview-status-line { align-items: center; display: flex; font-size: 16px; gap: 15px; margin-top: 27px; }
.preview-badge {
  align-items: center;
  border: 1px solid currentColor;
  border-radius: 6px;
  display: inline-flex;
  font-size: 13px;
  font-weight: 700;
  justify-content: center;
  min-height: 39px;
  min-width: 76px;
  padding: 0 12px;
}
.preview-watch { color: var(--preview-yellow); }
.preview-positive { color: var(--preview-green); }
.preview-negative { color: var(--preview-red); }
.preview-neutral { color: var(--preview-muted); }

.preview-plan-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.preview-plan-metric {
  border-bottom: 1px solid var(--preview-border-soft);
  min-height: 92px;
  padding: 13px 20px 15px;
}
.preview-plan-metric:not(:nth-child(3n+1)) { border-left: 1px solid var(--preview-border-soft); }
.preview-plan-metric:nth-child(n+7) { border-bottom: 0; }
.preview-metric-label { color: var(--preview-muted); font-size: 14px; line-height: 1.2; }
.preview-metric-value { color: var(--preview-text); font-size: 19px; line-height: 1.25; margin-top: 12px; white-space: nowrap; }
.preview-plan-metric.preview-positive .preview-metric-label,
.preview-plan-metric.preview-positive .preview-metric-value { color: var(--preview-green); }
.preview-plan-metric.preview-negative .preview-metric-label,
.preview-plan-metric.preview-negative .preview-metric-value { color: var(--preview-red); }
.preview-plan-metric.preview-watch .preview-metric-value { color: var(--preview-yellow); }
.preview-plan-link { font-size: 16px; margin-top: 27px; text-align: center; }
.preview-plan-link span { margin-left: 17px; }

.preview-reasoning {
  border: 1px solid var(--preview-border);
  border-left: 4px solid var(--preview-yellow);
  border-radius: 9px;
  min-height: 350px;
  padding: 23px 23px 15px;
}
.preview-reason-label { color: #bdc5ce; font-size: 15px; font-weight: 600; margin-bottom: 9px; }
.preview-reasoning p { color: var(--preview-muted); font-size: 16px; line-height: 1.55; margin: 0 0 26px; }

.preview-quick-actions { margin-top: 20px; min-height: 130px; padding: 26px 22px; }
.preview-action-grid {
  align-items: center;
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  margin-top: 25px;
}
.preview-action-grid span { color: #d8dde2; font-size: 22px; white-space: nowrap; }
.preview-action-grid b { font-size: 14px; font-weight: 500; margin-left: 9px; }

.preview-lower-grid { display: grid; gap: 20px; grid-template-columns: .42fr .58fr; margin-top: 20px; }
.preview-open-card, .preview-signals-card { min-height: 480px; padding: 27px 22px; }
.preview-panel-heading { align-items: center; display: flex; justify-content: space-between; }
.preview-panel-heading a, .preview-focus-tip a { color: var(--preview-yellow); font-size: 14px; }
.preview-empty-position {
  align-items: center;
  border: 1px dashed #394650;
  border-radius: 8px;
  color: var(--preview-muted);
  display: flex;
  flex-direction: column;
  justify-content: center;
  margin-top: 26px;
  min-height: 265px;
  text-align: center;
}
.preview-empty-icon { color: #707a83; font-size: 52px; line-height: 1; }
.preview-empty-position strong { font-size: 17px; font-weight: 500; margin-top: 21px; }
.preview-empty-position span { font-size: 15px; line-height: 1.55; margin-top: 13px; }
.preview-settings { display: flex; margin: 22px auto 0; min-height: 45px; }

.preview-signal-list { margin-top: 15px; }
.preview-signal-row {
  align-items: center;
  border-bottom: 1px solid var(--preview-border-soft);
  display: grid;
  gap: 12px;
  grid-template-columns: 72px 78px minmax(120px, 1fr) 46px 72px 12px;
  min-height: 67px;
}
.preview-signal-row .preview-badge { font-size: 12px; min-height: 38px; min-width: 72px; }
.preview-signal-symbol { font-size: 22px; font-weight: 500; }
.preview-signal-direction { font-size: 15px; white-space: nowrap; }
.preview-signal-confidence { font-size: 15px; text-align: right; }
.preview-signal-time { color: var(--preview-muted); font-size: 14px; text-align: right; }
.preview-chevron { color: var(--preview-muted); font-size: 24px; }
.preview-signal-count { color: var(--preview-muted); font-size: 14px; margin-top: 21px; }

.preview-focus-tip {
  align-items: center;
  display: grid;
  font-size: 16px;
  gap: 18px;
  grid-template-columns: auto 1fr auto;
  margin-top: 20px;
  min-height: 88px;
  padding: 0 28px;
}
.preview-focus-tip strong { color: var(--preview-yellow); margin-right: 7px; }
.preview-bulb { color: var(--preview-yellow); font-size: 30px; }

@media (max-width: 1050px) {
  .preview-setup-grid { grid-template-columns: 180px minmax(0, 1fr); }
  .preview-reasoning { grid-column: 1 / -1; min-height: 0; }
  .preview-action-grid { grid-template-columns: repeat(3, 1fr); row-gap: 20px; }
  .preview-lower-grid { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  [data-testid="stMainBlockContainer"] { padding: 25px 16px 36px !important; }
  .preview-header { flex-direction: column; gap: 25px; }
  .preview-header-right { align-items: flex-start; width: 100%; }
  .preview-controls { flex-wrap: wrap; }
  .preview-tabs { overflow-x: auto; }
  .preview-tab { min-width: 108px; padding-left: 14px; padding-right: 14px; }
  .preview-setup-grid { grid-template-columns: 1fr; }
  .preview-setup-identity { border-bottom: 1px solid var(--preview-border-soft); border-right: 0; min-height: 0; padding: 0 0 24px; }
  .preview-plan-grid { grid-template-columns: 1fr 1fr; }
  .preview-plan-metric:not(:nth-child(3n+1)) { border-left: 0; }
  .preview-plan-metric:nth-child(even) { border-left: 1px solid var(--preview-border-soft); }
  .preview-action-grid { grid-template-columns: 1fr 1fr; }
  .preview-signal-row { grid-template-columns: 55px 74px 1fr 42px; }
  .preview-signal-time, .preview-chevron { display: none; }
  .preview-focus-tip { grid-template-columns: auto 1fr; padding: 18px; }
  .preview-focus-tip a { grid-column: 2; }
}
</style>
"""


def configure_preview_page(st_module) -> None:
    """Configure only the local preview page."""
    st_module.set_page_config(
        page_title="OptionBeacon Trade Desk Preview",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st_module.markdown(PREVIEW_CSS, unsafe_allow_html=True)
