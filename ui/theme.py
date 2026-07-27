"""Option Beacon Streamlit page configuration and visual theme."""

import streamlit as st
from streamlit_autorefresh import st_autorefresh


def configure_page():
    st.set_page_config(page_title="Option Beacon", layout="wide")
    st_autorefresh(interval=60000, key="option_beacon_refresh")
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;600;700&family=Source+Sans+3:wght@400;600;700&display=swap');

        :root {
            --ob-bg: #050505;
            --ob-panel: #101010;
            --ob-panel-soft: #151515;
            --ob-border: rgba(255, 255, 255, 0.12);
            --ob-border-strong: rgba(255, 255, 255, 0.22);
            --ob-text: #f7f7f2;
            --ob-muted: #a9aaa5;
            --ob-green: #2fd37a;
            --ob-red: #ff5d5d;
            --ob-gold: #d8b35a;
        }

        html, body, [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at top right, rgba(216, 179, 90, 0.10), transparent 28rem),
                var(--ob-bg);
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
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.02));
            margin-bottom: 0.55rem;
        }

        .brand-row {
            display: flex;
            align-items: center;
            flex-direction: column;
            justify-content: space-between;
            gap: 1rem;
        }

        .brand-left {
            display: flex;
            align-items: center;
            gap: 1rem;
            justify-content: center;
            min-width: 0;
            flex: 1 1 auto;
            width: 100%;
        }

        .brand-logo {
            width: 148px;
            height: 148px;
            object-fit: contain;
            background: #000000;
            border: 1px solid rgba(255, 255, 255, 0.20);
            border-radius: 8px;
            padding: 0;
            flex: 0 0 auto;
        }

        .brand-copy {
            align-items: center;
            display: flex;
            flex-direction: column;
            justify-content: center;
            min-width: 0;
            text-align: center;
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
            white-space: nowrap;
        }

        .status-shell {
            align-items: center;
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            display: flex;
            justify-content: center;
            margin: 0 0 1rem;
            padding: 0.45rem;
        }

        .status-strip {
            display: flex;
            flex-direction: row;
            flex-wrap: wrap;
            gap: 0.55rem;
            align-items: center;
            justify-content: center;
            width: 100%;
        }

        .status-primary,
        .status-secondary {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            justify-content: center;
            align-items: stretch;
        }

        .status-secondary {
            align-items: stretch;
            justify-content: center;
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
            background: rgba(255, 255, 255, 0.04);
            white-space: nowrap;
        }

        .pill-market {
            font-size: 0.74rem;
        }

        .pill-secondary {
            font-size: 0.74rem;
            padding: 0.3rem 0.65rem;
        }

        .status-strip .pill {
            min-height: 2.25rem;
            min-width: 8.25rem;
            padding: 0.3rem 0.65rem;
        }

        .pill-stack {
            flex-direction: column;
            gap: 0.05rem;
            line-height: 1.05;
        }

        .pill-subtext {
            color: var(--ob-muted);
            font-size: 0.64rem;
            font-weight: 600;
            letter-spacing: 0;
            text-transform: none;
        }

        .pill-open {
            border-color: rgba(47, 211, 122, 0.55);
            color: var(--ob-green);
        }

        .pill-closed {
            border-color: rgba(255, 255, 255, 0.18);
            color: var(--ob-muted);
        }

        .signal-pill {
            margin: 0.2rem 0 0.8rem;
            width: 100%;
            min-height: 2.45rem;
            font-size: 1rem;
        }

        .signal-call {
            border-color: rgba(47, 211, 122, 0.75);
            color: var(--ob-green);
            background: rgba(47, 211, 122, 0.09);
        }

        .signal-put {
            border-color: rgba(255, 93, 93, 0.75);
            color: var(--ob-red);
            background: rgba(255, 93, 93, 0.09);
        }

        .signal-wait {
            border-color: rgba(255, 255, 255, 0.18);
            color: var(--ob-muted);
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
            background: rgba(255, 255, 255, 0.045);
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
            background: rgba(216, 179, 90, 0.08);
            border-color: rgba(216, 179, 90, 0.28);
            color: #d9c385;
        }

        .notice-info {
            background: rgba(255, 255, 255, 0.035);
        }

        .health-grid {
            display: grid;
            gap: 0.7rem;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin-bottom: 0.9rem;
        }

        .health-card {
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 8px;
            min-height: 6.1rem;
            padding: 0.75rem;
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
            background: rgba(255, 255, 255, 0.035);
            border: 1px dashed var(--ob-border-strong);
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
            background: rgba(255, 255, 255, 0.035);
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
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
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
            background: linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.018));
            padding: 1rem;
            margin-bottom: 0.85rem;
        }

        .coach-card-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.08);
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
            background: rgba(255,255,255,0.035);
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

        .factor-list {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.45rem;
            margin: 0.75rem 0;
        }

        .factor-pill {
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            color: var(--ob-muted);
            background: rgba(255,255,255,0.025);
            padding: 0.45rem 0.55rem;
            font-size: 0.86rem;
        }

        .factor-good {
            border-color: rgba(47, 211, 122, 0.35);
            color: var(--ob-green);
        }

        .factor-warn {
            border-color: rgba(216, 179, 90, 0.35);
            color: #d9c385;
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
            background: linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.018));
        }

        div[data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.035);
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
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid rgba(255, 255, 255, 0.14);
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
            border-color: rgba(216, 179, 90, 0.85);
            color: var(--ob-text);
            background: linear-gradient(180deg, rgba(216, 179, 90, 0.14), rgba(255, 255, 255, 0.04));
            box-shadow: inset 0 -3px 0 rgba(216, 179, 90, 0.85);
        }

        div[data-testid="stTabs"] button[role="tab"]:hover {
            border-color: rgba(216, 179, 90, 0.55);
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
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.035), rgba(0, 0, 0, 0.05)), #070707;
            border: 1px solid rgba(255, 255, 255, 0.16);
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
            background: rgba(255, 255, 255, 0.055);
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
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
            border-bottom: 1px solid rgba(255, 255, 255, 0.075);
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
            font-size: 0.62rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            line-height: 1;
            padding: 0.22rem 0.42rem;
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
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.035);
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
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid rgba(255, 255, 255, 0.14);
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
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 8px;
            display: grid;
            grid-template-columns: 1fr 1.15fr 1fr 1fr;
            margin-bottom: 0.85rem;
            overflow: hidden;
        }

        .tape-panel {
            background: #050505;
            border-right: 1px solid rgba(255, 255, 255, 0.12);
            min-height: 13rem;
        }

        .tape-panel:last-child {
            border-right: 0;
        }

        .tape-header {
            align-items: center;
            background: rgba(255, 255, 255, 0.04);
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
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
            border-bottom: 1px solid rgba(255, 255, 255, 0.07);
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
            .brand-row {
                align-items: center;
                flex-direction: column;
            }

            .brand-left {
                gap: 1.25rem;
            }

            .brand-title {
                font-size: clamp(1.15rem, 5.2vw, 1.8rem);
                letter-spacing: 0.08em;
            }

            .status-strip {
                align-items: center;
            }

            .status-primary,
            .status-secondary {
                justify-content: center;
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
        """,
        unsafe_allow_html=True,
    )
