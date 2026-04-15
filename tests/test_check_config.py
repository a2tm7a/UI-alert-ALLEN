"""
Unit tests for url_config.UrlConfig — URL and auth-session configuration loader.

Tests cover: YAML loading, missing file graceful degradation, guest task list,
stream-filtered task list, auth session profile mapping, and empty streams fallback.
"""
import textwrap
import pytest
from url_config import UrlConfig, AuthSession, UrlEntry


def test_load_valid_config(tmp_path):
    """UrlConfig.load() parses a valid YAML file and returns a UrlConfig instance."""
    config_file = tmp_path / "urls.yaml"
    config_file.write_text(textwrap.dedent("""\
        version: 1
        auth_sessions:
          - stream: JEE
            class: "11th"
          - stream: NEET
            class: "12th"
        urls:
          - url: https://allen.in/
            section: HOME
          - url: https://allen.in/jee/online-coaching-class-11
            section: PLP_PAGES
            streams: [JEE]
    """))

    config = UrlConfig.load(str(config_file))

    assert config.version == 1
    assert len(config.auth_sessions) == 2
    assert len(config.urls) == 2


def test_load_missing_file():
    """UrlConfig.load() returns an empty config when the file does not exist."""
    result = UrlConfig.load("/tmp/definitely_not_here_watchdog_99999.yaml")

    assert isinstance(result, UrlConfig)
    assert result.urls == []
    assert result.auth_sessions == []


def test_get_all_tasks_returns_every_url(tmp_path):
    """get_all_tasks() returns (section, url) tuples for every URL entry."""
    config_file = tmp_path / "urls.yaml"
    config_file.write_text(textwrap.dedent("""\
        version: 1
        urls:
          - url: https://allen.in/
            section: HOME
          - url: https://allen.in/jee/online-coaching-class-11
            section: PLP_PAGES
            streams: [JEE]
          - url: https://allen.in/jee/results-2025
            section: RESULTS_PAGES
    """))

    config = UrlConfig.load(str(config_file))
    tasks = config.get_all_tasks()

    assert len(tasks) == 3
    assert ("HOME", "https://allen.in/") in tasks
    assert ("PLP_PAGES", "https://allen.in/jee/online-coaching-class-11") in tasks
    assert ("RESULTS_PAGES", "https://allen.in/jee/results-2025") in tasks


def test_get_tasks_for_stream_filters_correctly():
    """get_tasks_for_stream() returns only URLs tagged for that stream."""
    config = UrlConfig(
        urls=[
            UrlEntry(url="https://allen.in/", section="HOME", streams=[]),
            UrlEntry(url="https://allen.in/jee/online-coaching-class-11", section="PLP_PAGES", streams=["JEE"]),
            UrlEntry(url="https://allen.in/neet/online-coaching-class-11", section="PLP_PAGES", streams=["NEET"]),
            UrlEntry(url="https://allen.in/jee/results-2025", section="RESULTS_PAGES", streams=[]),
        ]
    )

    jee_tasks = config.get_tasks_for_stream("JEE")
    neet_tasks = config.get_tasks_for_stream("NEET")
    class610_tasks = config.get_tasks_for_stream("Class 6-10")

    assert jee_tasks == [("PLP_PAGES", "https://allen.in/jee/online-coaching-class-11")]
    assert neet_tasks == [("PLP_PAGES", "https://allen.in/neet/online-coaching-class-11")]
    assert class610_tasks == []


def test_guest_only_urls_excluded_from_stream_tasks():
    """URLs with no streams tag are excluded from all stream-filtered task lists."""
    config = UrlConfig(
        urls=[
            UrlEntry(url="https://allen.in/", section="HOME"),
            UrlEntry(url="https://allen.in/jee/results-2025", section="RESULTS_PAGES"),
        ]
    )

    assert config.get_tasks_for_stream("JEE") == []
    assert config.get_tasks_for_stream("NEET") == []
    # But both appear in the guest pass
    assert len(config.get_all_tasks()) == 2


def test_auth_session_profile_mapping():
    """AuthSession.auth_profile maps stream names to switch_profile() keys correctly."""
    assert AuthSession(stream="JEE", **{"class": "11th"}).auth_profile == "JEE"
    assert AuthSession(stream="NEET", **{"class": "12th"}).auth_profile == "NEET"
    assert AuthSession(stream="Class 6-10", **{"class": "8th"}).auth_profile == "Classes610"


def test_auth_session_unknown_stream_raises():
    """AuthSession.auth_profile raises ValueError for an unrecognised stream."""
    sess = AuthSession(stream="UNKNOWN", **{"class": "11th"})
    with pytest.raises(ValueError, match="Unknown stream"):
        _ = sess.auth_profile


def test_class610_session_has_board_default():
    """AuthSession for Class 6-10 defaults to CBSE when board is not specified."""
    sess = AuthSession(stream="Class 6-10", **{"class": "8th"})
    assert sess.board == "CBSE"
