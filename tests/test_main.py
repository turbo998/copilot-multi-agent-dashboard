"""Integration tests for the FastAPI app, wired to real adapters with synthetic data."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.ghcp import GHCPAdapter
from app.adapters.hermes import HermesAdapter
from app.adapters.openclaw import OpenClawAdapter
from app.main import create_app


@pytest.fixture
def client(hermes_db, ghcp_db, openclaw_dir):
    adapters = [
        HermesAdapter(hermes_db),
        GHCPAdapter(ghcp_db),
        OpenClawAdapter(openclaw_dir),
    ]
    app = create_app(adapters=adapters)
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    r = client.get('/healthz')
    assert r.status_code == 200
    assert r.json() == {'status': 'ok'}


def test_index_html(client):
    r = client.get('/')
    assert r.status_code == 200
    assert 'Agent Dashboard' in r.text
    # session titles from each adapter render
    assert 'First Session' in r.text or 'hermes' in r.text


def test_api_sessions_all(client):
    r = client.get('/api/sessions')
    assert r.status_code == 200
    data = r.json()
    sources = {s['source'] for s in data}
    assert {'hermes', 'ghcp', 'openclaw'} <= sources
    # 3 hermes (s_empty excluded) + 2 ghcp + 2 openclaw = 7
    assert len(data) == 7


def test_api_sessions_filter_hermes(client):
    r = client.get('/api/sessions?source=hermes')
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    for s in data:
        assert s['id'].startswith('hermes:')
        assert s['source'] == 'hermes'


def test_api_sessions_filter_ghcp(client):
    r = client.get('/api/sessions?source=ghcp')
    data = r.json()
    assert all(s['source'] == 'ghcp' for s in data)
    assert len(data) == 2


def test_api_sessions_search_query(client):
    r = client.get('/api/sessions?q=openclaw')
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    # all matches should mention 'openclaw' in title/preview/body
    for s in data:
        haystack = ' '.join([s.get('title') or '', s.get('first_user_msg') or '', s.get('body') or '']).lower()
        assert 'openclaw' in haystack


def test_api_sessions_search_no_match(client):
    r = client.get('/api/sessions?q=zzz_nonexistent_token_xyz')
    assert r.json() == []


def test_session_detail_valid(client):
    r = client.get('/session/hermes:s1')
    assert r.status_code == 200
    assert 'Hello hermes' in r.text
    assert 'Hi there' in r.text


def test_session_detail_ghcp(client):
    r = client.get('/session/ghcp:g1')
    assert r.status_code == 200
    assert 'ghcp hello' in r.text


def test_session_detail_invalid_id(client):
    r = client.get('/session/hermes:does_not_exist')
    assert r.status_code == 404


def test_session_detail_unknown_source(client):
    r = client.get('/session/wat:abc')
    assert r.status_code == 404


def test_api_messages(client):
    r = client.get('/api/sessions/hermes:s2/messages')
    assert r.status_code == 200
    data = r.json()
    assert [m['role'] for m in data] == ['user', 'assistant', 'assistant']


def test_api_messages_unknown_source(client):
    r = client.get('/api/sessions/nope:xyz/messages')
    assert r.status_code == 404
