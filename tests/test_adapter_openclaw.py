import os
import pytest

from app.adapters.openclaw import OpenClawAdapter
from app.adapters.base import SchemaMismatchError


def test_schema_check_missing_dir_ok(tmp_path):
    OpenClawAdapter(str(tmp_path / 'nope')).schema_check()


def test_schema_check_ok(openclaw_dir):
    OpenClawAdapter(openclaw_dir).schema_check()


def test_schema_check_bad(openclaw_dir_bad):
    with pytest.raises(SchemaMismatchError):
        OpenClawAdapter(openclaw_dir_bad).schema_check()


def test_list_sessions(openclaw_dir):
    sessions = list(OpenClawAdapter(openclaw_dir).list_sessions())
    assert len(sessions) == 2
    ids = sorted(s.id for s in sessions)
    assert ids == ['openclaw:session_a', 'openclaw:session_b']
    by_id = {s.id: s for s in sessions}
    a = by_id['openclaw:session_a']
    assert a.source == 'openclaw'
    assert a.turns == 3
    assert a.first_user_msg == 'openclaw question one'
    assert a.title == 'openclaw question one'
    b = by_id['openclaw:session_b']
    # malformed line skipped, blank skipped -> 3 valid
    assert b.turns == 3
    assert b.first_user_msg == 'b prompt'


def test_get_session_messages(openclaw_dir):
    msgs = OpenClawAdapter(openclaw_dir).get_session_messages('openclaw:session_a')
    assert len(msgs) == 3
    assert msgs[0]['role'] == 'user'
    assert msgs[0]['content'] == 'openclaw question one'
    # plain id also works
    msgs2 = OpenClawAdapter(openclaw_dir).get_session_messages('session_a')
    assert msgs2 == msgs


def test_filename_title_fallback(tmp_path):
    d = tmp_path / 'oc'
    d.mkdir()
    import json
    (d / 'noUser.jsonl').write_text(
        json.dumps({'role': 'assistant', 'content': 'just bot'}) + '\n')
    sessions = list(OpenClawAdapter(str(d)).list_sessions())
    assert len(sessions) == 1
    assert sessions[0].title == 'noUser'
