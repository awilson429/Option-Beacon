from ui_modern_style import (
    DEMO_SCORE_FIELDS,
    DEMO_SCORE_SUMMARY,
    MODERN_STYLE_TOKENS,
    MODERN_TOKEN_CSS,
    OPTIONBEACON_NEW_STYLE,
    demo_scorecard_enabled,
    demo_scorecard_presentation,
    inject_modern_style,
    modern_style_active,
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


def test_modern_style_is_active_only_on_develop():
    assert modern_style_active({"new_style": "1"}, "develop") is True
    assert modern_style_active({"new_style": "1"}, "main") is False
    assert modern_style_active({}, "develop") is False


def test_demo_scorecard_requires_both_develop_flags():
    query = {"new_style": "1", "demo_data": "1"}
    assert demo_scorecard_enabled(query, "develop") is True
    assert demo_scorecard_enabled(query, "main") is False
    assert demo_scorecard_enabled({"demo_data": "1"}, "develop") is False
    assert demo_scorecard_enabled({"new_style": "1"}, "develop") is False


def test_demo_scorecard_fixture_has_requested_display_values():
    fields, summary = demo_scorecard_presentation()

    assert fields == DEMO_SCORE_FIELDS
    assert summary == DEMO_SCORE_SUMMARY
    assert dict((label, value) for label, value, _ in fields) == {
        "Opened Alerts": 10,
        "Closed Trades": 10,
        "Winners": 9,
        "Losers": 1,
        "Win Rate": "90.00%",
        "AVG. RETURN": "+0.20%",
    }
    assert "+0.58%" in summary
    assert "-0.73%" in summary
    assert "27.50 minutes" in summary


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
        ("AVG. RETURN", "+0.50%", "positive"),
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


def test_development_indicator_is_explicit_and_optional():
    assert "MODERN STYLE ACTIVE" not in scorecard_markup(())
    assert "MODERN STYLE ACTIVE" in scorecard_markup((), show_indicator=True)
