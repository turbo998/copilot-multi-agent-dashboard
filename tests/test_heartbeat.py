from datetime import datetime, timedelta, timezone

from app.heartbeat import HeartbeatStore
from app.storage import BlobSnapshotCache


def _store(tmp_path):
    return BlobSnapshotCache(
        account_url=f"file://{tmp_path / 'blob'}",
        container="ctr",
        cache_dir=str(tmp_path / "cache"),
    )


def test_write_then_read_all_roundtrip(tmp_path):
    h = HeartbeatStore(_store(tmp_path))
    now = datetime.now(timezone.utc)
    h.write("hermes", now)
    res = h.read_all()
    assert res["hermes"] is not None
    assert abs((res["hermes"] - now).total_seconds()) < 1
    assert res["ghcp"] is None
    assert res["openclaw"] is None


def test_status_classifies(tmp_path):
    h = HeartbeatStore(_store(tmp_path))
    now = datetime.now(timezone.utc)
    h.write("hermes", now)
    h.write("ghcp", now - timedelta(hours=1))

    status = h.status({
        "hermes": timedelta(minutes=5),
        "ghcp": timedelta(minutes=5),
        "openclaw": timedelta(minutes=5),
    })
    assert status["hermes"] == "ok"
    assert status["ghcp"] == "stale"
    assert status["openclaw"] == "missing"


def test_write_default_now(tmp_path):
    h = HeartbeatStore(_store(tmp_path))
    h.write("openclaw")
    res = h.read_all()
    assert res["openclaw"] is not None
    delta = datetime.now(timezone.utc) - res["openclaw"]
    assert abs(delta.total_seconds()) < 5
