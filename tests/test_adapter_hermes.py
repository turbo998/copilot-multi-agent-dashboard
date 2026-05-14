import pytest

from app.adapters.hermes import HermesAdapter
from app.adapters.base import SchemaMismatchError


def test_schema_check_ok(hermes_db):
    HermesAdapter(hermes_db).schema_check()


def test_schema_check_fails(hermes_db_bad_schema):
    with pytest.raises(SchemaMismatchError):
        HermesAdapter(hermes_db_bad_schema).schema_check()


def test_list_sessions_count_and_order(hermes_db):
    sessions = list(HermesAdapter(hermes_db).list_sessions())
    # s_empty (message_count=0) excluded
    assert len(sessions) == 3
    ids = [s.id for s in sessions]
    # ordered by started_at DESC
    assert ids == ['hermes:s3', 'hermes:s2', 'hermes:s1']
    for s in sessions:
        assert s.source == 'hermes'
        assert s.id.startswith('hermes:')


def test_list_sessions_title_fallbacks(hermes_db):
    by_id = {s.id: s for s in HermesAdapter(hermes_db).list_sessions()}
    assert by_id['hermes:s1'].title == 'First Session'  # from db
    # s2 title is NULL -> use first user message preview
    assert by_id['hermes:s2'].title == 'second session question'
    # s3 title is empty -> first user msg preview
    assert by_id['hermes:s3'].title == 'third question only'


def test_list_sessions_first_user_and_body(hermes_db):
    by_id = {s.id: s for s in HermesAdapter(hermes_db).list_sessions()}
    assert by_id['hermes:s1'].first_user_msg == 'Hello hermes'
    assert 'Hello hermes' in by_id['hermes:s1'].body
    assert 'Hi there' in by_id['hermes:s1'].body
    assert by_id['hermes:s1'].turns == 2
    assert by_id['hermes:s1'].model == 'gpt-4'
    assert by_id['hermes:s1'].created_at.startswith('20')


def test_get_session_messages_order(hermes_db):
    msgs = HermesAdapter(hermes_db).get_session_messages('hermes:s2')
    assert [m['role'] for m in msgs] == ['user', 'assistant', 'assistant']
    assert msgs[0]['content'] == 'second session question'
    # accepts plain id too
    msgs2 = HermesAdapter(hermes_db).get_session_messages('s2')
    assert msgs2 == msgs
