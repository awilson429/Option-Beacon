"""Central semantic visual tokens for the OptionBeacon workstation UI."""

TOKENS = {
    "bg_page": "#030a13",
    "bg_header": "#06111d",
    "bg_nav": "#050d17",
    "bg_card": "#091522",
    "bg_card_secondary": "#0b1928",
    "bg_card_elevated": "#0e2031",
    "bg_control": "#0c1a29",
    "bg_control_hover": "#13283b",
    "bg_empty_state": "#07131f",
    "border_subtle": "#172a3d",
    "border_default": "#263c52",
    "border_strong": "#36516d",
    "divider": "#1b3145",
    "text_primary": "#f4f7fb",
    "text_secondary": "#bdc8d5",
    "text_muted": "#7f91a5",
    "text_disabled": "#5f6d7b",
    "purple": "#8b5cf6",
    "purple_bright": "#a879ff",
    "purple_muted": "#5b3ba7",
    "accent_gold": "#a879ff",
    "accent_gold_muted": "#5b3ba7",
    "positive": "#28d978",
    "negative": "#f05b68",
    "warning": "#f3a61d",
    "info": "#45b7e8",
    "watch_bg": "#17122b",
    "watch_border": "#7548d8",
    "wait_bg": "#17122b",
    "wait_border": "#6844b7",
    "active_bg": "#17122b",
    "active_border": "#8b5cf6",
    "card_radius": "12px",
    "button_radius": "9px",
    "space_compact": "8px",
    "space_standard": "16px",
    "space_section": "24px",
    "font_label": "13px",
    "font_body": "15px",
    "font_value": "22px",
    "font_heading": "46px",
    "line_height": "1.45",
}


COMPATIBILITY_ALIASES = {
    "bg": "bg-page",
    "panel": "bg-card",
    "panel-elevated": "bg-card-elevated",
    "border": "border-default",
    "border-muted": "border-subtle",
    "text": "text-primary",
    "amber": "accent-gold",
    "green": "positive",
    "red": "negative",
    "blue": "info",
    "muted": "text-muted",
    "gold": "accent-gold",
}


def css_variables():
    """Return the semantic palette plus compatibility aliases for existing UI."""
    variables = [
        f"--ob-{name.replace('_', '-')}:{value}" for name, value in TOKENS.items()
    ]
    variables.extend(
        f"--ob-{alias}:var(--ob-{target})"
        for alias, target in COMPATIBILITY_ALIASES.items()
    )
    return ";".join(variables)
