"""Validation for labeled retrieval datasets."""

from __future__ import annotations


def validate_labels(queries, chunk_ids, access_edges):
    """Validate IDs, access sets, and writer/reader edge evidence."""
    errors = []
    known = set(chunk_ids)
    for query in queries:
        writers = set(query.get('relevant_writers', []))
        readers = set(query.get('relevant_readers', []))
        accesses = set(query.get('relevant_accesses', []))
        if not writers | readers == accesses:
            errors.append(f'{query["term"]}: relevant_accesses must be the writer/reader union')
        for label, ids in (('writers', writers), ('readers', readers), ('accesses', accesses)):
            missing = ids - known
            if missing:
                errors.append(f'{query["term"]}: unknown {label} chunks: {sorted(missing)}')
        for chunk_id in writers:
            if (chunk_id, 'writes') not in access_edges:
                errors.append(f'{query["term"]}: {chunk_id} is not a writes edge')
        for chunk_id in readers:
            if (chunk_id, 'reads') not in access_edges:
                errors.append(f'{query["term"]}: {chunk_id} is not a reads edge')
    return errors
