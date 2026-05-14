from app.models import UnifiedSession, truncate


def test_truncate_handles_none():
    assert truncate(None, 10) == ''
    assert truncate('', 10) == ''


def test_truncate_short_passthrough():
    assert truncate('hi', 10) == 'hi'


def test_truncate_long():
    assert truncate('a' * 100, 10) == 'a' * 10


def test_unified_session_to_dict_roundtrip():
    s = UnifiedSession(
        id='hermes:abc',
        source='hermes',
        title='t',
        created_at='2024-01-01T00:00:00+00:00',
        updated_at='2024-01-01T00:01:00+00:00',
        turns=2,
        model='gpt-4',
        cwd=None,
        first_user_msg='hi',
        body='hi\n\nhello',
    )
    d = s.to_dict()
    assert d['id'] == 'hermes:abc'
    assert d['source'] == 'hermes'
    assert d['cat'] == 'uncategorized'
    assert d['hidden'] is False
    assert d['group_id'] is None
    # all keys serializable
    import json
    json.dumps(d)


def test_unified_session_truncates_long_fields():
    s = UnifiedSession(
        id='x', source='hermes', title='t',
        created_at='', updated_at='', turns=0, model=None, cwd=None,
        first_user_msg='a' * 500,
        body='b' * 9000,
    )
    assert len(s.first_user_msg) == 240
    assert len(s.body) == 8000
