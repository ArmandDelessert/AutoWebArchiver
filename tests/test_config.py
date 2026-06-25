import pytest

from autowebarchiver.config import ConfigError, load_config

_VALID_SOURCE = """
sources:
  - name: example
    type: rss
    url: https://example.com/feed
"""


def _write(tmp_path, text):
    path = tmp_path / "sources.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_config(tmp_path):
    config = load_config(_write(tmp_path, _VALID_SOURCE))
    assert len(config.sources) == 1
    assert config.sources[0].name == "example"


def test_duplicate_source_name_rejected(tmp_path):
    text = """
sources:
  - name: dup
    type: rss
    url: https://example.com/a
  - name: dup
    type: rss
    url: https://example.com/b
"""
    with pytest.raises(ConfigError, match="duplicate name 'dup'"):
        load_config(_write(tmp_path, text))


@pytest.mark.parametrize("value", ["12h", "5d", "1M", "30", "2w", "1y"])
def test_valid_if_not_archived_within(tmp_path, value):
    text = _VALID_SOURCE + f"\nsettings:\n  if_not_archived_within: \"{value}\"\n"
    config = load_config(_write(tmp_path, text))
    assert config.settings.if_not_archived_within == value


@pytest.mark.parametrize("value", ["3days", "h", "1.5d", "1 d", ""])
def test_invalid_if_not_archived_within_rejected(tmp_path, value):
    text = _VALID_SOURCE + f"\nsettings:\n  if_not_archived_within: \"{value}\"\n"
    with pytest.raises(ConfigError, match="Invalid if_not_archived_within"):
        load_config(_write(tmp_path, text))


def test_unknown_setting_key_rejected(tmp_path):
    text = _VALID_SOURCE + "\nsettings:\n  bogus_option: 1\n"
    with pytest.raises(ConfigError, match="Invalid settings"):
        load_config(_write(tmp_path, text))
