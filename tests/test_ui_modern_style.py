from ui_modern_style import (
    MODERN_STYLE_TOKENS,
    MODERN_TOKEN_CSS,
    OPTIONBEACON_NEW_STYLE,
    inject_modern_style,
    modern_style_enabled,
    render_modern_scorecard,
    scorecard_markup,
)


class FakeStreamlit:
    def __init__(self):
        self.calls = []

    def markdown(self, value, **kwargs):
        self.calls.append((value, kwargs))


def test_modern_style_defaults_off():
    assert OPTIONBEACON_NEW_STYLE is False
    assert modern_style_enabled() is False
    assert modern_style_enabled({}) is False


def test_modern_style_requires_explicit_query_opt_in():
    assert modern_style_enabled({"new_style": "1"}) is True
    assert modern_style_enabled({"new_style": ["true"]}) is True
    assert modern_style_enabled({"new_style": "off"}) is False


def test_tokens_cover_the_incremental_design_system():
    assert MODERN_STYLE_TOKENS == {
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


def test_token_css_is_narrowly_scoped():
    assert ".ob-modern-shell" in MODERN_TOKEN_CSS
    for forbidden in ("button {", "table {", "section {", "nth-child"):
        assert forbidden not in MODERN_TOKEN_CSS


def test_token_injection_is_flag_gated():
    fake = FakeStreamlit()

    inject_modern_style(fake, enabled=False)
    assert fake.calls == []

    inject_modern_style(fake, enabled=True)
    assert len(fake.calls) == 1
    assert fake.calls[0][1]["unsafe_allow_html"] is True


def test_scorecard_markup_preserves_labels_values_and_treatments():
    fields = (
        ("Opened Alerts", 4, "neutral"),
        ("Closed Trades", 3, "neutral"),
        ("Winners", 1, "positive"),
        ("Losers", 1, "negative"),
        ("Win Rate", "50.00%", "neutral"),
        ("Average Realized Return", "+0.50%", "positive"),
    )

    markup = scorecard_markup(
        fields,
        "Best trade +2.00% · Worst trade -1.00% · Average hold 30 minutes",
    )

    for label, value, _treatment in fields:
        assert label in markup
        assert str(value) in markup
    assert "ob-scorecard-grid" in markup
    assert "ob-positive" in markup
    assert "ob-negative" in markup
    assert "Best trade +2.00%" in markup
    assert "Worst trade -1.00%" in markup
    assert "Average hold 30 minutes" in markup


def test_modern_scorecard_renderer_is_scoped_and_presentation_only():
    fake = FakeStreamlit()
    fields = (("Opened Alerts", 0, "neutral"),)

    render_modern_scorecard(fake, fields)

    rendered = "\n".join(call[0] for call in fake.calls)
    assert ".ob-modern-shell .ob-scorecard-card" in rendered
    assert '<section class="ob-modern-shell ob-scorecard">' in rendered
    assert "daily_scorecard" not in rendered
