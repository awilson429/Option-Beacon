from pathlib import Path

from app import header_markup


TIMESTAMP = "2026-07-31 10:42:18 AM ET"


def test_status_controls_render_inside_one_brand_header():
    markup = header_markup(True, TIMESTAMP, "logo.png")

    assert markup.count('class="brand-shell"') == 1
    assert 'class="brand-controls"' in markup
    assert "status-shell" not in markup
    assert "status-strip" not in markup


def test_market_state_remains_dynamic_and_uses_existing_treatments():
    open_markup = header_markup(True, TIMESTAMP, "logo.png")
    closed_markup = header_markup(False, TIMESTAMP, "logo.png")

    assert "Market Open" in open_markup
    assert "pill-open" in open_markup
    assert "Market Closed" in closed_markup
    assert "pill-closed" in closed_markup


def test_refresh_label_timestamp_and_branding_remain_present():
    markup = header_markup(True, TIMESTAMP, "logo.png")

    assert "Option Beacon" in markup
    assert "ETF + Single Stock Scanner" in markup
    assert "Refresh 1 min" in markup
    assert f"Last refreshed {TIMESTAMP}" in markup
    assert 'src="logo.png"' in markup


def test_shared_css_uses_single_desktop_row_and_internal_responsive_fallback():
    source = Path("ui/theme.py").read_text(encoding="utf-8")
    compact = source.replace(" ", "").replace("\n", "").lower()

    assert ".brand-row{" in compact
    assert "flex-direction:row" in compact
    assert ".brand-controls{" in compact
    assert "max-width:100%" in compact
    assert "@media(max-width:760px)" in compact
    mobile = compact.split("@media(max-width:760px)", 1)[1]
    assert ".brand-row{" in mobile
    assert "flex-direction:column" in mobile
    assert ".brand-controls{" in mobile
    assert "width:100%" in mobile


def test_standalone_status_container_css_is_removed():
    source = Path("ui/theme.py").read_text(encoding="utf-8")

    assert ".status-shell" not in source
    assert ".status-strip" not in source
