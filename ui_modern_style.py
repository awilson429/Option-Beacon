"""Opt-in, narrowly scoped visual tokens for incremental UI modernization."""

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

