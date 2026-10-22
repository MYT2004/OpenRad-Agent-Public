"""Synthetic gamma allocation probe; emits JSON and never reads patient files.

Run from the checkout root: python -m validation.benchmarks.efficiency
Compare result dictionaries exactly across revisions. Timing is diagnostic, not
a performance gate; tracemalloc is not a measure of total process RSS.
"""
import json
import tempfile
import time
import tracemalloc

import numpy as np

from openrad.tools.gamma_tool import evaluate_gamma_index
from src.storage import StorageManager, session_scope


def main():
    rng = np.random.default_rng(263)
    reference = rng.uniform(0, 70, size=(40, 40, 40))
    prediction = np.maximum(0, reference + rng.normal(0, .7, reference.shape))
    runs = []
    with tempfile.TemporaryDirectory() as directory:
        with session_scope(StorageManager(directory)):
            for _ in range(3):
                tracemalloc.start()
                start = time.perf_counter()
                result = evaluate_gamma_index(reference, prediction, 3, 2, 10,
                                              [2, 2, 2], [2, 2, 2])
                elapsed = time.perf_counter() - start
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                runs.append(dict(seconds=elapsed, peak_traced_bytes=peak, result=result))
    print(json.dumps(dict(case='seed263_synthetic_40x40x40', runs=runs), indent=2))


if __name__ == '__main__':
    main()
