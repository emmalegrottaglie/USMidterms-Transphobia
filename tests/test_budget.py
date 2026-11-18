import json
import multiprocessing
import os
import time

import pytest

from monitor import budget as budget_module
from monitor.budget import Budget, BudgetExhausted


def test_take_counts_per_utc_day_and_stops_at_cap(tmp_path):
    path = tmp_path / "usage.json"
    Budget(path, cap=2).take()
    Budget(path, cap=2).take()  # the count survives a restart
    with pytest.raises(BudgetExhausted, match="cap"):
        Budget(path, cap=2).take()
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert json.loads(path.read_text(encoding="utf-8")) == {day: 2}
    assert not (tmp_path / "usage.json.lock").exists()  # the lock is released after a refusal too


def _worker(path, cap, calls, barrier, queue):
    budget = Budget(path, cap)
    barrier.wait(timeout=60)  # both workers start together, so the takes really overlap
    ok = 0
    try:
        for _ in range(calls):
            try:
                budget.take()
                ok += 1
            except BudgetExhausted:
                pass
    except Exception as exc:  # report a crash to the test instead of leaving it waiting
        queue.put(repr(exc))
        return
    queue.put(ok)


def test_two_processes_never_exceed_cap(tmp_path):
    path = tmp_path / "usage.json"
    ctx = multiprocessing.get_context("spawn")
    queue, barrier = ctx.Queue(), ctx.Barrier(2)
    procs = [ctx.Process(target=_worker, args=(path, 300, 200, barrier, queue)) for _ in range(2)]
    try:
        for p in procs:
            p.start()
        results = [queue.get(timeout=30) for _ in procs]
    finally:
        for p in procs:
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()
    assert all(isinstance(r, int) for r in results), results  # a worker crashed
    assert sum(results) == 300
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert json.loads(path.read_text(encoding="utf-8")) == {day: 300}


def test_held_lock_blocks_take_and_is_left_alone(tmp_path, monkeypatch):
    path = tmp_path / "usage.json"
    day = time.strftime("%Y-%m-%d", time.gmtime())
    path.write_text(json.dumps({day: 1}), encoding="utf-8")
    lock = tmp_path / "usage.json.lock"
    lock.write_bytes(b"")  # fresh mtime: another process holds it
    monkeypatch.setattr(budget_module, "LOCK_WAIT", 0.3)
    with pytest.raises(BudgetExhausted, match="lock"):
        Budget(path, cap=100).take()
    assert json.loads(path.read_text(encoding="utf-8")) == {day: 1}
    assert lock.exists()


def test_stale_lock_is_removed(tmp_path):
    path = tmp_path / "usage.json"
    lock = tmp_path / "usage.json.lock"
    lock.write_bytes(b"")
    old = time.time() - budget_module.LOCK_STALE - 5
    os.utime(lock, (old, old))
    Budget(path, cap=100).take()
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert json.loads(path.read_text(encoding="utf-8")) == {day: 1}
    assert not lock.exists()


def test_unreadable_file_counts_as_cap_reached(tmp_path):
    path = tmp_path / "usage.json"
    path.write_bytes(b"not json")
    with pytest.raises(BudgetExhausted):
        Budget(path, cap=100).take()
    assert path.read_bytes() == b"not json"
    assert not (tmp_path / "usage.json.lock").exists()


def test_lock_refused_by_the_folder_gives_up_at_the_deadline(tmp_path, monkeypatch):
    real_open = os.open

    def refuse_lock(path, *args, **kwargs):
        if str(path).endswith(".lock"):
            raise PermissionError("read-only folder")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", refuse_lock)
    monkeypatch.setattr(budget_module, "LOCK_WAIT", 0.3)
    started = time.monotonic()
    with pytest.raises(BudgetExhausted, match="lock"):
        Budget(tmp_path / "usage.json", cap=100).take()
    assert time.monotonic() - started < 5  # waits for the deadline, never spins forever
