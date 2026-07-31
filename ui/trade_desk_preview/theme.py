"""Isolated Streamlit configuration and design system for the local preview."""

from __future__ import annotations


PREVIEW_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;650;700&display=swap');

:root {
  --ob-bg: #070b0f;
  --ob-bg-raised: #0a1015;
  --ob-panel: #101820;
  --ob-panel-deep: #0c1319;
  --ob-panel-hover: #131e26;
  --ob-border: #293640;
  --ob-border-soft: #1e2a32;
  --ob-border-bright: #35444f;
  --ob-text: #f2f5f7;
  --ob-text-secondary: #c2cad1;
  --ob-muted: #8d99a3;
  --ob-yellow: #f3c51b;
  --ob-yellow-soft: rgba(243, 197, 27, .10);
  --ob-green: #32d26b;
  --ob-green-soft: rgba(50, 210, 107, .10);
  --ob-red: #ff5258;
  --ob-red-soft: rgba(255, 82, 88, .09);
  --ob-blue: #58a9ff;
  --ob-space-1: 4px;
  --ob-space-2: 8px;
  --ob-space-3: 12px;
  --ob-space-4: 16px;
  --ob-space-5: 20px;
  --ob-space-6: 24px;
  --ob-space-7: 32px;
  --ob-space-8: 40px;
  --ob-radius-sm: 7px;
  --ob-radius-md: 11px;
  --ob-radius-lg: 14px;
  --ob-shadow-card: 0 18px 50px rgba(0, 0, 0, .20);
  --ob-shadow-hover: 0 20px 55px rgba(0, 0, 0, .27);
  --ob-text-xs: 11px;
  --ob-text-sm: 13px;
  --ob-text-md: 15px;
  --ob-text-lg: 18px;
  --ob-text-xl: 22px;
  --ob-transition: 160ms ease;
}

[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"] { display: none !important; }

html, body, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 49% 22%, rgba(45, 71, 85, .12), transparent 34rem),
    linear-gradient(180deg, #080d12 0%, var(--ob-bg) 60%);
  color: var(--ob-text);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

[data-testid="stMainBlockContainer"] {
  box-sizing: border-box;
  max-width: 1280px !important;
  padding: 34px 28px 56px !important;
}

.preview-shell { position: relative; width: 100%; }
.preview-local-notice {
  background: rgba(141, 153, 163, .08);
  border: 1px solid var(--ob-border-soft);
  border-radius: 999px;
  color: var(--ob-muted);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .13em;
  padding: 5px 9px;
  position: absolute;
  right: 0;
  text-transform: uppercase;
  top: -18px;
}

.preview-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  min-height: 102px;
}
.preview-brand-row {
  align-items: center;
  display: flex;
  gap: 15px;
}
.preview-brand-mark {
  align-items: center;
  background: linear-gradient(145deg, rgba(243,197,27,.10), rgba(243,197,27,.018));
  border: 1px solid rgba(243,197,27,.22);
  border-radius: 11px;
  box-shadow: inset 0 1px rgba(255,255,255,.025), 0 9px 28px rgba(0,0,0,.22);
  display: inline-flex;
  height: 48px;
  justify-content: center;
  width: 48px;
}
.preview-brand-mark svg { height: 37px; overflow: visible; width: 37px; }
.preview-logo-orbit {
  fill: none;
  opacity: .78;
  stroke: var(--ob-yellow);
  stroke-linecap: round;
  stroke-width: 1.7;
}
.preview-logo-orbit-inner { opacity: .42; }
.preview-logo-tower { fill: #121c23; stroke: #eef2f4; stroke-width: 1.6; }
.preview-logo-cut { fill: none; stroke: #77858e; stroke-width: 1.25; }
.preview-logo-spark { fill: var(--ob-yellow); }
.preview-wordmark {
  display: flex;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: .075em;
  line-height: 1;
}
.preview-wordmark span:first-child { color: var(--ob-text); }
.preview-wordmark span:last-child { color: var(--ob-yellow); }
.preview-branding {
  align-items: center;
  display: flex;
}
.preview-header-right {
  align-items: flex-end;
  display: flex;
  flex-direction: column;
  gap: 27px;
  padding-top: 0;
}
.preview-market-line { align-items: center; display: flex; font-size: 15px; gap: 10px; }
.preview-market-dot {
  animation: preview-pulse 2.4s ease-out infinite;
  background: var(--ob-green);
  border-radius: 50%;
  box-shadow: 0 0 0 0 rgba(50,210,107,.35);
  height: 11px;
  width: 11px;
}
.preview-market-status { color: var(--ob-green); font-weight: 650; letter-spacing: .01em; }
.preview-time { color: var(--ob-muted); margin-left: 20px; }
.preview-controls { display: flex; gap: var(--ob-space-3); }
.preview-controls button, .preview-settings, .preview-plan-link, .preview-action {
  -webkit-appearance: none;
  appearance: none;
  color: var(--ob-text);
  cursor: default;
  font: inherit;
  transition:
    background var(--ob-transition),
    border-color var(--ob-transition),
    box-shadow var(--ob-transition),
    transform var(--ob-transition);
}
.preview-controls button, .preview-settings {
  align-items: center;
  background: linear-gradient(180deg, #111a21, #0c1217);
  border: 1px solid var(--ob-border);
  border-radius: var(--ob-radius-sm);
  display: inline-flex;
  font-size: 15px;
  gap: 10px;
  justify-content: center;
  min-height: 48px;
  padding: 0 20px;
}
.preview-controls button:hover, .preview-settings:hover {
  background: linear-gradient(180deg, #162129, #10181e);
  border-color: var(--ob-border-bright);
  box-shadow: 0 8px 22px rgba(0,0,0,.22);
  transform: translateY(-1px);
}
.preview-controls button:last-child { min-width: 60px; padding: 0 15px; }

.preview-tabs {
  border-bottom: 1px solid var(--ob-border-soft);
  display: flex;
  margin-bottom: 24px;
}
.preview-tab {
  color: var(--ob-text-secondary);
  font-size: 15px;
  min-width: 130px;
  padding: 15px 24px 18px;
  position: relative;
}
.preview-tab-active { color: var(--ob-yellow); font-weight: 600; }
.preview-tab-active::after {
  background: var(--ob-yellow);
  bottom: -1px;
  content: "";
  height: 2px;
  left: 0;
  position: absolute;
  width: 116px;
}

.preview-card {
  animation: preview-enter 420ms ease-out both;
  background:
    linear-gradient(145deg, rgba(18, 28, 35, .98), rgba(11, 18, 23, .99));
  border: 1px solid var(--ob-border);
  border-radius: var(--ob-radius-md);
  box-shadow:
    inset 0 1px rgba(255,255,255,.018),
    var(--ob-shadow-card);
  box-sizing: border-box;
}
.preview-eyebrow, .preview-panel-heading {
  color: var(--ob-text-secondary);
  font-size: 14px;
  font-weight: 650;
  letter-spacing: .025em;
}
.preview-eyebrow-row { align-items: center; display: flex; justify-content: space-between; }
.preview-sample-chip {
  border: 1px solid var(--ob-border);
  border-radius: 999px;
  color: var(--ob-muted);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .1em;
  padding: 5px 8px;
}

.preview-setup-card { min-height: 552px; padding: 25px 22px 20px; }
.preview-setup-grid {
  display: grid;
  gap: 22px;
  grid-template-columns: 205px minmax(0, 1fr) 276px;
  margin-top: 24px;
}
.preview-setup-identity {
  border-right: 1px solid var(--ob-border-soft);
  min-height: 415px;
  padding: 7px 20px 0 1px;
}
.preview-symbol {
  color: #fff;
  font-size: 49px;
  font-weight: 650;
  letter-spacing: -.045em;
  line-height: 1;
}
.preview-direction {
  color: var(--ob-red);
  font-size: 19px;
  font-weight: 650;
  margin-top: 18px;
}
.preview-setup-name { color: var(--ob-muted); font-size: 17px; line-height: 1.4; margin-top: 11px; }
.preview-status-line {
  align-items: center;
  color: var(--ob-text-secondary);
  display: flex;
  font-size: 15px;
  gap: 14px;
  margin-top: 26px;
}
.preview-badge {
  align-items: center;
  border: 1px solid currentColor;
  border-radius: 6px;
  display: inline-flex;
  font-size: 11px;
  font-weight: 700;
  height: 34px;
  justify-content: center;
  letter-spacing: .025em;
  min-width: 70px;
  padding: 0 10px;
}
.preview-watch { color: var(--ob-yellow); }
.preview-positive { color: var(--ob-green); }
.preview-negative { color: var(--ob-red); }
.preview-neutral { color: var(--ob-muted); }

.preview-plan-area { min-width: 0; }
.preview-plan-grid {
  border-bottom: 1px solid var(--ob-border-soft);
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.preview-plan-metric {
  border-bottom: 1px solid var(--ob-border-soft);
  min-height: 83px;
  padding: 11px 17px 13px;
}
.preview-plan-metric:not(:nth-child(3n+1)) { border-left: 1px solid var(--ob-border-soft); }
.preview-plan-metric:nth-child(n+7) { border-bottom: 0; }
.preview-metric-label {
  color: var(--ob-muted);
  font-size: 12px;
  line-height: 1.3;
  min-height: 16px;
}
.preview-metric-value {
  color: var(--ob-text);
  font-size: 17px;
  font-weight: 500;
  line-height: 1.3;
  margin-top: 10px;
  white-space: nowrap;
}
.preview-plan-metric.preview-positive .preview-metric-label,
.preview-plan-metric.preview-positive .preview-metric-value { color: var(--ob-green); }
.preview-plan-metric.preview-negative .preview-metric-label,
.preview-plan-metric.preview-negative .preview-metric-value { color: var(--ob-red); }
.preview-plan-metric.preview-watch .preview-metric-value { color: var(--ob-yellow); }
.preview-confidence-block {
  background: rgba(7, 12, 16, .26);
  border: 1px solid var(--ob-border-soft);
  border-radius: var(--ob-radius-sm);
  margin-top: 15px;
  padding: 12px 14px 13px;
}
.preview-confidence-heading {
  align-items: center;
  color: var(--ob-text-secondary);
  display: flex;
  font-size: 10px;
  font-weight: 650;
  justify-content: space-between;
  letter-spacing: .045em;
}
.preview-confidence-heading span:last-child {
  color: var(--ob-muted);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: .02em;
  text-transform: none;
}
.preview-factor-grid {
  display: grid;
  gap: 7px 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 10px;
}
.preview-factor {
  align-items: center;
  color: var(--ob-muted);
  display: flex;
  font-size: 11px;
  gap: 7px;
  line-height: 1.25;
}
.preview-factor > span:first-child {
  align-items: center;
  border: 1px solid currentColor;
  border-radius: 50%;
  display: inline-flex;
  flex: 0 0 15px;
  font-size: 9px;
  height: 15px;
  justify-content: center;
}
.preview-factor-positive { color: #71d994; }
.preview-factor-missing { color: #d19366; }
.preview-plan-link {
  align-items: center;
  background: transparent;
  border: 0;
  display: flex;
  font-size: 14px;
  gap: 10px;
  justify-content: center;
  margin: 15px auto 0;
  padding: 4px 10px;
}
.preview-plan-link:hover { color: var(--ob-yellow); }

.preview-reasoning {
  background:
    linear-gradient(155deg, rgba(22, 32, 39, .94), rgba(12, 19, 25, .96));
  border: 1px solid var(--ob-border);
  border-left: 3px solid var(--ob-yellow);
  border-radius: var(--ob-radius-sm);
  box-shadow: inset 0 1px rgba(255,255,255,.018);
  min-height: 414px;
  padding: 20px 20px 15px;
}
.preview-reason-section + .preview-reason-section {
  border-top: 1px solid var(--ob-border-soft);
  padding-top: 18px;
}
.preview-reason-label {
  color: var(--ob-text-secondary);
  font-size: 12px;
  font-weight: 650;
  letter-spacing: .02em;
  margin-bottom: 8px;
}
.preview-reasoning p {
  color: var(--ob-muted);
  font-size: 14px;
  line-height: 1.55;
  margin: 0 0 18px;
}

.preview-quick-actions { animation-delay: 50ms; margin-top: 18px; min-height: 121px; padding: 22px; }
.preview-action-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  margin-top: 16px;
}
.preview-action {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--ob-radius-sm);
  color: var(--ob-text-secondary);
  display: flex;
  font-size: 13px;
  gap: 10px;
  justify-content: flex-start;
  min-height: 46px;
  padding: 0 11px;
  white-space: nowrap;
}
.preview-action svg { color: #b9c5cc; flex: 0 0 auto; }
.preview-action:hover {
  background: rgba(255,255,255,.025);
  border-color: var(--ob-border-soft);
  color: var(--ob-text);
  transform: translateY(-1px);
}

.preview-lower-grid {
  display: grid;
  gap: 18px;
  grid-template-columns: .41fr .59fr;
  margin-top: 18px;
}
.preview-open-card, .preview-signals-card {
  animation-delay: 90ms;
  min-height: 440px;
  padding: 24px 21px;
}
.preview-panel-heading { align-items: center; display: flex; justify-content: space-between; }
.preview-panel-heading a, .preview-focus-tip a {
  align-items: center;
  color: var(--ob-yellow);
  display: inline-flex;
  font-size: 13px;
  gap: 7px;
}
.preview-empty-position {
  align-items: center;
  background:
    radial-gradient(circle at 50% 18%, rgba(73, 94, 108, .08), transparent 56%);
  border: 1px dashed #34434d;
  border-radius: var(--ob-radius-sm);
  color: var(--ob-muted);
  display: flex;
  flex-direction: column;
  justify-content: center;
  margin-top: 22px;
  min-height: 242px;
  text-align: center;
}
.preview-empty-icon {
  align-items: center;
  background: rgba(141,153,163,.055);
  border: 1px solid rgba(141,153,163,.10);
  border-radius: 50%;
  color: #687680;
  display: flex;
  height: 76px;
  justify-content: center;
  width: 76px;
}
.preview-empty-position strong {
  color: var(--ob-text-secondary);
  font-size: 16px;
  font-weight: 550;
  margin-top: 17px;
}
.preview-empty-position span { font-size: 14px; line-height: 1.55; margin-top: 9px; }
.preview-settings { display: flex; font-size: 13px; margin: 18px auto 0; min-height: 42px; }

.preview-signal-list { margin-top: 12px; }
.preview-signal-row {
  align-items: center;
  border-bottom: 1px solid var(--ob-border-soft);
  border-radius: 4px;
  display: grid;
  gap: 12px;
  grid-template-columns: 70px 76px minmax(120px, 1fr) 43px 69px 18px;
  min-height: 62px;
  padding: 0 6px;
  transition: background var(--ob-transition), transform var(--ob-transition);
}
.preview-signal-row:hover { background: rgba(255,255,255,.022); transform: translateX(2px); }
.preview-signal-row .preview-badge { font-size: 10px; height: 31px; min-width: 65px; }
.preview-signal-symbol { color: #fff; font-size: 20px; font-weight: 600; letter-spacing: -.02em; }
.preview-signal-direction { color: var(--ob-text-secondary); font-size: 13px; white-space: nowrap; }
.preview-signal-confidence { font-size: 13px; font-variant-numeric: tabular-nums; text-align: right; }
.preview-signal-time { color: var(--ob-muted); font-size: 12px; text-align: right; white-space: nowrap; }
.preview-chevron { color: #71808a; display: flex; justify-content: flex-end; }
.preview-signal-row:hover .preview-chevron { color: var(--ob-text-secondary); }
.preview-signal-count { color: var(--ob-muted); font-size: 12px; margin-top: 17px; }

.preview-focus-tip {
  align-items: center;
  animation-delay: 130ms;
  display: grid;
  font-size: 14px;
  gap: 17px;
  grid-template-columns: auto 1fr auto;
  margin-top: 18px;
  min-height: 78px;
  padding: 0 25px;
}
.preview-focus-tip strong { color: var(--ob-yellow); margin-right: 7px; }
.preview-bulb { color: var(--ob-yellow); display: flex; }

@keyframes preview-pulse {
  0%, 55%, 100% { box-shadow: 0 0 0 0 rgba(50,210,107,.30); }
  75% { box-shadow: 0 0 0 7px rgba(50,210,107,0); }
}
@keyframes preview-enter {
  from { opacity: 0; transform: translateY(5px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 1100px) {
  .preview-setup-grid { grid-template-columns: 180px minmax(0, 1fr); }
  .preview-reasoning { grid-column: 1 / -1; min-height: 0; }
  .preview-reason-section { display: inline-block; padding-right: 24px; vertical-align: top; width: 31%; }
  .preview-reason-section + .preview-reason-section { border-left: 1px solid var(--ob-border-soft); border-top: 0; padding-left: 20px; padding-top: 0; }
  .preview-action-grid { grid-template-columns: repeat(3, 1fr); }
  .preview-quick-actions { min-height: 170px; }
}
@media (max-width: 800px) {
  [data-testid="stMainBlockContainer"] { padding: 24px 16px 36px !important; }
  .preview-local-notice { position: static; display: inline-flex; margin-bottom: 16px; }
  .preview-header { align-items: flex-start; flex-direction: column; gap: 24px; min-height: 0; }
  .preview-header-right { align-items: flex-start; padding-bottom: 20px; width: 100%; }
  .preview-market-line { flex-wrap: wrap; }
  .preview-time { margin-left: 10px; }
  .preview-controls { flex-wrap: wrap; }
  .preview-tabs { overflow-x: auto; }
  .preview-tab { min-width: 105px; padding-left: 13px; padding-right: 13px; }
  .preview-setup-grid { grid-template-columns: 1fr; }
  .preview-setup-identity { border-bottom: 1px solid var(--ob-border-soft); border-right: 0; min-height: 0; padding: 0 0 22px; }
  .preview-plan-grid { grid-template-columns: 1fr 1fr; }
  .preview-plan-metric:not(:nth-child(3n+1)) { border-left: 0; }
  .preview-plan-metric:nth-child(even) { border-left: 1px solid var(--ob-border-soft); }
  .preview-plan-metric:nth-child(n+7) { border-bottom: 1px solid var(--ob-border-soft); }
  .preview-plan-metric:last-child { border-bottom: 0; }
  .preview-factor-grid { grid-template-columns: 1fr; }
  .preview-reason-section { display: block; padding-right: 0; width: auto; }
  .preview-reason-section + .preview-reason-section { border-left: 0; border-top: 1px solid var(--ob-border-soft); padding-left: 0; padding-top: 18px; }
  .preview-action-grid { grid-template-columns: 1fr 1fr; }
  .preview-lower-grid { grid-template-columns: 1fr; }
  .preview-signal-row { grid-template-columns: 55px 68px minmax(100px, 1fr) 42px; }
  .preview-signal-time, .preview-chevron { display: none; }
  .preview-focus-tip { grid-template-columns: auto 1fr; padding: 16px 18px; }
  .preview-focus-tip a { grid-column: 2; }
}

@media (prefers-reduced-motion: reduce) {
  .preview-card, .preview-market-dot { animation: none !important; }
  .preview-action, .preview-controls button, .preview-settings,
  .preview-plan-link, .preview-signal-row { transition: none !important; }
  .preview-action:hover, .preview-controls button:hover,
  .preview-settings:hover, .preview-signal-row:hover { transform: none !important; }
}
</style>
"""


def configure_preview_page(st_module) -> None:
    """Configure only the local preview page."""
    st_module.set_page_config(
        page_title="OptionBeacon Trade Desk Preview",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st_module.markdown(PREVIEW_CSS, unsafe_allow_html=True)
