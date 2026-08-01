"""Central semantic visual tokens for the OptionBeacon workstation UI."""

TOKENS = {
    "bg_page": "#071019",
    "bg_header": "#0a131d",
    "bg_card": "#0d1824",
    "bg_card_elevated": "#122131",
    "bg_control": "#101d2a",
    "bg_control_hover": "#17283a",
    "bg_empty_state": "#09141f",
    "border_subtle": "#223244",
    "border_default": "#34495e",
    "border_strong": "#4a6178",
    "divider": "#26394c",
    "text_primary": "#f2f5f7",
    "text_secondary": "#c0c9d3",
    "text_muted": "#8796a6",
    "text_disabled": "#5f6d7b",
    "accent_gold": "#d2ad52",
    "accent_gold_muted": "#92783f",
    "positive": "#49bf7b",
    "negative": "#df666a",
    "warning": "#d2ad52",
    "info": "#68a6d8",
    "watch_bg": "#211d13",
    "watch_border": "#9f833d",
    "wait_bg": "#241619",
    "wait_border": "#9d4b50",
    "active_bg": "#292416",
    "active_border": "#d2ad52",
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
