"""Bounded local conversation memory shared by CodeTrace entry points."""

import json
import os
import re
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

SESSION_ID = re.compile(r'[0-9a-f]{32}')
SESSION_HELP = 'Resume a local conversation by ID, or use new to start one'
MAX_TURNS = 3
_REFERENCE = re.compile(
    r'^\s*[¿?]?\s*(?:y|and)\s+|'
    r'\b(?:ese|esa|esos|esas|esto|eso|aqu[eé]l|aquella|primer[oa]?|segund[oa]|'
    r'tercer[oa]?|[uú]ltim[oa]|that|those|it|them|first|second|third|last)\b',
    re.IGNORECASE,
)


def valid_session(value):
    return isinstance(value, str) and (value == 'new' or SESSION_ID.fullmatch(value) is not None)


@contextmanager
def database(path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY)')
            db.execute(
                'CREATE TABLE IF NOT EXISTS turns ('
                'id INTEGER PRIMARY KEY, session TEXT, scope TEXT, question TEXT, answer TEXT)'
            )
            db.execute('CREATE INDEX IF NOT EXISTS turns_scope ON turns (session, scope, id)')
            yield db
    except (OSError, sqlite3.Error) as exc:
        raise ValueError('Could not access local conversation memory') from exc


class Conversation:
    def __init__(self, path, identifier, scope):
        self.path = path
        self.identifier = identifier
        self.scope = scope

    @classmethod
    def open(cls, value, config, index=None, relationships=None):
        if not valid_session(value):
            raise ValueError('Use --session new or a 32-character hexadecimal session ID')
        base = config.resolve().parent if config else Path.cwd()
        path = base / 'indexes/.conversations/conversations.sqlite3'
        scope = (
            json.dumps([str(index.resolve()), str(relationships.resolve())])
            if index is not None
            else None
        )
        identifier = uuid4().hex if value == 'new' else value
        with database(path) as db:
            if value == 'new':
                db.execute('INSERT INTO sessions VALUES (?)', (identifier,))
            elif (
                db.execute('SELECT 1 FROM sessions WHERE id = ?', (identifier,)).fetchone() is None
            ):
                raise ValueError('Conversation session not found. Start a new conversation.')
        return cls(path, identifier, scope)

    def history(self):
        with database(self.path) as db:
            rows = db.execute(
                'SELECT question, answer FROM turns WHERE session = ? AND scope = ? '
                'ORDER BY id DESC LIMIT ?',
                (self.identifier, self.scope, MAX_TURNS),
            ).fetchall()
        return [{'question': question, 'answer': answer} for question, answer in reversed(rows)]

    def remember(self, question, answer):
        with database(self.path) as db:
            db.execute('PRAGMA secure_delete = ON')
            db.execute(
                'INSERT INTO turns (session, scope, question, answer) VALUES (?, ?, ?, ?)',
                (self.identifier, self.scope, question[:1200], answer[:2400]),
            )
            db.execute(
                'DELETE FROM turns WHERE session = ? AND scope = ? AND id NOT IN ('
                'SELECT id FROM turns WHERE session = ? AND scope = ? ORDER BY id DESC LIMIT ?)',
                (self.identifier, self.scope, self.identifier, self.scope, MAX_TURNS),
            )


def retrieval_question(question, history):
    if not history or not _REFERENCE.search(question):
        return question
    previous = history[-1]
    identifiers = ' '.join(re.findall(r'`([\w./:-]{2,100})`', previous['answer'])[:8])
    return ' '.join(filter(None, (question, previous['question'], identifiers)))
