"""Option Beacon Streamlit page configuration and visual theme."""

import streamlit as st
from streamlit_autorefresh import st_autorefresh
from ui.design_tokens import css_variables


def configure_page():
    st.set_page_config(page_title="Option Beacon", layout="wide")
    st_autorefresh(interval=60000, key="option_beacon_refresh")
    theme_css = """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;600;700&family=Source+Sans+3:wght@400;600;700&display=swap');

        :root {
            /* OPTIONBEACON_THEME_TOKENS */
        }

        html, body, [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at top right, rgba(42, 72, 102, 0.18), transparent 30rem),
                var(--ob-bg-page);
            color: var(--ob-text);
            font-family: 'Source Sans 3', sans-serif;
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        .block-container {
            max-width: 1240px;
            padding-top: 2rem;
            padding-bottom: 2rem;
        }

        h1, h2, h3 {
            letter-spacing: 0;
        }

        h1, .brand-title {
            font-family: 'Orbitron', 'Source Sans 3', sans-serif;
        }

        h2, h3 {
            font-family: 'Source Sans 3', sans-serif;
            font-weight: 700;
        }

        [data-testid="stMarkdownContainer"] p {
            color: var(--ob-muted);
        }

        .brand-shell {
            border: 1px solid var(--ob-border-strong);
            border-radius: 8px;
            padding: 1.15rem 1.25rem;
            background: var(--ob-bg-header);
            box-sizing: border-box;
            margin-bottom: 0.65rem;
            max-width: 100%;
        }

        .ob-live-notice {
            border: 1px solid var(--ob-border-strong); border-left-width: 5px;
            border-radius: 8px; margin: .5rem 0 1rem; padding: 1rem 1.1rem;
            background: var(--ob-bg-header);
        }
        .ob-live-entry,.ob-live-winning {border-left-color:#5fd38b}
        .ob-live-losing {border-left-color:#d96b72}
        .ob-live-kicker {font-size:.76rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
        .ob-live-symbol {font-size:1.35rem;font-weight:800;margin:.2rem 0}
        .ob-live-result {display:block;font-size:1.65rem;color:#5fd38b}
        .ob-live-losing .ob-live-result {color:#e07a80}
        .ob-live-detail {color:var(--ob-text-muted);font-size:.86rem}

        .ob-desk-status {
            align-items:center; background:var(--ob-bg-card); border:1px solid var(--ob-border-default);
            border-radius:8px; display:flex; flex-wrap:wrap; gap:.35rem .7rem;
            margin:.15rem 0 .4rem; padding:.34rem .55rem; max-width:100%; overflow:hidden;
        }
        .ob-desk-status-warning {border-color:#c49b45;background:rgba(196,155,69,.08)}
        .ob-desk-status-error {border-color:#d96b72;background:rgba(217,107,114,.08)}
        .ob-desk-status-pill {
            color:var(--ob-text-muted); font-size:.7rem; font-weight:800; letter-spacing:.045em;
            line-height:1; white-space:nowrap;
        }
        .ob-desk-status-pill + .ob-desk-status-pill::before {content:"\\00b7";color:var(--ob-border-strong);margin-right:.7rem}
        .ob-desk-kpis {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.55rem;margin:.25rem 0 .55rem;max-width:100%;min-width:0}
        .ob-desk-kpi,.ob-desk-panel {background:var(--ob-bg-card);border:1px solid var(--ob-border-default);border-radius:8px;box-sizing:border-box;min-width:0}
        .ob-desk-kpi {display:flex;flex-direction:column;justify-content:center;height:4.1rem;min-height:4.1rem;padding:.45rem .62rem}
        .ob-desk-kpi-label {color:var(--ob-text-muted);font-size:.62rem;font-weight:800;letter-spacing:.055em;white-space:nowrap}
        .ob-desk-kpi-value {color:var(--ob-text);font-size:1.08rem;font-weight:800;line-height:1.15;margin:.12rem 0}
        .ob-desk-kpi-detail,.ob-panel-note {color:var(--ob-text-muted);font-size:.66rem;line-height:1.25}
        .ob-value-positive {color:var(--ob-positive)!important}.ob-value-negative {color:var(--ob-negative)!important}
        .ob-desk-panel {margin:0 0 .55rem;padding:.68rem .78rem;overflow:hidden}.ob-desk-panel h3 {font-size:.86rem;letter-spacing:0;margin:0 0 .42rem}
        .ob-desk-empty,.ob-best-trade-empty {color:var(--ob-text-muted);font-size:.74rem;line-height:1.3;padding:.2rem 0}
        .ob-performance-grid {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.35rem}
        .ob-performance-stat {border-right:1px solid var(--ob-border-default);display:flex;flex-direction:column;gap:.12rem;min-width:0;padding:.18rem .4rem}
        .ob-performance-stat:last-child {border-right:0}.ob-performance-stat span {color:var(--ob-text-muted);font-size:.62rem;white-space:nowrap}
        .ob-performance-stat strong {font-size:.88rem;white-space:nowrap}.ob-panel-note {border-top:1px solid var(--ob-border-default);margin-top:.55rem;padding-top:.45rem}
        .ob-risk-row {margin:.43rem 0}.ob-risk-line {display:flex;font-size:.68rem;gap:.5rem;justify-content:space-between}.ob-risk-line span:last-child {color:var(--ob-text-muted);text-align:right}.ob-risk-line small {font-size:.58rem;margin-left:.22rem}
        .ob-risk-track {background:var(--ob-bg-control);border-radius:3px;height:3px;margin-top:.2rem;overflow:hidden}.ob-risk-fill {display:block;height:100%}
        .ob-risk-healthy {background:var(--ob-positive)}.ob-risk-warning {background:var(--ob-warning)}.ob-risk-danger {background:var(--ob-negative)}
        .ob-position-scroll {max-width:100%;overflow-x:auto}.ob-position-table {border-collapse:collapse;font-size:.7rem;min-width:47rem;width:100%}
        .ob-position-table th {color:var(--ob-text-muted);font-size:.58rem;letter-spacing:.04em;text-align:left}.ob-position-table th,.ob-position-table td {border-bottom:1px solid var(--ob-border-default);padding:.34rem .32rem;white-space:nowrap}
        .ob-position-table tbody tr:last-child td {border-bottom:0}.ob-position-state {background:color-mix(in srgb,var(--ob-positive) 12%,transparent);border-radius:4px;color:var(--ob-positive);font-size:.58rem;font-weight:800;padding:.18rem .35rem}
        .ob-position-table details {position:relative}.ob-position-table summary {color:var(--ob-gold);cursor:pointer;list-style:none}.ob-position-table details div {color:var(--ob-text-muted);font-size:.66rem;padding:.3rem 0;white-space:normal;width:15rem}
        .ob-activity-row {align-items:center;border-bottom:1px solid var(--ob-border-default);display:grid;gap:.4rem;grid-template-columns:7.2rem 3.7rem 3.8rem minmax(7rem,1fr) auto;padding:.28rem 0;font-size:.68rem;min-width:0}
        .ob-activity-row:last-child {border-bottom:0}.ob-activity-time {color:var(--ob-text-muted);white-space:nowrap}.ob-activity-tag {border:1px solid var(--ob-border-default);border-radius:4px;font-size:.56rem;font-weight:800;padding:.14rem .25rem;text-align:center}
        .ob-activity-enter,.ob-activity-target {color:var(--ob-positive)}.ob-activity-exit,.ob-activity-stop {color:var(--ob-negative)}.ob-activity-result {font-weight:700;text-align:right;white-space:nowrap}
        .ob-activity-invalid {color:var(--ob-text-muted)}
        .ob-best-trade-empty {background:var(--ob-bg-card);border:1px solid var(--ob-border-default);border-radius:8px;margin:0 0 .45rem;padding:.58rem .7rem}
        .ob-disclaimer {color:var(--ob-text-muted);font-size:.62rem;margin:.25rem 0;text-align:center}
        .ob-trade-dashboard {
            background:var(--ob-bg-header);border:1px solid var(--ob-border-strong);
            border-radius:11px;box-sizing:border-box;display:grid;gap:12px;
            grid-template-areas:
                "header header"
                "kpis kpis"
                "positions risk"
                "performance risk"
                "activity activity"
                "more more";
            grid-template-columns:minmax(0,7fr) minmax(280px,3fr);
            margin:.2rem 0 .65rem;max-width:100%;overflow:hidden;padding:12px;
        }
        .ob-grid-header {align-items:center;display:flex;gap:1rem;grid-area:header;justify-content:space-between;min-width:0}
        .ob-grid-header h2 {font-size:1.55rem;line-height:1.1;margin:0}.ob-grid-header p {color:var(--ob-text-muted);font-size:.72rem;margin:.18rem 0 0}
        .ob-grid-header .ob-desk-status {flex:0 1 auto;margin:0}
        .ob-grid-kpis {grid-area:kpis;min-width:0}.ob-grid-kpis .ob-desk-kpis {margin:0}
        .ob-grid-performance {grid-area:performance;min-width:0}.ob-grid-risk {grid-area:risk;min-width:0}
        .ob-grid-positions {grid-area:positions;min-width:0}.ob-grid-activity {grid-area:activity;min-width:0}
        .ob-grid-more {grid-area:more;min-width:0}
        .ob-grid-performance > .ob-desk-panel,.ob-grid-risk .ob-desk-panel,.ob-grid-positions > .ob-desk-panel {margin:0}
        .ob-risk-stack {display:grid;gap:12px}.ob-paper-link {background:var(--ob-bg-control);border:1px solid var(--ob-border-default);border-radius:6px;color:var(--ob-gold);font-size:.68rem;padding:.4rem .55rem;text-align:center;text-decoration:none}
        .ob-performance-anchor {align-items:flex-start;display:flex;flex-direction:column;gap:.12rem;padding:.15rem .35rem .6rem}
        .ob-performance-anchor span {color:var(--ob-text-muted);font-size:.62rem;font-weight:800;letter-spacing:.055em}
        .ob-performance-anchor strong {font-size:1.65rem;line-height:1.1}
        .ob-performance-rule {background:linear-gradient(90deg,var(--ob-positive),color-mix(in srgb,var(--ob-positive) 12%,transparent));border-radius:3px;height:3px;margin-top:.35rem;width:100%}
        .ob-best-trade-panel {margin:0}.ob-best-heading {align-items:center;display:flex;gap:.5rem;justify-content:space-between}.ob-best-heading h3 {margin:0}.ob-best-heading strong {font-size:.72rem;white-space:nowrap}
        .ob-best-grid {display:grid;gap:.3rem;grid-template-columns:repeat(5,minmax(0,1fr));margin-top:.45rem}.ob-best-metric {display:flex;flex-direction:column;gap:.12rem;min-width:0}.ob-best-metric span {color:var(--ob-text-muted);font-size:.55rem}.ob-best-metric strong {font-size:.68rem;overflow-wrap:anywhere}
        .ob-best-details {color:var(--ob-text-muted);font-size:.62rem;margin-top:.4rem}.ob-best-details summary {color:var(--ob-gold);cursor:pointer}.ob-best-details p {margin:.25rem 0 0}
        .ob-activity-header {align-items:center;display:grid;gap:.45rem;grid-template-columns:auto minmax(0,1fr) auto;margin-bottom:.35rem}.ob-activity-header h3 {margin:0;white-space:nowrap}
        .ob-activity-filters {background:var(--ob-bg-control);border:1px solid var(--ob-border-default);border-radius:6px;display:flex;min-width:0;overflow-x:auto;white-space:nowrap}
        .ob-activity-filter {border-right:1px solid var(--ob-border-default);color:var(--ob-text-muted);font-size:.56rem;font-weight:800;padding:.28rem .4rem;text-decoration:none}.ob-activity-filter:last-child {border-right:0}.ob-activity-filter.is-active {box-shadow:inset 0 -2px var(--ob-accent-gold);color:var(--ob-gold)}
        .ob-activity-view {color:var(--ob-gold);font-size:.62rem;text-decoration:none;white-space:nowrap}
        .ob-more-stats {background:var(--ob-bg-card);border:1px solid var(--ob-border-default);border-radius:8px;color:var(--ob-text-muted);font-size:.68rem;padding:.48rem .65rem}
        .ob-more-stats summary {color:var(--ob-gold);cursor:pointer;font-size:.64rem;font-weight:800;letter-spacing:.045em;text-transform:uppercase}
        .ob-more-stats-grid {display:grid;gap:0 .8rem;grid-template-columns:repeat(5,minmax(0,1fr));margin-top:.35rem}
        .ob-stat-row {align-items:center;border-right:1px solid var(--ob-border-default);display:flex;flex-direction:column;gap:.15rem;padding:.15rem .35rem}.ob-stat-row:last-child {border-right:0}
        .ob-stat-row span {color:var(--ob-text-muted);font-size:.62rem}.ob-stat-row strong {font-size:.74rem;white-space:nowrap}
        .ob-active-trade {
            background:var(--ob-bg-card); border:1px solid var(--ob-border-default); border-left:3px solid var(--ob-accent-gold);
            border-radius:8px; display:grid; gap:.18rem; margin:.35rem 0; padding:.58rem .72rem;
            max-width:100%; overflow-wrap:anywhere;
        }
        .ob-active-trade-positive {border-left-color:#5fd38b}.ob-active-trade-negative {border-left-color:#d96b72}
        .ob-active-state {color:var(--ob-gold);float:right;font-size:.7rem;font-weight:800;letter-spacing:.06em;margin-left:.7rem}
        .ob-active-result {font-size:1rem;font-weight:800}.ob-active-levels {color:var(--ob-text-muted);font-size:.78rem}
        .ob-paper-status {
            align-items:center;background:var(--ob-bg-card);border:1px solid var(--ob-border-default);
            border-radius:8px;display:flex;flex-wrap:wrap;gap:.45rem 1rem;margin:.25rem 0 .8rem;
            max-width:100%;overflow:hidden;padding:.5rem .7rem;
        }
        .ob-paper-status span {color:var(--ob-text-secondary);font-size:.72rem;font-weight:800;letter-spacing:.05em;white-space:nowrap}
        .ob-paper-status-active {border-color:var(--ob-positive)}
        .ob-paper-status-warning {border-color:var(--ob-warning)}

        @media (max-width: 759px) {
            .ob-trade-dashboard {border-radius:9px;gap:9px;grid-template-areas:"header" "kpis" "positions" "risk" "performance" "activity" "more";grid-template-columns:minmax(0,1fr);padding:9px}
            .ob-grid-header {align-items:flex-start;flex-direction:column}.ob-grid-header .ob-desk-status {width:100%}
            .ob-desk-status {align-items:flex-start;flex-direction:column;gap:.38rem}
            .ob-desk-status-pill + .ob-desk-status-pill::before {content:"";margin:0}
            .ob-desk-kpis {grid-template-columns:repeat(2,minmax(0,1fr))}.ob-desk-kpi {height:3.95rem;min-height:3.95rem;padding:.42rem .5rem}.ob-desk-kpi-label {white-space:normal}
            .ob-performance-grid {grid-template-columns:repeat(2,minmax(0,1fr))}.ob-performance-stat {border-bottom:1px solid var(--ob-border-default);border-right:0}
            .ob-activity-row {grid-template-columns:6.6rem 3.6rem minmax(3rem,.5fr) minmax(5rem,1fr)}.ob-activity-result {grid-column:3/-1;text-align:left}
            .ob-position-scroll {overscroll-behavior-inline:contain}
            .ob-more-stats-grid {grid-template-columns:repeat(2,minmax(0,1fr))}.ob-stat-row {border-bottom:1px solid var(--ob-border-default);border-right:0}
            .ob-active-state {float:none;display:inline-block}.ob-active-result{font-size:.92rem}
            .ob-paper-status {align-items:flex-start;flex-direction:column;gap:.35rem;overflow:visible}
        }

        @media (min-width: 760px) and (max-width: 1099px) {
            .ob-trade-dashboard {grid-template-areas:"header header" "kpis kpis" "positions risk" "performance risk" "activity activity" "more more";grid-template-columns:minmax(0,2fr) minmax(280px,1fr)}
            .ob-risk-stack {grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.ob-risk-stack .ob-paper-link {grid-column:1/-1}
            .ob-desk-kpis {grid-template-columns:repeat(3,minmax(0,1fr))}
            .ob-performance-grid {grid-template-columns:repeat(3,minmax(0,1fr))}
        }

        .brand-row {
            display: flex;
            align-items: center;
            flex-direction: row;
            justify-content: space-between;
            gap: 1rem;
            max-width: 100%;
            min-width: 0;
        }

        .brand-left {
            display: flex;
            align-items: center;
            gap: 1rem;
            justify-content: flex-start;
            flex: 1 1 70%;
            max-width: 70%;
            min-width: 0;
        }

        .brand-logo {
            width: 148px;
            height: 148px;
            object-fit: contain;
            background: var(--ob-bg-page);
            border: 1px solid var(--ob-border-default);
            border-radius: 8px;
            padding: 0;
            flex: 0 0 auto;
        }

        .brand-copy {
            align-items: stretch;
            display: flex;
            flex: 0 1 auto;
            flex-direction: column;
            justify-content: center;
            min-width: 0;
            text-align: left;
            width: fit-content;
        }

        .brand-title {
            color: var(--ob-text);
            font-family: 'Orbitron', 'Source Sans 3', sans-serif;
            font-size: clamp(2rem, 3.65vw, 4rem);
            font-weight: 600;
            letter-spacing: 0.18em;
            line-height: 1;
            margin: 0;
            text-transform: uppercase;
            white-space: nowrap;
        }

        .brand-subtitle {
            color: var(--ob-muted);
            font-size: clamp(0.78rem, 1.7vw, 1rem);
            margin-top: 0.45rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            text-align: center;
            white-space: nowrap;
        }

        .brand-controls {
            align-items: flex-end;
            box-sizing: border-box;
            display: flex;
            flex: 0 1 30%;
            flex-direction: column;
            gap: 0.35rem;
            justify-content: center;
            max-width: 100%;
            min-width: 11rem;
            text-align: right;
        }

        .pill, .signal-pill {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            border: 1px solid var(--ob-border-strong);
            padding: 0.38rem 0.75rem;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: var(--ob-text);
            background: var(--ob-bg-control);
            white-space: nowrap;
        }

        .pill,
        .signal-pill,
        .board-bias-tag,
        .board-callout-chip,
        .factor-pill {
            align-items: center;
            border-radius: 999px;
            box-sizing: border-box;
            display: inline-flex;
            font-size: 0.72rem;
            justify-content: center;
            line-height: 1;
            min-height: 1.8rem;
            padding: 0.32rem 0.65rem;
            vertical-align: middle;
        }

        .pill-market {
            font-size: 0.72rem;
        }

        .pill-secondary {
            font-size: 0.72rem;
            padding: 0.32rem 0.65rem;
        }

        .brand-controls .pill {
            border-radius: 8px;
            border-width: 1px;
            height: 3.375rem;
            min-height: 3.375rem;
            padding: 0.45rem 0.7rem;
            width: 10rem;
        }

        .brand-refresh-label {
            min-width: 10rem;
        }

        .brand-refreshed-at {
            display: block;
            line-height: 1.05;
            text-align: center;
            white-space: nowrap;
        }

        .pill-stack {
            flex-direction: column;
            gap: 0.2rem;
            line-height: 1;
        }

        .pill-subtext {
            color: var(--ob-muted);
            font-size: 0.6rem;
            font-weight: 600;
            letter-spacing: 0;
            text-transform: none;
        }

        .pill-open {
            border-color: color-mix(in srgb, var(--ob-positive) 62%, transparent);
            color: var(--ob-green);
        }

        .pill-closed {
            border-color: var(--ob-border-default);
            color: var(--ob-muted);
        }

        .signal-pill {
            margin: 0.2rem 0 0.8rem;
            width: 100%;
            min-height: 1.8rem;
            font-size: 0.72rem;
        }

        .signal-call {
            border-color: var(--ob-positive);
            color: var(--ob-green);
            background: color-mix(in srgb, var(--ob-positive) 10%, var(--ob-bg-control));
        }

        .signal-put {
            border-color: var(--ob-negative);
            color: var(--ob-red);
            background: var(--ob-wait-bg);
        }

        .signal-wait {
            background: var(--ob-wait-bg);
            border-color: var(--ob-wait-border);
            color: var(--ob-negative);
        }

        .signal-watch {
            background: var(--ob-watch-bg);
            border-color: var(--ob-watch-border);
            color: var(--ob-warning);
        }

        .signal-neutral {
            background: var(--ob-bg-control);
            border-color: var(--ob-border-default);
            color: var(--ob-text-muted);
        }

        .section-title {
            color: var(--ob-text);
            font-size: 2.25rem;
            font-weight: 700;
            letter-spacing: 0;
            line-height: 1.15;
            margin: 0.35rem 0 0.15rem;
        }

        .section-kicker {
            color: var(--ob-muted);
            font-size: 0.95rem;
            letter-spacing: 0.04em;
            margin: 0 0 1.1rem;
            text-transform: uppercase;
        }

        .section-subtitle {
            align-items: center;
            background: var(--ob-bg-card-elevated);
            border: 1px solid var(--ob-border);
            border-left: 6px solid var(--ob-gold);
            border-radius: 8px;
            color: var(--ob-text);
            display: flex;
            font-size: 1.55rem;
            font-weight: 700;
            justify-content: space-between;
            letter-spacing: 0;
            line-height: 1.2;
            margin: 1.2rem 0 0.8rem;
            padding: 0.9rem 1rem;
        }

        .section-count {
            color: var(--ob-muted);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }

        .content-section {
            margin: 0.25rem 0 1rem;
        }

        .content-title {
            color: var(--ob-text);
            font-size: 1.75rem;
            font-weight: 700;
            line-height: 1.2;
            margin: 0;
        }

        .content-kicker {
            color: var(--ob-muted);
            font-size: 0.9rem;
            letter-spacing: 0.04em;
            margin-top: 0.2rem;
            text-transform: uppercase;
        }

        .notice {
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            color: var(--ob-muted);
            font-size: 0.95rem;
            margin: 0.75rem 0 1.25rem;
            padding: 0.75rem 0.9rem;
        }

        .notice-warning {
            background: var(--ob-watch-bg);
            border-color: var(--ob-watch-border);
            color: var(--ob-warning);
        }

        .notice-info {
            background: var(--ob-bg-card);
        }

        .health-grid {
            display: grid;
            gap: 0.7rem;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin-bottom: 0.9rem;
        }

        .health-card {
            background: var(--ob-bg-card-elevated);
            border: 1px solid var(--ob-border-default);
            border-radius: 8px;
            min-height: 6.1rem;
            padding: 0.75rem;
        }

        .journal-summary-card {
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            min-height: 6.1rem;
            padding: 0.75rem;
        }

        .journal-summary-label {
            align-items: flex-start;
            display: flex;
            line-height: 1.2;
            min-height: 1.8rem;
        }

        .journal-summary-value {
            font-size: 1.05rem;
            font-weight: 850;
            line-height: 1.15;
            margin-top: auto;
        }

        .journal-scorecard-summary {
            color: var(--ob-muted);
            font-size: 0.82rem;
            line-height: 1.4;
            margin-top: 0.7rem;
        }

        .health-label {
            color: var(--ob-muted);
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }

        .health-state {
            font-size: 1.05rem;
            font-weight: 850;
            margin-top: 0.25rem;
        }

        .health-detail {
            color: var(--ob-muted);
            font-size: 0.78rem;
            line-height: 1.25;
            margin-top: 0.25rem;
        }

        .health-good {
            color: var(--ob-green);
        }

        .health-warn {
            color: var(--ob-gold);
        }

        .health-bad {
            color: var(--ob-red);
        }

        .empty-state {
            background: var(--ob-bg-empty-state);
            border: 1px dashed var(--ob-border-default);
            border-radius: 8px;
            color: var(--ob-muted);
            padding: 1rem;
            text-align: center;
        }

        .security-symbol {
            color: var(--ob-text);
            font-family: "Arial Black", Impact, Inter, sans-serif;
            font-weight: 900;
            letter-spacing: -0.02em;
            text-shadow:
                0.08rem 0.08rem 0 var(--ob-blue),
                0 0 0.45rem rgba(38, 84, 255, 0.22);
            text-transform: uppercase;
        }

        .ticker-title {
            font-size: 1.28rem;
            line-height: 1.2;
            margin: 0 0 0.65rem;
        }

        .price-metric {
            background: var(--ob-bg-card-elevated);
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            margin-bottom: 0.75rem;
            padding: 0.75rem;
        }

        .price-label {
            color: var(--ob-muted);
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .price-value {
            color: var(--ob-text);
            font-size: 1.45rem;
            font-weight: 700;
            line-height: 1.2;
            margin-top: 0.15rem;
        }

        .opportunity-row {
            align-items: center;
            border-bottom: 1px solid var(--ob-divider);
            display: grid;
            gap: 0.75rem;
            grid-template-columns: minmax(4rem, 0.8fr) minmax(5rem, 0.8fr) minmax(5rem, 0.8fr) 1fr;
            padding: 0.75rem 0;
        }

        .opportunity-heading {
            background: transparent;
            border: 0;
            font-size: 1.75rem;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 0.25rem;
            padding: 0;
        }

        .opportunity-row:last-child {
            border-bottom: 0;
        }

        .opportunity-symbol {
            font-size: 1.2rem;
        }

        .opportunity-score {
            color: var(--ob-gold);
            font-size: 1.15rem;
            font-weight: 700;
        }

        .opportunity-meta {
            color: var(--ob-muted);
            font-size: 0.88rem;
        }

        .opportunity-reason {
            color: var(--ob-muted);
            font-size: 0.92rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .coach-card {
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            background: var(--ob-bg-card);
            padding: 1rem;
            margin-bottom: 0.85rem;
        }

        .coach-card-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            border-bottom: 1px solid var(--ob-divider);
            padding-bottom: 0.75rem;
            margin-bottom: 0.75rem;
        }

        .coach-symbol {
            font-size: 1.75rem;
            line-height: 1.1;
        }

        .coach-grade {
            color: var(--ob-gold);
            font-size: 1.1rem;
            font-weight: 700;
            text-align: right;
        }

        .coach-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.65rem;
            margin: 0.75rem 0;
        }

        .coach-metric {
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            background: var(--ob-bg-card-elevated);
            padding: 0.65rem;
            min-height: 4.2rem;
        }

        .coach-label {
            color: var(--ob-muted);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .coach-value {
            color: var(--ob-text);
            font-size: 1.05rem;
            font-weight: 700;
            margin-top: 0.2rem;
        }

        .decision-summary {
            background: var(--ob-bg-card);
            border: 1px solid var(--ob-border-strong);
            border-left: 6px solid var(--ob-muted);
            border-radius: 8px;
            margin: 0 0 0.85rem;
            padding: 0.85rem;
        }

        .decision-header {
            align-items: flex-start;
            display: flex;
            gap: 0.75rem;
            justify-content: space-between;
            margin-bottom: 0.7rem;
        }

        .decision-symbol {
            font-size: 1.55rem;
            line-height: 1.1;
        }

        .decision-setup {
            color: var(--ob-muted);
            font-size: 0.85rem;
            margin-top: 0.2rem;
        }

        .decision-state {
            border: 1px solid currentColor;
            border-radius: 999px;
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.04em;
            padding: 0.35rem 0.6rem;
            text-transform: uppercase;
            white-space: nowrap;
        }

        .decision-grid {
            display: grid;
            gap: 0.45rem;
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }

        .decision-metric {
            background: var(--ob-bg-card-elevated);
            border: 1px solid var(--ob-border);
            border-radius: 6px;
            min-width: 0;
            padding: 0.5rem 0.55rem;
        }

        .decision-label {
            color: var(--ob-muted);
            font-size: 0.68rem;
            font-weight: 750;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .decision-value {
            color: var(--ob-text);
            font-size: 0.95rem;
            font-weight: 750;
            line-height: 1.2;
            margin-top: 0.15rem;
            overflow-wrap: anywhere;
        }

        .decision-action {
            align-items: center;
            color: var(--ob-text);
            display: flex;
            font-size: 0.9rem;
            gap: 0.45rem;
            justify-content: space-between;
            margin-top: 0.65rem;
        }

        .decision-action span {
            color: var(--ob-muted);
            font-size: 0.72rem;
            text-transform: uppercase;
        }

        .decision-banner {
            border: 1px solid var(--ob-border);
            border-left: 5px solid var(--ob-muted);
            border-radius: 8px;
            margin: 0.35rem 0 0.65rem;
            padding: 0.65rem 0.75rem;
        }

        .decision-positive {
            border-left-color: var(--ob-green);
            color: var(--ob-green);
        }

        .decision-caution {
            border-left-color: var(--ob-gold);
            color: var(--ob-warning);
        }

        .decision-urgent {
            border-left-color: var(--ob-red);
            color: var(--ob-red);
        }

        .decision-muted,
        .decision-neutral {
            border-left-color: var(--ob-muted);
            color: var(--ob-muted);
        }

        .factor-list {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.45rem;
            margin: 0.75rem 0;
        }

        .factor-pill {
            border: 1px solid var(--ob-border);
            border-radius: 999px;
            color: var(--ob-muted);
            background: var(--ob-bg-control);
            padding: 0.32rem 0.65rem;
            font-size: 0.72rem;
        }

        .factor-good {
            border-color: rgba(47, 211, 122, 0.35);
            color: var(--ob-green);
        }

        .factor-warn {
            border-color: rgba(216, 179, 90, 0.35);
            color: var(--ob-warning);
        }

        .why-list {
            color: var(--ob-muted);
            margin: 0.65rem 0 0;
            padding-left: 1rem;
        }

        .why-list li {
            margin-bottom: 0.25rem;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--ob-border);
            border-radius: 8px;
            background: var(--ob-bg-card);
        }

        div[data-testid="stMetric"] {
            background: var(--ob-bg-card-elevated);
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            padding: 0.75rem;
        }

        div[data-testid="stMetricValue"] {
            color: var(--ob-text);
            font-weight: 700;
        }

        div[data-testid="stMetricLabel"] {
            color: var(--ob-muted);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .stAlert {
            border-radius: 8px;
        }

        [data-testid="stDataFrame"] {
            background: var(--ob-bg-card);
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            overflow: hidden;
        }

        div[data-testid="stTabs"] div[role="tablist"],
        .stTabs [data-baseweb="tab-list"] {
            background: transparent;
            border: 0;
            display: grid !important;
            gap: 0.7rem;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            padding: 0;
            margin: 0.15rem 0 0.85rem;
            width: 100%;
        }

        div[data-testid="stTabs"] button[role="tab"],
        .stTabs [data-baseweb="tab"] {
            align-items: flex-start;
            background: var(--ob-bg-control);
            border: 1px solid var(--ob-border-default);
            border-radius: 8px;
            color: var(--ob-muted);
            display: flex !important;
            flex: unset !important;
            font-size: clamp(0.82rem, 1.35vw, 1.05rem);
            font-weight: 800;
            justify-content: flex-start !important;
            min-height: 5.25rem;
            padding: 0.8rem;
            text-align: left;
            width: 100% !important;
        }

        div[data-testid="stTabs"] button[role="tab"] p,
        .stTabs [data-baseweb="tab"] p {
            color: inherit;
            font-size: inherit;
            font-weight: inherit;
            letter-spacing: 0;
            line-height: 1.1;
            margin: 0;
            white-space: normal;
        }

        div[data-testid="stTabs"] button[role="tab"][aria-selected="true"],
        .stTabs [aria-selected="true"] {
            border-color: var(--ob-active-border);
            color: var(--ob-text);
            background: var(--ob-active-bg);
            box-shadow: inset 0 -3px 0 var(--ob-accent-gold-muted);
        }

        div[data-testid="stTabs"] button[role="tab"]:hover {
            background: var(--ob-bg-control-hover);
            border-color: var(--ob-accent-gold-muted);
            color: var(--ob-text);
        }

        div[data-testid="stTabs"] [data-baseweb="tab-highlight"],
        div[data-testid="stTabs"] [data-baseweb="tab-border"],
        .stTabs [data-baseweb="tab-highlight"],
        .stTabs [data-baseweb="tab-border"] {
            display: none !important;
        }

        .beacon-board {
            display: grid;
            gap: 0.65rem;
            grid-template-columns: 1.15fr 1fr 1fr;
            margin-top: 0.2rem;
        }

        .board-panel {
            background: var(--ob-bg-card);
            border: 1px solid var(--ob-border-default);
            border-radius: 8px;
            min-height: 10rem;
            overflow: hidden;
        }

        .board-panel-wide {
            grid-column: span 2;
        }

        .board-panel-full {
            grid-column: 1 / -1;
        }

        .board-header {
            align-items: center;
            background: var(--ob-bg-card-elevated);
            border-bottom: 1px solid var(--ob-divider);
            color: var(--ob-muted);
            display: flex;
            font-size: 0.78rem;
            font-weight: 800;
            justify-content: space-between;
            letter-spacing: 0.1em;
            padding: 0.55rem 0.7rem;
            text-transform: uppercase;
        }

        .board-body {
            padding: 0.6rem 0.7rem;
        }

        .board-row {
            align-items: center;
            border-bottom: 1px solid var(--ob-divider);
            display: grid;
            gap: 0.75rem;
            grid-template-columns: minmax(4rem, 0.62fr) minmax(0, 1.55fr) minmax(2.25rem, 0.28fr);
            min-height: 4.15rem;
            padding: 0.55rem 0;
        }

        .board-row:last-child {
            border-bottom: 0;
        }

        .board-row-compact {
            min-height: 4.15rem;
        }

        .board-symbol {
            font-size: clamp(1rem, 1.2vw, 1.35rem);
            line-height: 1;
        }

        .board-main {
            color: var(--ob-text);
            font-size: 0.92rem;
            font-weight: 700;
            line-height: 1.12;
            text-transform: none;
        }

        .board-titleline {
            align-items: center;
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
        }

        .board-bias-tag {
            border: 1px solid currentColor;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            line-height: 1;
            padding: 0.32rem 0.65rem;
            text-transform: uppercase;
            white-space: nowrap;
        }

        .board-callout {
            align-items: center;
            color: var(--ob-text);
            display: flex;
            flex-wrap: wrap;
            font-size: clamp(0.78rem, 0.85vw, 0.94rem);
            font-weight: 900;
            gap: 0.28rem 0.42rem;
            letter-spacing: 0.05em;
            line-height: 1.08;
            text-transform: uppercase;
            overflow-wrap: anywhere;
        }

        .board-callout-chip {
            background: var(--ob-bg-control);
            border: 1px solid currentColor;
            white-space: nowrap;
        }

        .board-callout-muted {
            color: var(--ob-muted);
            white-space: nowrap;
        }

        .board-sub {
            color: var(--ob-muted);
            font-size: 0.76rem;
            line-height: 1.25;
            margin-top: 0.16rem;
        }

        .board-meta {
            color: var(--ob-muted);
            display: flex;
            flex-wrap: wrap;
            font-size: 0.76rem;
            gap: 0.18rem 0.45rem;
            line-height: 1.2;
            margin-top: 0.18rem;
        }

        .board-meta span {
            white-space: nowrap;
        }

        .board-score {
            align-items: flex-end;
            display: flex;
            flex-direction: column;
            gap: 0.12rem;
            justify-self: end;
            text-align: right;
        }

        .board-number {
            color: var(--ob-gold);
            font-size: 1.04rem;
            font-weight: 800;
            line-height: 1;
        }

        .board-score-label {
            color: var(--ob-muted);
            font-size: 0.62rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .board-green {
            color: var(--ob-green);
        }

        .board-red {
            color: var(--ob-red);
        }

        .board-muted {
            color: var(--ob-muted);
        }

        .board-strip {
            display: grid;
            gap: 0.45rem;
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }

        .board-tile {
            border: 1px solid var(--ob-border-default);
            border-radius: 8px;
            background: var(--ob-bg-card-elevated);
            padding: 0.55rem 0.65rem;
        }

        .board-tile-label {
            font-size: 0.9rem;
        }

        .board-tile-value {
            color: var(--ob-text);
            font-size: 1.2rem;
            font-weight: 800;
            margin-top: 0.15rem;
        }

        .board-note {
            color: var(--ob-muted);
            font-size: 0.85rem;
            line-height: 1.25;
            margin-top: 0.5rem;
        }

        .snapshot-strip {
            display: grid;
            gap: 0.7rem;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin: 0.15rem 0 0.85rem;
        }

        .snapshot-tile {
            background: var(--ob-bg-card-elevated);
            border: 1px solid var(--ob-border-default);
            border-radius: 8px;
            min-height: 6.25rem;
            padding: 0.8rem;
        }

        .snapshot-label {
            color: var(--ob-muted);
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }

        .snapshot-value {
            color: var(--ob-text);
            font-size: 1.25rem;
            font-weight: 800;
            line-height: 1.1;
            margin-top: 0.25rem;
        }

        .snapshot-detail {
            color: var(--ob-muted);
            font-size: 0.84rem;
            line-height: 1.25;
            margin-top: 0.35rem;
        }

        .beacon-tape {
            border: 1px solid var(--ob-border-default);
            border-radius: 8px;
            display: grid;
            grid-template-columns: 1fr 1.15fr 1fr 1fr;
            margin-bottom: 0.85rem;
            overflow: hidden;
        }

        .tape-panel {
            background: var(--ob-bg-card);
            border-right: 1px solid var(--ob-divider);
            min-height: 13rem;
        }

        .tape-panel:last-child {
            border-right: 0;
        }

        .tape-header {
            align-items: center;
            background: var(--ob-bg-card-elevated);
            border-bottom: 1px solid var(--ob-divider);
            color: var(--ob-muted);
            display: flex;
            font-size: 0.75rem;
            font-weight: 900;
            justify-content: space-between;
            letter-spacing: 0.11em;
            padding: 0.5rem 0.65rem;
            text-transform: uppercase;
        }

        .tape-row {
            align-items: center;
            border-bottom: 1px solid var(--ob-divider);
            display: grid;
            gap: 0.45rem;
            grid-template-columns: 0.75fr 0.85fr 0.55fr;
            min-height: 2rem;
            padding: 0.32rem 0.65rem;
        }

        .tape-row:last-child {
            border-bottom: 0;
        }

        .tape-symbol {
            font-size: 1rem;
        }

        .tape-main {
            font-size: 0.95rem;
            font-weight: 900;
            text-align: right;
        }

        .tape-sub {
            color: var(--ob-muted);
            font-size: 0.76rem;
            font-weight: 700;
            text-align: right;
        }

        .tape-green {
            color: var(--ob-green);
        }

        .tape-red {
            color: var(--ob-red);
        }

        .tape-muted {
            color: var(--ob-muted);
        }

        .tape-empty {
            color: var(--ob-muted);
            font-size: 0.85rem;
            line-height: 1.25;
            padding: 0.75rem;
        }

        hr {
            border-color: rgba(255, 255, 255, 0.10);
        }

        .footer-line {
            color: var(--ob-muted);
            font-size: 0.9rem;
            text-align: center;
            padding: 1rem 0 0.4rem;
        }

        .footer-line a {
            color: var(--ob-text);
            text-decoration: none;
            border-bottom: 1px solid var(--ob-border-strong);
        }

        @media (max-width: 760px) {
            .decision-header,
            .decision-action {
                align-items: flex-start;
                flex-direction: column;
            }

            .decision-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .decision-state {
                white-space: normal;
            }

            .brand-row {
                align-items: center;
                flex-direction: column;
            }

            .brand-left {
                gap: 1.25rem;
                max-width: 100%;
                width: 100%;
            }

            .brand-title {
                font-size: clamp(1.15rem, 5.2vw, 1.8rem);
                letter-spacing: 0.08em;
            }

            .brand-controls {
                align-items: center;
                flex: 0 0 auto;
                justify-content: center;
                min-width: 0;
                text-align: center;
                width: 100%;
            }

            .pill-market {
                min-width: 0;
            }

            .brand-logo {
                width: 108px;
                height: 108px;
            }

            .opportunity-row {
                grid-template-columns: 1fr 1fr;
            }

            div[data-testid="stTabs"] div[role="tablist"],
            .stTabs [data-baseweb="tab-list"] {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            div[data-testid="stTabs"] button[role="tab"],
            .stTabs [data-baseweb="tab"] {
                min-height: 4rem;
                padding: 0.65rem;
            }

            .opportunity-reason {
                grid-column: 1 / -1;
            }

            .coach-grid,
            .factor-list,
            .health-grid {
                grid-template-columns: 1fr 1fr;
            }

            .beacon-board {
                grid-template-columns: 1fr;
            }

            .snapshot-strip {
                grid-template-columns: 1fr;
            }

            .beacon-tape {
                grid-template-columns: 1fr;
            }

            .tape-panel {
                border-bottom: 1px solid rgba(255, 255, 255, 0.12);
                border-right: 0;
            }

            .board-panel-wide,
            .board-panel-full {
                grid-column: auto;
            }

            .board-row {
                grid-template-columns: minmax(4.25rem, 0.7fr) minmax(0, 1.45fr) minmax(2rem, 0.25fr);
            }

            .board-strip {
                grid-template-columns: 1fr 1fr;
            }
        }

        @media (max-width: 390px) {
            .brand-left {
                gap: 0.75rem;
            }

            .brand-title {
                font-size: clamp(1rem, 4.8vw, 1.45rem);
                letter-spacing: 0.05em;
            }

            .brand-subtitle {
                font-size: 0.68rem;
                letter-spacing: 0.04em;
            }

            .brand-logo {
                width: 86px;
                height: 86px;
            }

            .health-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """
    st.markdown(
        theme_css.replace("/* OPTIONBEACON_THEME_TOKENS */", css_variables()),
        unsafe_allow_html=True,
    )
