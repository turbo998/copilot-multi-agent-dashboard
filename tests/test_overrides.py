import pytest

from app.models import UnifiedSession
from app.overrides import OverridesStore
from app.storage import BlobSnapshotCache


def _store(tmp_path):
    return BlobSnapshotCache(
        account_url=f"file://{tmp_path / 'blob'}",
        container="ctr",
        cache_dir=str(tmp_path / "cache"),
    )


def _mk_session(uid: str, source: str = "hermes") -> UnifiedSession:
    return UnifiedSession(
        id=uid,
        source=source,
        title=f"t-{uid}",
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
        turns=1,
        model="gpt-test",
        cwd=None,
        first_user_msg="hi",
        body="body",
    )


def test_set_and_save_and_load_roundtrip(tmp_path):
    s = _store(tmp_path)
    o = OverridesStore(s)
    o.load()
    o.set_cat("a", "research")
    o.set_group("a", "g1")
    o.hide("b")
    o.save_all()

    o2 = OverridesStore(s)
    o2.load()
    assert o2.cats == {"a": "research"}
    assert o2.groups == {"a": "g1"}
    assert o2.hidden == {"b"}


def test_unhide_and_clear_cat(tmp_path):
    s = _store(tmp_path)
    o = OverridesStore(s)
    o.load()
    o.set_cat("x", "c1")
    o.hide("x")
    o.unhide("x")
    o.set_cat("x", None)
    o.save_all()

    o2 = OverridesStore(s)
    o2.load()
    assert "x" not in o2.cats
    assert "x" not in o2.hidden


def test_apply_mutates_sessions(tmp_path):
    s = _store(tmp_path)
    o = OverridesStore(s)
    o.load()
    o.set_cat("a", "research")
    o.set_group("b", "grp1")
    o.hide("c")

    sessions = [_mk_session("a"), _mk_session("b"), _mk_session("c"), _mk_session("d")]
    o.apply(sessions)

    by_id = {s.id: s for s in sessions}
    assert by_id["a"].cat == "research"
    assert by_id["b"].group_id == "grp1"
    assert by_id["c"].hidden is True
    assert by_id["d"].cat == "uncategorized"
    assert by_id["d"].hidden is False


def test_gc_prunes_orphans(tmp_path):
    s = _store(tmp_path)
    o = OverridesStore(s)
    o.load()
    o.set_cat("a", "x")
    o.set_cat("b", "y")
    o.set_group("a", "g")
    o.set_group("c", "g2")
    o.hide("d")
    o.hide("a")

    pruned = o.gc({"a"})
    # b cat (1) + c group (1) + d hidden (1) = 3
    assert pruned == 3
    assert o.cats == {"a": "x"}
    assert o.groups == {"a": "g"}
    assert o.hidden == {"a"}


def test_gc_zero_when_all_present(tmp_path):
    s = _store(tmp_path)
    o = OverridesStore(s)
    o.load()
    o.set_cat("a", "x")
    assert o.gc({"a", "b"}) == 0
