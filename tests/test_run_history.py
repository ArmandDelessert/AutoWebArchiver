import json

from autowebarchiver.state.run_history import RunHistoryStore


def test_record_appends_a_timestamped_entry(tmp_path):
    store = RunHistoryStore(tmp_path / "run_history.json")

    store.record(success=10, error=2, discovered=20)

    assert len(store._runs) == 1
    entry = store._runs[0]
    assert entry["success"] == 10
    assert entry["error"] == 2
    assert entry["discovered"] == 20
    assert "timestamp" in entry


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "run_history.json"
    store = RunHistoryStore(path)
    store.record(success=5, error=0)
    store.save()

    on_disk = json.loads(path.read_text())
    assert len(on_disk) == 1
    assert on_disk[0]["success"] == 5

    reloaded = RunHistoryStore(path)
    reloaded.record(success=3, error=1)
    assert len(reloaded._runs) == 2


def test_purge_older_than_removes_stale_runs(tmp_path):
    store = RunHistoryStore(tmp_path / "run_history.json")
    store.record(success=1)
    store._runs[0]["timestamp"] = "2000-01-01T00:00:00Z"
    store.record(success=2)

    purged = store.purge_older_than(days=90)

    assert purged == 1
    assert len(store._runs) == 1
    assert store._runs[0]["success"] == 2
