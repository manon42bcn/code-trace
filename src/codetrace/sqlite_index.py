"""Disk-backed lexical candidates and evidence chunks for a prepared snapshot."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import closing, contextmanager

from .query_planning import variants, words

FIELDS = ('symbol', 'path', 'content')
SCHEMA_VERSION = 1
SNAPSHOT_METADATA = (
    'created_at',
    'source_root',
    'git',
    'source_manifest',
    'source_stats',
    'indexing_settings',
    'skipped_files',
    'diagnostics',
)


def sqlite_index_path(index_path):
    output = index_path.with_suffix('.sqlite3')
    if output == index_path:
        raise ValueError('Expected the path of the JSON chunks index')
    return output


def _chunk_rows(chunks):
    for chunk in chunks:
        text = [chunk.get(field) for field in FIELDS]
        metadata = {
            key: value for key, value in chunk.items() if key not in FIELDS or value is None
        }
        yield (
            chunk['id'],
            *text,
            json.dumps(metadata, ensure_ascii=False),
            any(value is not None and '\0' in value for value in text),
        )


def _natural_rows(chunks):
    for position, chunk in enumerate(chunks, start=1):
        tokens = {
            variant
            for field in FIELDS
            for word in words(chunk.get(field) or '')
            for variant in variants(word)
        }
        yield position, ' '.join(sorted(tokens))


def prepare_sqlite_index(index_path, *, index=None):
    """Build from the JSON snapshot and publish the completed database atomically."""
    index_path = index_path.resolve()
    output = sqlite_index_path(index_path)
    if index is None:
        index = json.loads(index_path.read_text(encoding='utf-8'))
    chunks = index['chunks']
    metadata = {key: index[key] for key in SNAPSHOT_METADATA if key in index}
    fd, name = tempfile.mkstemp(prefix=f'.{output.name}.', dir=output.parent)
    os.close(fd)
    try:
        with closing(sqlite3.connect(name)) as db, db:
            db.executescript("""
                CREATE TABLE snapshot (metadata TEXT NOT NULL, chunk_count INTEGER NOT NULL);
                CREATE TABLE chunks (
                    chunk_id TEXT NOT NULL UNIQUE, symbol TEXT, path TEXT, content TEXT,
                    metadata TEXT NOT NULL, has_nul INTEGER NOT NULL
                );
                CREATE INDEX chunks_with_nul ON chunks(has_nul) WHERE has_nul = 1;
                CREATE VIRTUAL TABLE literal USING fts5(
                    symbol, path, content, content='chunks', tokenize='trigram case_sensitive 1'
                );
                CREATE VIRTUAL TABLE natural USING fts5(tokens, content='');
            """)
            db.execute(
                'INSERT INTO snapshot VALUES (?, ?)',
                (json.dumps(metadata, ensure_ascii=False), len(chunks)),
            )
            db.executemany('INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)', _chunk_rows(chunks))
            db.execute("INSERT INTO literal(literal) VALUES ('rebuild')")
            db.executemany(
                'INSERT INTO natural(rowid, tokens) VALUES (?, ?)', _natural_rows(chunks)
            )
            db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        os.replace(name, output)
    except sqlite3.Error as exc:
        raise ValueError(
            f'Could not build {output.name}. Check SQLite FTS5 and trigram support or index data.'
        ) from exc
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return output


def _literal_query(term):
    if len(term) >= 3 and '\0' not in term:
        return (
            'SELECT rowid FROM literal WHERE literal MATCH ? '
            'UNION SELECT rowid FROM chunks WHERE has_nul = 1',
            (_quoted(term),),
        )
    sql = ' OR '.join(f"instr(coalesce({field}, ''), ?) > 0" for field in FIELDS)
    return f'SELECT rowid FROM chunks WHERE {sql}', (term,) * len(FIELDS)


def _quoted(term):
    return '"' + term.replace('"', '""') + '"'


def _decode(row):
    chunk = json.loads(row[3])
    chunk.update(
        {field: value for field, value in zip(FIELDS, row[:3], strict=True) if value is not None}
    )
    return chunk


class SQLiteChunks:
    """Read only candidates and chunks requested by the retrieval pipeline."""

    backend = 'sqlite'

    def __init__(self, db, count):
        self.db = db
        self.count = count

    def __len__(self):
        return self.count

    def __iter__(self):
        rows = self.db.execute('SELECT symbol, path, content, metadata FROM chunks ORDER BY rowid')
        return map(_decode, rows)

    def get(self, chunk_id, default=None):
        row = self.db.execute(
            'SELECT symbol, path, content, metadata FROM chunks WHERE chunk_id = ?',
            (chunk_id,),
        ).fetchone()
        return _decode(row) if row is not None else default

    def lexical_candidates(self, term, plan):
        if plan and plan['lexical_mode'] == 'token_overlap':
            forms = sorted({form for forms in plan['lexical_variants'].values() for form in forms})
            if any(not form.isascii() for form in forms):
                return iter(self)
            sources = (
                [
                    (
                        'SELECT rowid FROM natural WHERE natural MATCH ?',
                        (' OR '.join(map(_quoted, forms)),),
                    )
                ]
                if forms
                else []
            )
            sources.extend(_literal_query(anchor) for anchor in plan['identifier_anchors'])
        else:
            sources = [_literal_query(term)]
        if not sources:
            return iter(())
        union = ' UNION '.join(query for query, _ in sources)
        rows = self.db.execute(
            f'SELECT symbol, path, content, metadata FROM chunks WHERE rowid IN ({union})',
            tuple(value for _, values in sources for value in values),
        )
        return map(_decode, rows)


@contextmanager
def open_sqlite_index(index_path):
    """Open the prepared snapshot read-only for one request."""
    path = sqlite_index_path(index_path.resolve())
    if not path.is_file():
        raise ValueError(f'SQLite index not found: {path}. Run code-trace prepare-sqlite INDEX.')
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise ValueError(f'Unsupported SQLite index format: {path}. Rebuild it.')
            metadata, count = db.execute('SELECT metadata, chunk_count FROM snapshot').fetchone()
            yield {**json.loads(metadata), 'chunks': SQLiteChunks(db, count)}
    except sqlite3.Error as exc:
        raise ValueError(f'Could not read SQLite index: {path}. Rebuild it.') from exc


def index_backend(index):
    return getattr(index.get('chunks'), 'backend', 'json')


@contextmanager
def open_prepared_index(index_path):
    """Prefer the prepared SQLite snapshot; read legacy JSON indexes until rebuilt."""
    if sqlite_index_path(index_path.resolve()).is_file():
        with open_sqlite_index(index_path) as index:
            yield index
    else:
        yield json.loads(index_path.read_text(encoding='utf-8'))
