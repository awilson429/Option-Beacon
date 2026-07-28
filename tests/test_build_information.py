from pathlib import Path

from build_information import (
    build_footer_text,
    build_information,
    render_build_footer,
    short_commit,
)


def no_git(*_args):
    return None


def test_development_environment_rendering():
    info = build_information(
        environ={"STREAMLIT_GIT_BRANCH": "develop", "GIT_COMMIT": "3068eeeff"},
        git_reader=no_git,
        streamlit_version="1.60.0",
    )

    assert info["environment"] == "Development"
    assert "Environment: Development" in build_footer_text(info)
    assert "Branch: develop" in build_footer_text(info)


def test_production_environment_rendering():
    info = build_information(
        environ={"STREAMLIT_GIT_BRANCH": "main", "GIT_COMMIT": "abcdef123"},
        git_reader=no_git,
        streamlit_version="1.60.0",
    )

    assert info["environment"] == "Production"
    assert "Environment: Production" in build_footer_text(info)


def test_missing_branch_and_commit_metadata_fall_back_safely():
    info = build_information(
        environ={},
        git_reader=no_git,
        streamlit_version="1.60.0",
    )

    assert info["branch"] == "unknown"
    assert info["commit"] == "unknown"


def test_short_commit_formatting():
    assert short_commit("1a8cb49a2a90d8d") == "1a8cb49"
    assert short_commit(None) == "unknown"


def test_streamlit_version_and_optional_timestamp_display():
    info = build_information(
        environ={
            "STREAMLIT_GIT_BRANCH": "develop",
            "GIT_COMMIT": "123456789",
            "BUILD_TIMESTAMP": "2026-07-28T12:00:00Z",
        },
        git_reader=no_git,
        streamlit_version="1.60.0",
    )
    text = build_footer_text(info)

    assert "Streamlit: 1.60.0" in text
    assert "Built: 2026-07-28T12:00:00Z" in text


def test_secret_values_are_never_rendered():
    secret = "super-secret-token"
    info = build_information(
        environ={
            "STREAMLIT_GIT_BRANCH": "develop",
            "GIT_COMMIT": "123456789",
            "TRADIER_ACCESS_TOKEN": secret,
            "FINNHUB_API_KEY": secret,
            "APP_ACCESS_CODE": secret,
        },
        git_reader=no_git,
        streamlit_version="1.60.0",
    )

    assert secret not in build_footer_text(info)
    assert all("TOKEN" not in value for value in info.values() if isinstance(value, str))


def test_footer_renderer_uses_shared_low_priority_markup():
    calls = []

    class FakeStreamlit:
        @staticmethod
        def markdown(body, **kwargs):
            calls.append((body, kwargs))

    render_build_footer(
        FakeStreamlit,
        {
            "environment": "Development",
            "branch": "develop",
            "commit": "1234567",
            "streamlit_version": "1.60.0",
            "build_timestamp": None,
        },
    )

    assert len(calls) == 1
    assert "ob-build-footer" in calls[0][0]
    assert calls[0][1]["unsafe_allow_html"] is True


def test_footer_appears_through_shared_app_layout():
    source = Path("app.py").read_text(encoding="utf-8")

    assert source.count("render_build_footer()") == 1
    assert source.index("render_build_footer()") > source.index("active_page = render_card_navigation()")
