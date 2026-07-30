"""Central visual tokens for the OptionBeacon workstation UI."""

TOKENS = {
    "page_background": "#05090d",
    "panel_background": "#0d141b",
    "panel_elevated": "#111a23",
    "border": "#34404b",
    "border_muted": "rgba(255,255,255,.09)",
    "text_primary": "#f4f6f8",
    "text_secondary": "#b6bec8",
    "text_muted": "#828d99",
    "amber": "#e4bc3e",
    "green": "#4bd16f",
    "red": "#ff5b5f",
    "blue": "#61a9ee",
    "card_radius": "11px",
    "button_radius": "8px",
    "space_compact": "8px",
    "space_standard": "16px",
    "space_section": "24px",
    "font_label": "13px",
    "font_body": "15px",
    "font_value": "22px",
    "font_heading": "46px",
    "line_height": "1.45",
}


def css_variables():
    """Return the tokens as CSS custom properties."""
    names = {
        "page_background": "bg",
        "panel_background": "panel",
        "panel_elevated": "panel-elevated",
        "border": "border",
        "border_muted": "border-muted",
        "text_primary": "text",
        "text_secondary": "text-secondary",
        "text_muted": "text-muted",
        "amber": "amber",
        "green": "green",
        "red": "red",
        "blue": "blue",
        "card_radius": "card-radius",
        "button_radius": "button-radius",
        "space_compact": "space-compact",
        "space_standard": "space-standard",
        "space_section": "space-section",
        "font_label": "font-label",
        "font_body": "font-body",
        "font_value": "font-value",
        "font_heading": "font-heading",
        "line_height": "line-height",
    }
    return ";".join(f"--ob-{names[key]}:{value}" for key, value in TOKENS.items())
