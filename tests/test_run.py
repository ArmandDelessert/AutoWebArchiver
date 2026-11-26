import json
import threading

from autowebarchiver import main
from autowebarchiver.state.dropped_urls import DroppedUrlsStore
from autowebarchiver.state.feed_stats import DroppedUrl

_CONFIG = """
sources:
  - name: s
    type: rss
    url: https://example.com/feed.xml
"""


def test_run_rechecks_dropped_urls_while_archiving(tmp_path, monkeypatch):
    config_path = tmp_path / "sources.yaml"
    config_path.write_text(_CONFIG, encoding="utf-8")
    dropped_path = tmp_path / "dropped_urls.json"
    seeded = DroppedUrlsStore(dropped_path)
    seeded.record("s", [DroppedUrl(url="https://example.com/archived", reason="gave_up")])
    seeded.save()

    archiving_started = threading.Event()
    checked_during_archiving = []

    def checker(url):
        # Would time out (False) if the re-check ran before archiving started.
        checked_during_archiving.append(archiving_started.wait(timeout=5))
        return True

    def fake_archive(*args, **kwargs):
        archiving_started.set()
        counts = dict.fromkeys(
            ["success", "error", "pending", "already_archived", "error_retry", "error_permanent"], 0
        )
        return counts, {}, {}, 0

    monkeypatch.setenv("ARCHIVE_ORG_ACCESS_KEY", "fake")
    monkeypatch.setenv("ARCHIVE_ORG_SECRET_KEY", "fake")
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main, "load_dotenv", lambda: None)
    monkeypatch.setattr(main, "discover_source", lambda source: [])
    monkeypatch.setattr(main, "poll_leftovers", lambda *args: {})
    monkeypatch.setattr(main, "wayback_is_archived", checker)
    monkeypatch.setattr(main, "archive_new_urls", fake_archive)

    code = main.run(
        config_path=config_path,
        state_path=tmp_path / "seen.json",
        feed_stats_path=tmp_path / "feed_stats.json",
        run_history_path=tmp_path / "run_history.json",
        dropped_urls_path=dropped_path,
    )

    assert code == 0
    assert checked_during_archiving == [True]
    # The re-check was joined before saving: its removal reached the disk.
    assert json.loads(dropped_path.read_text(encoding="utf-8")) == []
