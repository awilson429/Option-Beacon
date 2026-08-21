"""OptionBeacon product-shell CSS shared by every Streamlit workspace."""

from html import escape

from ui.design_tokens import css_variables


PRODUCT_SHELL_CSS = f"""
<style>
:root {{{css_variables()}}}
html,body,[data-testid="stAppViewContainer"] {{background:var(--ob-bg-page);color:var(--ob-text-primary)}}
[data-testid="stAppViewContainer"] > .main {{background:radial-gradient(circle at 75% 0,rgba(87,55,156,.10),transparent 31rem),var(--ob-bg-page)}}
[data-testid="stMainBlockContainer"] {{box-sizing:border-box;max-width:1440px!important;padding:1.25rem 1.65rem 2rem!important}}
[data-testid="stSidebar"] {{background:linear-gradient(180deg,#07111d,#030a12)!important;border-right:1px solid var(--ob-border-subtle);min-width:220px!important}}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{padding:1rem .7rem}}
.ob-nav-brand {{border-bottom:1px solid var(--ob-border-subtle);margin:0 0 .8rem;padding:.45rem .55rem 1rem}}
.ob-nav-brand strong {{color:var(--ob-text-primary);display:block;font-size:1.08rem;letter-spacing:.01em}}
.ob-nav-brand span {{color:var(--ob-purple-bright);font-size:.62rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}
.ob-nav-group {{color:var(--ob-text-muted);font-size:.59rem;font-weight:850;letter-spacing:.11em;margin:.95rem .5rem .35rem;text-transform:uppercase}}
.ob-terminal-bar {{align-items:center;border-bottom:1px solid var(--ob-border-subtle);display:flex;justify-content:space-between;margin:-.25rem 0 .85rem;padding:.25rem .1rem .75rem}}.ob-terminal-bar>div{{display:flex;flex-direction:column}}.ob-terminal-bar strong{{font-size:.75rem;letter-spacing:.08em}}.ob-terminal-bar>div span,.ob-terminal-bar aside span{{color:var(--ob-text-muted);font-size:.63rem}}.ob-terminal-bar aside{{align-items:flex-end;display:flex;flex-direction:column}}.ob-terminal-bar aside b{{color:var(--ob-text-muted);font-size:.62rem}}.ob-terminal-bar aside b.is-live{{color:var(--ob-positive)}}
[data-testid="stSidebar"] div[data-testid="stButton"] button {{background:transparent;border:1px solid transparent;border-radius:8px;color:var(--ob-text-secondary);justify-content:flex-start;min-height:2.45rem;padding:.35rem .65rem}}
[data-testid="stSidebar"] div[data-testid="stButton"] button:hover {{background:rgba(139,92,246,.10);border-color:rgba(139,92,246,.32);color:var(--ob-text-primary)}}
[data-testid="stSidebar"] div[data-testid="stButton"] button p {{font-size:.78rem;font-weight:680}}
.ob-nav-active button {{background:linear-gradient(90deg,rgba(139,92,246,.28),rgba(91,59,167,.15))!important;border-color:var(--ob-purple-muted)!important;box-shadow:inset 3px 0 var(--ob-purple)}}
.brand-shell {{background:linear-gradient(135deg,var(--ob-bg-header),var(--ob-bg-card))!important;border-color:var(--ob-border-default)!important;border-radius:var(--ob-card-radius)!important;box-shadow:0 14px 40px rgba(0,0,0,.2);padding:.75rem 1rem!important}}
.brand-logo {{height:48px!important;width:48px!important}}.brand-title {{font-size:1.05rem!important}}.brand-subtitle {{font-size:.63rem!important}}
.content-section {{margin:1.2rem 0 .8rem}}.content-title {{color:var(--ob-text-primary);font-size:1.55rem!important;font-weight:780;letter-spacing:-.02em}}.content-kicker {{color:var(--ob-text-muted);font-size:.78rem}}
div[data-testid="stVerticalBlockBorderWrapper"] {{background:var(--ob-bg-card);border-color:var(--ob-border-default)!important;border-radius:var(--ob-card-radius);box-shadow:0 8px 24px rgba(0,0,0,.15)}}
div[data-testid="stExpander"] {{background:var(--ob-bg-card);border:1px solid var(--ob-border-default)!important;border-radius:var(--ob-card-radius)!important;overflow:hidden}}
div[data-testid="stExpander"] summary:hover {{background:var(--ob-bg-control-hover)}}
div[data-testid="stButton"] button,div[data-testid="stDownloadButton"] button {{background:var(--ob-bg-control);border:1px solid var(--ob-border-default);border-radius:var(--ob-button-radius);color:var(--ob-text-primary);font-weight:720;min-height:2.55rem;transition:background .15s,border-color .15s,transform .15s}}
div[data-testid="stButton"] button:hover,div[data-testid="stDownloadButton"] button:hover {{background:var(--ob-bg-control-hover);border-color:var(--ob-purple);color:var(--ob-purple-bright);transform:translateY(-1px)}}
div[data-testid="stMetric"] {{background:var(--ob-bg-card);border:1px solid var(--ob-border-default);border-radius:var(--ob-card-radius);padding:.8rem .9rem}}
div[data-testid="stMetricLabel"] {{color:var(--ob-text-muted)}} div[data-testid="stMetricValue"] {{color:var(--ob-text-primary)}}
div[data-testid="stDataFrame"] {{background:var(--ob-bg-card);border:1px solid var(--ob-border-default);border-radius:var(--ob-card-radius);overflow:hidden;padding:3px}}
div[data-testid="stTabs"] [role="tablist"] {{border-bottom:1px solid var(--ob-border-default);gap:.35rem}}div[data-testid="stTabs"] button[role="tab"] {{color:var(--ob-text-muted);font-size:.75rem;font-weight:760;padding:.65rem .8rem}}div[data-testid="stTabs"] button[aria-selected="true"] {{color:var(--ob-purple-bright)}}
[data-testid="stAlert"] {{border-radius:var(--ob-card-radius);border-width:1px}}
.ob-product-status-strip {{align-items:center;background:var(--ob-bg-card);border:1px solid var(--ob-border-default);border-radius:var(--ob-card-radius);display:flex;flex-wrap:wrap;gap:.5rem 1.5rem;margin-top:1rem;padding:.65rem .85rem}}.ob-product-status-strip span {{color:var(--ob-text-secondary);font-size:.72rem}}.ob-product-status-strip b {{color:var(--ob-text-muted);font-size:.59rem;letter-spacing:.06em;margin-right:.35rem;text-transform:uppercase}}
.ob-confidence strong {{color:var(--ob-warning);font-size:1.25rem}}.ob-confidence-track {{background:var(--ob-bg-control);border-radius:999px;height:6px;margin:.55rem 0 .3rem;overflow:hidden}}.ob-confidence-track i {{background:linear-gradient(90deg,var(--ob-warning),var(--ob-purple));border-radius:inherit;display:block;height:100%}}.ob-confidence>div:not(.ob-confidence-track) {{display:flex;justify-content:space-between}}.ob-confidence span,.ob-confidence small {{color:var(--ob-text-muted);font-size:.59rem}}
.ob-product-badge {{background:var(--ob-bg-control);border:1px solid var(--ob-border-default);border-radius:999px;color:var(--ob-text-secondary);display:inline-flex;font-size:.62rem;font-weight:850;letter-spacing:.045em;padding:.3rem .62rem;text-transform:uppercase}}.ob-product-badge.is-positive{{background:rgba(40,217,120,.08);border-color:rgba(40,217,120,.45);color:var(--ob-positive)}}.ob-product-badge.is-negative{{background:rgba(240,91,104,.08);border-color:rgba(240,91,104,.45);color:var(--ob-negative)}}.ob-product-badge.is-warning{{color:var(--ob-warning)}}
.ob-product-metric {{background:var(--ob-bg-card);border:1px solid var(--ob-border-default);border-radius:var(--ob-card-radius);display:flex;flex-direction:column;padding:.8rem .9rem}}.ob-product-metric>span{{color:var(--ob-text-muted);font-size:.58rem;font-weight:800;text-transform:uppercase}}.ob-product-metric>strong{{font-size:1.35rem;margin:.2rem 0}}.ob-product-metric>small{{color:var(--ob-text-muted)}}.ob-product-metric.is-positive>strong{{color:var(--ob-positive)}}.ob-product-metric.is-negative>strong{{color:var(--ob-negative)}}
.ob-product-empty {{align-items:center;background:var(--ob-bg-empty-state);border:1px dashed var(--ob-border-default);border-radius:var(--ob-card-radius);display:flex;flex-direction:column;min-height:150px;padding:1.5rem;text-align:center}}.ob-product-empty i{{color:var(--ob-purple);font-size:1.8rem}}.ob-product-empty strong{{margin:.55rem 0 .25rem}}.ob-product-empty span{{color:var(--ob-text-muted);font-size:.76rem}}
.ob-instrument {{align-items:center;background:linear-gradient(135deg,var(--ob-bg-header),var(--ob-bg-card));border:1px solid var(--ob-border-default);border-radius:var(--ob-card-radius);display:grid;gap:1rem;grid-template-columns:auto auto minmax(180px,1fr) auto;margin-bottom:1rem;padding:1rem 1.15rem}}.ob-instrument>div{{align-items:baseline;display:flex;gap:1rem}}.ob-instrument>div b{{font-size:1.45rem}}.ob-instrument>div strong{{font-size:2rem}}.ob-instrument p{{display:flex;flex-direction:column;margin:0!important}}.ob-instrument p span{{color:var(--ob-text-muted);font-size:.62rem;text-transform:uppercase}}.ob-instrument aside{{align-items:flex-end;display:flex;flex-direction:column;gap:.35rem}}.ob-instrument aside small{{color:var(--ob-text-muted)}}
hr {{border-color:var(--ob-border-subtle)!important}}
@media(max-width:900px) {{[data-testid="stMainBlockContainer"]{{padding:1rem!important}}.ob-instrument{{grid-template-columns:1fr auto}}.ob-instrument p{{grid-column:1/-1}}}}
</style>
"""


def status_strip_markup(items):
    body="".join(f'<span><b>{escape(str(label))}</b>{escape(str(value))}</span>' for label,value in items)
    return f'<div class="ob-product-status-strip">{body}</div>'


def confidence_bar_markup(label, score, detail="More data = higher confidence"):
    bounded=max(0,min(100,int(score or 0)))
    tone="positive" if bounded>=75 else "info" if bounded>=45 else "warning"
    return (f'<div class="ob-confidence"><strong class="ob-tone-{tone}">{escape(str(label))}</strong>'
        f'<div class="ob-confidence-track"><i style="width:{bounded}%"></i></div>'
        f'<div><span>LOW</span><span>MEDIUM</span><span>HIGH</span></div><small>{escape(str(detail))}</small></div>')


def badge_markup(label, tone="neutral"):
    return f'<span class="ob-product-badge is-{escape(tone)}">{escape(str(label))}</span>'


def metric_card_markup(label, value, detail=None, tone="neutral"):
    copy=f'<small>{escape(str(detail))}</small>' if detail else ""
    return (f'<div class="ob-product-metric is-{escape(tone)}"><span>{escape(str(label))}</span>'
        f'<strong>{escape(str(value))}</strong>{copy}</div>')


def empty_state_markup(title, message, icon="◇"):
    return (f'<div class="ob-product-empty"><i>{escape(icon)}</i><strong>{escape(str(title))}</strong>'
        f'<span>{escape(str(message))}</span></div>')


def instrument_header_markup(ticker, price, *, bias, regime, setup, updated, status):
    tone="positive" if str(bias).upper() in {"CALL","BULLISH"} else "negative" if str(bias).upper() in {"PUT","BEARISH"} else "neutral"
    return (f'<header class="ob-instrument"><div><b>{escape(str(ticker))}</b><strong>{escape(str(price))}</strong></div>'
        f'{badge_markup(f"{bias} BIAS",tone)}<p><span>{escape(str(regime))}</span>{escape(str(setup))}</p>'
        f'<aside>{badge_markup(status,"positive" if str(status).upper()=="LIVE" else "neutral")}<small>{escape(str(updated))}</small></aside></header>')
