"""Capture parser warnings once at full-file indexing, not on every derived snippet."""

import ast
import warnings

PYTHON_DIAGNOSTICS_VERSION = 1
PARSER_WARNINGS = (SyntaxWarning, DeprecationWarning)


def parse_python(source, *, filename='<unknown>', diagnostics=None, quiet=False):
    captured = []
    try:
        with warnings.catch_warnings(record=True) as captured:
            for category in PARSER_WARNINGS:
                warnings.simplefilter('always', category)
            return ast.parse(source, filename=filename)
    finally:
        for warning in captured:
            if issubclass(warning.category, SyntaxWarning) or (
                issubclass(warning.category, DeprecationWarning)
                and 'escape sequence' in str(warning.message)
            ):
                if diagnostics is not None:
                    diagnostic = {
                        'type': 'python_syntax_warning',
                        'language': 'python',
                        'severity': 'warning',
                        'category': warning.category.__name__,
                        'line': warning.lineno,
                        'message': str(warning.message),
                    }
                    if diagnostic not in diagnostics:
                        diagnostics.append(diagnostic)
                elif not quiet:
                    warnings.warn_explicit(
                        warning.message, warning.category, warning.filename, warning.lineno
                    )
            else:
                # Only repeated parser warnings are quieted; other categories keep their filters.
                warnings.warn_explicit(
                    warning.message, warning.category, warning.filename, warning.lineno
                )
