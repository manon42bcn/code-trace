"""Repository routing remains deterministic, local, and explicit about ambiguity."""

import pytest

from coderag.repository_routing import RepositoryRoutingError, select_repository


@pytest.fixture
def catalog():
    return {
        'home': {'description': 'Frontend de escritorio'},
        'aicc-tests': {
            'aliases': ['tests de AICC', 'ensayos Ágiles'],
            'description': 'Pruebas de aceptación y validación de integraciones API',
        },
        'toolium': {'description': 'Framework compartido de automatización'},
        'toolium-examples': {'description': 'Ejemplos del framework'},
    }


@pytest.mark.parametrize(
    ('query', 'expected'),
    [
        ('En AICC tests, order_id', 'aicc-tests'),
        ('en tests de AICC order_id', 'aicc-tests'),
        ('Sobre ENSAYOS AGILES: order_id', 'aicc-tests'),
        ('¿En toolium-examples, order_id?', 'toolium-examples'),
        ('¿Dónde se usa toolium?', 'toolium'),
        ('Where is the API called?', 'home'),
        ('aicc_testsmith', 'home'),
    ],
)
def test_names_aliases_boundaries_and_default(catalog, query, expected):
    assert select_repository(query, catalog, 'home')['repository'] == expected


def test_leading_selector_is_removed_but_question_is_preserved(catalog):
    routed = select_repository('En los tests de AICC, ¿Dónde se escribe order_id?', catalog, 'home')
    assert routed['query'] == '¿Dónde se escribe order_id?'
    assert routed['reason'] == 'alias'


def test_description_requires_a_scoped_multiword_reference(catalog):
    routed = select_repository('En las pruebas de aceptación, order_id', catalog, 'home')
    assert routed['repository'] == 'aicc-tests'
    assert routed['reason'] == 'description'
    assert routed['query'] == 'order_id'
    assert select_repository('Hay pruebas de aceptación', catalog, 'home')['repository'] == 'home'
    assert select_repository('En API, order_id', catalog, 'home')['repository'] == 'home'


def test_explicit_names_precede_descriptions(catalog):
    routed = select_repository('En toolium, pruebas de aceptación', catalog, 'home')
    assert routed['repository'] == 'toolium'


@pytest.mark.parametrize(
    'query', ['En toolium y aicc-tests, order_id', 'Compare toolium with toolium-examples']
)
def test_multiple_explicit_repositories_require_clarification(catalog, query):
    with pytest.raises(RepositoryRoutingError, match='Several repositories') as exc:
        select_repository(query, catalog, 'home')
    assert exc.value.code == 'ambiguous_repository'
    assert len(exc.value.candidates) == 2


def test_alias_collision_is_not_resolved_by_default(catalog):
    catalog['home']['aliases'] = ['tests de AICC']
    with pytest.raises(RepositoryRoutingError, match='Several repositories') as exc:
        select_repository('En tests de AICC, order_id', catalog, 'home')
    assert exc.value.candidates == ['aicc-tests', 'home']


def test_description_tie_requires_clarification(catalog):
    catalog['home']['description'] = catalog['aicc-tests']['description']
    with pytest.raises(RepositoryRoutingError, match='Description matches several'):
        select_repository('En las pruebas de aceptación, order_id', catalog, 'home')


def test_explicit_unknown_repository_does_not_query_default(catalog):
    with pytest.raises(RepositoryRoutingError, match='not configured') as exc:
        select_repository('En el repositorio desconocido, order_id', catalog, 'home')
    assert exc.value.code == 'unknown_repository'


@pytest.mark.parametrize('aliases', ['not a list', [42], ['']])
def test_invalid_alias_metadata_is_rejected(catalog, aliases):
    catalog['home']['aliases'] = aliases
    with pytest.raises(ValueError, match='aliases must be'):
        select_repository('order_id', catalog, 'home')


@pytest.mark.parametrize('suffix', ['--repo fabrica', '--repo=fabrica'])
def test_embedded_selector_and_trailing_scope_do_not_enter_retrieval(catalog, suffix):
    catalog['fabrica'] = {'aliases': ['fábrica']}
    routed = select_repository(
        f'en que tools se incluye en handoff en fábrica {suffix}', catalog, 'home'
    )
    assert routed == {
        'repository': 'fabrica',
        'reason': 'explicit',
        'matched': 'fabrica',
        'query': 'en que tools se incluye en handoff',
    }


@pytest.mark.parametrize(
    'question',
    [
        '¿Qué tools en fábrica incluyen handoff?',
        '¿Qué tools incluyen handoff en el repositorio fábrica?',
        '¿Qué tools incluyen handoff en fábrica?',
    ],
)
def test_repository_scopes_can_be_removed_from_middle_or_end(catalog, question):
    catalog['fabrica'] = {'aliases': ['fábrica']}
    routed = select_repository(question, catalog, 'home')
    assert 'fábrica' not in routed['query']
    assert 'handoff' in routed['query']
    assert 'tools' in routed['query']


def test_repo_names_used_as_subjects_and_quoted_flags_remain_literal(catalog):
    assert (
        select_repository('¿Dónde se usa toolium?', catalog, 'home')['query']
        == '¿Dónde se usa toolium?'
    )
    query = '¿Qué significa `--repo home`?'
    assert select_repository(query, catalog, 'home')['query'] == query
    query = '¿Qué significa "en toolium"?'
    assert select_repository(query, catalog, 'home')['query'] == query


@pytest.mark.parametrize(
    ('question', 'repo', 'code'),
    [
        ('handoff --repo missing', None, 'unknown_repository'),
        ('handoff --repo home', 'toolium', 'conflicting_repository'),
        ('En toolium, handoff', 'home', 'conflicting_repository'),
        ('handoff --repo home --repo toolium', None, 'conflicting_repository'),
    ],
)
def test_repository_directives_fail_explicitly_on_unknown_or_conflicting_targets(
    catalog, question, repo, code
):
    with pytest.raises(RepositoryRoutingError) as exc:
        select_repository(question, catalog, 'home', repo=repo)
    assert exc.value.code == code


@pytest.mark.parametrize('question', ['--repo home', 'handoff --repo', 'handoff --repo='])
def test_malformed_or_empty_directives_do_not_become_search_terms(catalog, question):
    with pytest.raises(ValueError, match=r'requires|requires a|nonempty'):
        select_repository(question, catalog, 'home')


def test_domain_alias_is_not_erased_from_the_actual_question(catalog):
    catalog['fabrica'] = {'aliases': ['Pix']}
    question = '¿Qué tools incluyen handoff en Pix?'
    assert select_repository(question, catalog, 'home')['query'] == question
    scoped = select_repository(
        '¿Qué tools incluyen handoff en el repositorio Pix?', catalog, 'home'
    )
    assert 'Pix' not in scoped['query']
    assert scoped['repository'] == 'fabrica'
