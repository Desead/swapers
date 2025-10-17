# app_market/collectors/metrics.py
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict

log = logging.getLogger(__name__)


@dataclass
class Counter:
    fetched: int = 0
    normalized: int = 0
    pushed: int = 0
    skipped: int = 0
    errors: int = 0
    dump_written: int = 0
    timings_ms: Dict[str, int] = field(default_factory=dict)

    def log_json(self, provider: str, task: str, **extra):
        payload = {
            "provider": provider,
            "task": task,
            "fetched": self.fetched,
            "normalized": self.normalized,
            "pushed": self.pushed,
            "skipped": self.skipped,
            "errors": self.errors,
            "dump_written": self.dump_written,
            "timings_ms": self.timings_ms,
            **extra,
        }
        log.info(json.dumps(payload, ensure_ascii=False))


class Timer:
    def __init__(self, counter: Counter, key: str):
        self.counter = counter
        self.key = key
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        dt = int((time.perf_counter() - self._t0) * 1000)
        self.counter.timings_ms[self.key] = dt
