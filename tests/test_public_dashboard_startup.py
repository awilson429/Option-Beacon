from pathlib import Path

from developer_tools import HOSTED_SECRET_NAMES


def test_app_opens_directly_to_dashboard():
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'type="password"' not in source
    assert "st.stop()" not in source
    assert "render_header()" in source
    assert "active_page = render_card_navigation()" in source


def test_hosted_configuration_banner_is_not_rendered_in_main_workspace():
    source = Path("app.py").read_text(encoding="utf-8")

    assert "Hosted configuration: Ready" not in source
    assert "Hosted configuration incomplete" not in source
    assert "hosted_status = hosted_configuration_status()" not in source
    assert source.index("render_header()") < source.index("scan_symbols()")


def test_hosted_configuration_diagnostics_remain_in_developer_tools():
    app_source = Path("app.py").read_text(encoding="utf-8")
    developer_source = Path("developer_tools.py").read_text(encoding="utf-8")

    assert 'st.markdown("### System Status")' in app_source
    assert "system_status()" in app_source
    assert "def hosted_configuration_status()" in developer_source


def test_hosted_configuration_requires_provider_secrets_only():
    assert HOSTED_SECRET_NAMES == (
        "TRADIER_ACCESS_TOKEN",
        "FINNHUB_API_KEY",
    )
