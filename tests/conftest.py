import pytest

from codetrace import request_metrics


@pytest.fixture(autouse=True)
def isolate_request_metrics(tmp_path, monkeypatch):
    """Keep synthetic provider traffic out of the local request history."""
    monkeypatch.setattr(request_metrics, 'HISTORY_PATH', tmp_path / request_metrics.HISTORY_PATH)
