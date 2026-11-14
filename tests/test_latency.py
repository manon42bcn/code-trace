import time

from coderag.latency import timed


def test_timed_records_elapsed_seconds():
    metrics = {}
    with timed(metrics, 'work'):
        time.sleep(0.001)
    assert metrics['work'] >= 0
