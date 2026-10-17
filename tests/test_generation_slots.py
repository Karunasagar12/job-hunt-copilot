import threading
import time

import api.utils as utils


def test_at_most_two_generations_run_at_once(monkeypatch):
    running, peak, lock = [0], [0], threading.Lock()
    release = threading.Event()

    def fake_run_pipeline(job_id, **kwargs):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        release.wait(2)
        with lock:
            running[0] -= 1

    monkeypatch.setattr(utils, "run_pipeline", fake_run_pipeline)
    for i in range(3):
        utils.run_pipeline_async(i)
    time.sleep(0.3)
    assert running[0] == 2          # third is waiting for a slot
    release.set()
    time.sleep(0.3)
    assert peak[0] == 2 and running[0] == 0
