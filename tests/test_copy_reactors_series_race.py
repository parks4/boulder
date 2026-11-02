"""``_copy_reactors_series`` must survive a writer growing the series dict."""

import threading

from boulder.simulation_worker import _copy_reactors_series


def test_copy_while_another_thread_appends():
    """Copying the series while a thread adds reactors and species never raises.

    The converter fills the shared dict from its own thread, so the copy takes a
    snapshot instead of iterating the live dicts (no "dictionary changed size
    during iteration").
    """
    series = {"r0": {"T": [300.0], "X": {"N2": [1.0]}, "is_psr": False}}
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set() and i < 3000:
            i += 1
            series[f"r{i}"] = {"T": [300.0], "X": {"N2": [1.0]}}
            series["r0"]["X"][f"S{i}"] = [0.0]
            series["r0"][f"k{i}"] = [0.0]

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        for _ in range(300):
            _copy_reactors_series(series)
    finally:
        stop.set()
        thread.join()
