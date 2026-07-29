"""Opt-in, narrowly scoped visual tokens for incremental UI modernization."""

from html import escape

OPTIONBEACON_NEW_STYLE = False

MODERN_STYLE_TOKENS = {
    "page_background": "#080d12",
    "panel_background": "#10171d",
    "elevated_panel_background": "#141c23",
    "primary_border": "#2c3943",
    "muted_border": "#202b33",
    "primary_text": "#f4f6f8",
    "secondary_text": "#b8c0c8",
    "muted_text": "#818b95",
    "yellow_accent": "#d2ad4f",
    "green_accent": "#42c96b",
    "red_accent": "#ff5a5f",
    "border_radius": "0.75rem",
    "panel_padding": "1rem",
    "standard_gap": "0.75rem",
    "compact_gap": "0.45rem",
    "heading_size": "1.2rem",
    "label_size": "0.78rem",
    "body_size": "0.95rem",
}

MODERN_TOKEN_CSS = """
<style>
.ob-modern-shell {
    --ob-page-background: #080d12;
    --ob-panel-background: #10171d;
    --ob-elevated-panel-background: #141c23;
    --ob-primary-border: #2c3943;
    --ob-muted-border: #202b33;
    --ob-primary-text: #f4f6f8;
    --ob-secondary-text: #b8c0c8;
    --ob-muted-text: #818b95;
    --ob-yellow-accent: #d2ad4f;
    --ob-green-accent: #42c96b;
    --ob-red-accent: #ff5a5f;
    --ob-border-radius: 0.75rem;
    --ob-panel-padding: 1rem;
    --ob-standard-gap: 0.75rem;
    --ob-compact-gap: 0.45rem;
    --ob-heading-size: 1.2rem;
    --ob-label-size: 0.78rem;
    --ob-body-size: 0.95rem;
}
</style>
"""

SCORECARD_CSS = """
<style>
.ob-modern-shell.ob-scorecard {
    margin: 1rem 0 0;
}
.ob-modern-shell .ob-section-header {
    color: var(--ob-primary-text);
    font-size: var(--ob-heading-size);
    font-weight: 700;
    line-height: 1.25;
    margin: 0 0 var(--ob-standard-gap);
}
.ob-modern-shell .ob-scorecard-grid {
    display: grid;
    gap: var(--ob-standard-gap);
    grid-template-columns: repeat(6, minmax(0, 1fr));
}
.ob-modern-shell .ob-scorecard-card {
    background: var(--ob-panel-background);
    border: 1px solid var(--ob-primary-border);
    border-radius: var(--ob-border-radius);
    min-width: 0;
    padding: var(--ob-panel-padding);
}
.ob-modern-shell .ob-scorecard-label {
    color: var(--ob-muted-text);
    font-size: var(--ob-label-size);
    font-weight: 650;
    letter-spacing: 0.025em;
    line-height: 1.3;
    margin-bottom: var(--ob-compact-gap);
}
.ob-modern-shell .ob-scorecard-value {
    color: var(--ob-primary-text);
    font-size: 1.35rem;
    font-weight: 750;
    line-height: 1.15;
}
.ob-modern-shell .ob-scorecard-card.ob-positive .ob-scorecard-value {
    color: var(--ob-green-accent);
}
.ob-modern-shell .ob-scorecard-card.ob-negative .ob-scorecard-value {
    color: var(--ob-red-accent);
}
.ob-modern-shell .ob-scorecard-summary {
    color: var(--ob-secondary-text);
    font-size: var(--ob-body-size);
    margin-top: var(--ob-standard-gap);
}
@media (max-width: 900px) {
    .ob-modern-shell .ob-scorecard-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
}
@media (max-width: 600px) {
    .ob-modern-shell .ob-scorecard-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
</style>
"""


def modern_style_enabled(query_params=None):
    """Return whether the temporary modern style flag is explicitly enabled."""
    if query_params is None:
        return OPTIONBEACON_NEW_STYLE
    requested = query_params.get("new_style")
    if isinstance(requested, (list, tuple)):
        requested = requested[0] if requested else None
    if requested is None:
        return OPTIONBEACON_NEW_STYLE
    return str(requested).strip().lower() in {"1", "true", "on", "yes"}


def inject_modern_style(st_module, enabled=False):
    """Inject scoped token variables only when the feature flag is enabled."""
    if enabled:
        st_module.markdown(MODERN_TOKEN_CSS, unsafe_allow_html=True)


def scorecard_markup(score_fields, summary=None):
    """Build presentation-only markup from already calculated Scorecard values."""
    cards = []
    for label, value, treatment in score_fields:
        safe_treatment = treatment if treatment in {"positive", "negative"} else "neutral"
        cards.append(
            f'<div class="ob-scorecard-card ob-{safe_treatment}">'
            f'<div class="ob-scorecard-label">{escape(str(label))}</div>'
            f'<div class="ob-scorecard-value">{escape(str(value))}</div>'
            "</div>"
        )
    summary_markup = (
        f'<div class="ob-scorecard-summary">{escape(str(summary))}</div>'
        if summary
        else ""
    )
    return (
        '<section class="ob-modern-shell ob-scorecard">'
        '<div class="ob-section-header">Today&#39;s Scorecard</div>'
        f'<div class="ob-scorecard-grid">{"".join(cards)}</div>'
        f"{summary_markup}</section>"
    )


def render_modern_scorecard(st_module, score_fields, summary=None):
    """Render only the opt-in Scorecard presentation."""
    inject_modern_style(st_module, enabled=True)
    st_module.markdown(SCORECARD_CSS, unsafe_allow_html=True)
    st_module.markdown(
        scorecard_markup(score_fields, summary),
        unsafe_allow_html=True,
    )
