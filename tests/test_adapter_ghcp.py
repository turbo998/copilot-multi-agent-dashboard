import pytest

from app.adapters.ghcp import GHCPAdapter
from app.adapters.base import SchemaMismatchError


def test_schema_check_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        GHCPAdapter(str(tmp_path / 'nope.db')).schema_check()


def test_schema_check_ok(ghcp_db):
    GHCPAdapter(ghcp_db).schema_check()


def test_schema_check_bad(ghcp_db_bad_schema):
    with pytest.raises(SchemaMismatchError):
        GHCPAdapter(ghcp_db_bad_schema).schema_check()


def test_list_sessions(ghcp_db):
    sessions = list(GHCPAdapter(ghcp_db).list_sessions())
    assert len(sessions) == 2
    # ordered by updated_at DESC
    assert [s.id for s in sessions] == ['ghcp:g2', 'ghcp:g1']
    by_id = {s.id: s for s in sessions}
    assert by_id['ghcp:g1'].title == 'GHCP One'
    assert by_id['ghcp:g1'].cwd == '/tmp/proj1'
    assert by_id['ghcp:g1'].turns == 2
    assert by_id['ghcp:g1'].first_user_msg == 'ghcp hello'
    # title fallback for null
    assert by_id['ghcp:g2'].title == 'ghcp two prompt'
    assert by_id['ghcp:g1'].source == 'ghcp'
    assert by_id['ghcp:g1'].created_at.startswith('20')


def test_get_session_messages(ghcp_db):
    msgs = GHCPAdapter(ghcp_db).get_session_messages('ghcp:g1')
    assert [m['role'] for m in msgs] == ['user', 'assistant']
    assert msgs[0]['content'] == 'ghcp hello'
    msgs2 = GHCPAdapter(ghcp_db).get_session_messages('g1')
    assert msgs2 == msgs
