"""The new project entry point preserves routing and the established CLI interface."""

import json
import subprocess
import sys

import pytest


@pytest.mark.parametrize('command', [[], ['chat'], ['query']])
def test_new_module_exposes_cli_help(command):
    result = subprocess.run(
        [sys.executable, '-m', 'codetrace', *command, '--help'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert 'code-trace' in result.stdout


def test_new_and_legacy_modules_resolve_the_same_configured_repository(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'repositories': {'demo': {'path': str(tmp_path)}}}))
    outputs = []
    for module in ('codetrace', 'coderag'):
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                module,
                'answer',
                'Dónde se usa order_id',
                '--config',
                str(config),
                '--repo',
                'demo',
                '--resolve-only',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(json.loads(result.stdout))
    assert outputs[0] == outputs[1]
    assert outputs[0]['repository'] == 'demo'
