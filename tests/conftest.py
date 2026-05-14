"""Shared pytest fixtures - synthetic sqlite/jsonl data."""
from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest


@pytest.fixture
def hermes_db(tmp_path):
    """Create synthetic Hermes state.db with 3 sessions, several messages."""
    path = tmp_path / 'hermes_state.db'
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    # Mimic a subset (plus a few extra cols) of real schema.
    cur.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            user_id TEXT,
            model TEXT,
            model_config TEXT,
            system_prompt TEXT,
            parent_session_id TEXT,
            started_at REAL,
            ended_at REAL,
            end_reason TEXT,
            message_count INTEGER,
            tool_call_count INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            title TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            timestamp REAL
        )
    """)
    base = 1700000000.0
    sessions = [
        ('s1', 'cli', 'u', 'gpt-4', None, None, None, base, base + 60, 'done', 2, 0, 10, 20, 'First Session'),
        ('s2', 'cli', 'u', 'gpt-4', None, None, None, base + 100, base + 200, 'done', 3, 0, 10, 20, None),
        ('s3', 'cli', 'u', 'gpt-4', None, None, None, base + 300, None, None, 1, 0, 5, 5, ''),
        ('s_empty', 'cli', 'u', 'gpt-4', None, None, None, base + 400, None, None, 0, 0, 0, 0, 'Empty'),
    ]
    cur.executemany(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", sessions)
    msgs = [
        ('s1', 'user', 'Hello hermes', None, None, None, base + 1),
        ('s1', 'assistant', 'Hi there', None, None, None, base + 2),
        ('s2', 'user', 'second session question', None, None, None, base + 101),
        ('s2', 'assistant', 'reply A', None, None, None, base + 102),
        ('s2', 'assistant', 'reply B', None, None, None, base + 103),
        ('s3', 'user', 'third question only', None, None, None, base + 301),
    ]
    cur.executemany(
        "INSERT INTO messages (session_id,role,content,tool_call_id,tool_calls,tool_name,timestamp) "
        "VALUES (?,?,?,?,?,?,?)", msgs)
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def hermes_db_bad_schema(tmp_path):
    """Hermes db missing required columns."""
    path = tmp_path / 'hermes_bad.db'
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
    cur.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def ghcp_db(tmp_path):
    path = tmp_path / 'session-store.db'
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at INTEGER,
            updated_at INTEGER,
            cwd TEXT,
            summary TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            created_at INTEGER
        )
    """)
    base = 1700000000
    cur.executemany(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
        [
            ('g1', 'GHCP One', base, base + 50, '/tmp/proj1', 'sum1'),
            ('g2', None, base + 100, base + 200, '/tmp/proj2', None),
        ],
    )
    cur.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [
            ('m1', 'g1', 'user', 'ghcp hello', base + 1),
            ('m2', 'g1', 'assistant', 'ghcp reply', base + 2),
            ('m3', 'g2', 'user', 'ghcp two prompt', base + 101),
            ('m4', 'g2', 'assistant', 'ghcp two reply', base + 102),
        ],
    )
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def ghcp_db_bad_schema(tmp_path):
    path = tmp_path / 'session-store-bad.db'
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
    cur.execute("CREATE TABLE messages (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def openclaw_dir(tmp_path):
    d = tmp_path / 'openclaw'
    d.mkdir()
    s1 = d / 'session_a.jsonl'
    s1.write_text('\n'.join([
        json.dumps({'role': 'user', 'content': 'openclaw question one', 'timestamp': '2024-01-01T00:00:00Z'}),
        json.dumps({'role': 'assistant', 'content': 'answer one', 'timestamp': '2024-01-01T00:00:05Z'}),
        json.dumps({'role': 'user', 'content': 'follow up', 'timestamp': '2024-01-01T00:00:10Z'}),
    ]) + '\n')
    s2 = d / 'session_b.jsonl'
    s2.write_text('\n'.join([
        json.dumps({'role': 'system', 'content': 'sys', 'timestamp': 1700000000}),
        json.dumps({'role': 'user', 'content': 'b prompt', 'timestamp': 1700000005}),
        json.dumps({'role': 'assistant', 'content': 'b reply', 'timestamp': 1700000010}),
        '',  # blank line
        '{not valid json',  # malformed - should be skipped
    ]) + '\n')
    return str(d)


@pytest.fixture
def openclaw_dir_bad(tmp_path):
    d = tmp_path / 'openclaw_bad'
    d.mkdir()
    f = d / 'broken.jsonl'
    f.write_text('{"no_role": "x"}\n')
    return str(d)
