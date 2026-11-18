"""Twitter requests made per UTC day, in a small JSON file shared between projects.

Two processes (this monitor and the bot tracker) may collect at the same moment, so every
take() holds an exclusive lock file, reads the count fresh, and writes it back atomically.
A missing file means nothing has been used yet; a file that exists but cannot be read or
parsed counts as the cap reached, never as zero used.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

LOCK_WAIT = 10.0   # seconds to wait for the lock
LOCK_RETRY = 0.1   # seconds between attempts
LOCK_STALE = 30.0  # a lock older than this is left over from a crashed process


class BudgetExhausted(Exception):
    """The UTC day's request cap is reached (or the usage file cannot be trusted)."""


class Budget:
    def __init__(self, path: Path, cap: int):
        self.path, self.cap = Path(path), cap
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def _acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                os.close(os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return
            except FileExistsError:
                pass
            try:
                if time.time() - self.lock_path.stat().st_mtime > LOCK_STALE:
                    self.lock_path.unlink()
                    continue
            except OSError:
                continue  # the lock vanished between the attempt and the check
            if time.monotonic() >= deadline:
                raise BudgetExhausted("could not lock the Twitter usage file")
            time.sleep(LOCK_RETRY)

    def _release(self) -> None:
        try:
            self.lock_path.unlink()
        except OSError:
            pass

    def _read(self) -> dict:
        """Counts by day. Missing file: nothing used. Unreadable file: raises BudgetExhausted."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as e:
            raise BudgetExhausted(f"Twitter usage file unreadable: {e}") from e
        try:
            state = json.loads(raw)
        except ValueError as e:
            raise BudgetExhausted("Twitter usage file is not valid JSON") from e
        if not isinstance(state, dict):
            raise BudgetExhausted("Twitter usage file is not a JSON object")
        return state

    def take(self) -> None:
        self._acquire()
        try:
            day = time.strftime("%Y-%m-%d", time.gmtime())
            used = self._read().get(day, 0)
            if not isinstance(used, int) or isinstance(used, bool):
                raise BudgetExhausted("Twitter usage file holds a bad count")
            if used >= self.cap:
                raise BudgetExhausted(f"daily Twitter request cap reached ({self.cap})")
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps({day: used + 1}), encoding="utf-8")
            os.replace(tmp, self.path)
        finally:
            self._release()
