from pathlib import Path

import pytest

from app.storage import BlobSnapshotCache


@pytest.fixture
def store(tmp_path):
    blob_root = tmp_path / "blob"
    cache_dir = tmp_path / "cache"
    return BlobSnapshotCache(
        account_url=f"file://{blob_root}",
        container="ctr",
        cache_dir=str(cache_dir),
    )


def test_upload_and_read_text(store):
    store.write_text("foo/bar.txt", "hello")
    assert store.read_text("foo/bar.txt") == "hello"


def test_upload_bytes_roundtrip(store):
    store.upload("data/x.json", b'{"a":1}')
    assert store.read_text("data/x.json") == '{"a":1}'


def test_download_if_changed_caches_and_skips(store, tmp_path):
    store.write_text("snap.json", '{"v":1}')
    p1 = store.download_if_changed("snap.json", "snap.json")
    assert p1.exists()
    assert p1.read_text() == '{"v":1}'

    etag_file = Path(store.cache_dir) / "snap.json.etag.txt"
    etag_before = etag_file.read_text()
    mtime_before = p1.stat().st_mtime_ns

    # Second call without modification: no-op (etag unchanged)
    p2 = store.download_if_changed("snap.json", "snap.json")
    assert p2 == p1
    assert etag_file.read_text() == etag_before
    assert p2.stat().st_mtime_ns == mtime_before


def test_download_if_changed_redownloads_on_change(store):
    store.write_text("snap.json", '{"v":1}')
    p = store.download_if_changed("snap.json", "snap.json")
    assert p.read_text() == '{"v":1}'

    # mutate source
    import time
    time.sleep(0.01)
    store.write_text("snap.json", '{"v":2}')
    p2 = store.download_if_changed("snap.json", "snap.json")
    assert p2.read_text() == '{"v":2}'


def test_download_missing_blob_returns_path(store):
    p = store.download_if_changed("nope.json", "nope.json")
    assert not p.exists()


def test_read_missing_raises(store):
    with pytest.raises(Exception):
        store.read_text("does/not/exist.txt")
