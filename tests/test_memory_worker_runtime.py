from src.memory.worker_runtime import should_autostart_memory_worker, start_memory_worker_runtime


def test_memory_worker_stays_off_under_pytest():
    assert should_autostart_memory_worker() is False
    assert start_memory_worker_runtime() is False
