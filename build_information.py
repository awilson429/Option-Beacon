"""Safe, reusable build metadata for OptionBeacon UI surfaces."""

from html import escape
import os
import subprocess


UNKNOWN = "unknown"
BRANCH_ENV_KEYS = ("STREAMLIT_GIT_BRANCH", "GIT_BRANCH")
COMMIT_ENV_KEYS = ("STREAMLIT_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA")
TIMESTAMP_ENV_KEYS = ("STREAMLIT_BUILD_TIMESTAMP", "BUILD_TIMESTAMP")


def _first_value(environ, keys):
    for key in keys:
        value = environ.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return None


def _git_value(*args):
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def short_commit(value):
    """Return a conventional short hash without leaking arbitrary metadata."""
    if not value:
        return UNKNOWN
    cleaned = str(value).strip()
    if not cleaned:
        return UNKNOWN
    return cleaned[:7]


def build_information(*, environ=None, git_reader=None, streamlit_version=None):
    """Collect only allowlisted, non-sensitive deployment metadata."""
    environment = os.environ if environ is None else environ
    read_git = _git_value if git_reader is None else git_reader

    branch = _first_value(environment, BRANCH_ENV_KEYS)
    if not branch:
        branch = read_git("branch", "--show-current") or UNKNOWN

    commit = _first_value(environment, COMMIT_ENV_KEYS)
    if not commit:
        commit = read_git("rev-parse", "--short", "HEAD")

    if streamlit_version is None:
        try:
            import streamlit

            streamlit_version = streamlit.__version__
        except (ImportError, AttributeError):
            streamlit_version = UNKNOWN

    timestamp = _first_value(environment, TIMESTAMP_ENV_KEYS)
    environment_name = "Production" if branch == "main" else "Development"
    return {
        "environment": environment_name,
        "branch": branch,
        "commit": short_commit(commit),
        "streamlit_version": str(streamlit_version or UNKNOWN),
        "build_timestamp": timestamp,
    }


def build_footer_text(info):
    parts = [
        f"Environment: {info['environment']}",
        f"Branch: {info['branch']}",
        f"Commit: {info['commit']}",
        f"Streamlit: {info['streamlit_version']}",
    ]
    if info.get("build_timestamp"):
        parts.append(f"Built: {info['build_timestamp']}")
    return " · ".join(parts)


def render_build_footer(st_module=None, info=None):
    """Render the shared low-priority footer on every main page."""
    if st_module is None:
        import streamlit as st_module

    details = info or build_information()
    text = escape(build_footer_text(details))
    st_module.markdown(
        (
            '<div class="ob-build-footer" '
            'style="margin-top:0.65rem;color:#8f96a1;font-size:0.74rem;'
            'line-height:1.35;text-align:center;">'
            f"{text}</div>"
        ),
        unsafe_allow_html=True,
    )
