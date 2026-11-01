from oddscompare import config


def test_streamlit_secrets_reach_the_environment_also_under_a_heading(monkeypatch):
    for name in config.SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    config.apply_secrets({"secrets": {"THE_ODDS_API_KEY": " fake-key \n", "NTFY_TOPIC": "topic"}})
    assert config.api_key("THE_ODDS_API_KEY") == "fake-key" and config.api_key("NTFY_TOPIC") == "topic"


def test_the_top_level_and_the_environment_win(monkeypatch):
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.setenv("NTFY_TOPIC", "from-env")
    config.apply_secrets(
        {"THE_ODDS_API_KEY": "top", "x": {"THE_ODDS_API_KEY": "nested", "NTFY_TOPIC": "nested"}}
    )
    assert config.api_key("THE_ODDS_API_KEY") == "top" and config.api_key("NTFY_TOPIC") == "from-env"


def test_empty_secrets_change_nothing(monkeypatch):
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    config.apply_secrets({"THE_ODDS_API_KEY": "  "})
    assert config.api_key("THE_ODDS_API_KEY") is None
