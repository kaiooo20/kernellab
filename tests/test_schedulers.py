"""Testes dos escalonadores. Os valores esperados foram calculados à mão."""
import pytest

import schedulers as sch
from metrics import compute_metrics, count_context_switches
from models import Process


def waits(result):
    m = compute_metrics(result)
    return {p.pid: p.waiting for p in m.processes}


def test_fcfs_order_and_waits(processes):
    r = sch.fcfs(processes)
    assert r.execution_order == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert waits(r) == {"P1": 0, "P2": 7, "P3": 10, "P4": 18, "P5": 18, "P6": 29}
    m = compute_metrics(r)
    assert m.avg_waiting == pytest.approx(82 / 6)
    assert m.avg_turnaround == pytest.approx(20.5)
    assert m.context_switches == 5


def test_sjf_picks_shortest_ready_job(processes):
    r = sch.sjf(processes)
    assert r.execution_order == ["P1", "P4", "P2", "P6", "P3", "P5"]
    assert waits(r) == {"P1": 0, "P2": 9, "P3": 18, "P4": 5, "P5": 24, "P6": 8}
    assert compute_metrics(r).avg_waiting == pytest.approx(64 / 6)


def test_round_robin_quantum_3(processes):
    r = sch.round_robin(processes, 3)
    assert r.execution_order == ["P1", "P2", "P3", "P4", "P1", "P5", "P6",
                                 "P2", "P3", "P1", "P5", "P6", "P3", "P5"]
    m = compute_metrics(r)
    assert {p.pid: p.completion for p in m.processes} == {
        "P1": 26, "P2": 21, "P3": 35, "P4": 11, "P5": 41, "P6": 32}
    assert {p.pid: p.response for p in m.processes} == {
        "P1": 0, "P2": 2, "P3": 4, "P4": 6, "P5": 9, "P6": 11}
    assert m.avg_waiting == pytest.approx(18.0)
    assert m.context_switches == 13


def test_round_robin_quantum_is_configurable(processes):
    big = sch.round_robin(processes, 100)          # quantum enorme = FCFS
    assert big.execution_order == sch.fcfs(processes).execution_order
    assert count_context_switches(sch.round_robin(processes, 1)) > 13
    with pytest.raises(ValueError):
        sch.round_robin(processes, 0)


def test_priority_preemptive_alarm_runs_on_arrival(processes):
    r = sch.priority_preemptive(processes)
    assert r.execution_order == ["P1", "P4", "P1", "P2", "P6", "P3", "P5"]
    m = compute_metrics(r)
    alarm = m.by_pid("P4")
    assert (alarm.first_start, alarm.response, alarm.turnaround) == (3, 0, 2)
    assert m.avg_waiting == pytest.approx(61 / 6)
    assert m.context_switches == 6


def test_priority_non_preemptive_waits_for_running_job(processes):
    r = sch.priority_non_preemptive(processes)
    assert compute_metrics(r).by_pid("P4").response == 5


def test_aging_reduces_wait_of_lowest_priority(processes):
    plain = compute_metrics(sch.priority_preemptive(processes))
    aged = compute_metrics(sch.priority_preemptive(processes, aging_interval=4))
    assert aged.by_pid("P5").waiting < plain.by_pid("P5").waiting
    assert aged.by_pid("P4").response == 0     # aging nunca passa o alarme
    assert len(aged.starving) < len(plain.starving)


@pytest.mark.parametrize("algo", [
    sch.fcfs, sch.sjf, sch.priority_preemptive, sch.priority_non_preemptive,
    lambda ps: sch.round_robin(ps, 2),
])
def test_every_unit_of_burst_is_executed_once(processes, algo):
    r = algo(processes)
    total = sum(s.duration for s in r.segments if s.pid is not None)
    assert total == sum(p.burst for p in processes)
    # segmentos não se sobrepõem e são contíguos
    for a, b in zip(r.segments, r.segments[1:]):
        assert a.end == b.start


def test_idle_cpu_when_nobody_ready():
    ps = [Process("A", "a", 0, 2, 1), Process("B", "b", 5, 1, 1)]
    r = sch.fcfs(ps)
    assert [(s.pid, s.start, s.end) for s in r.segments] == [
        ("A", 0, 2), (None, 2, 5), ("B", 5, 6)]
    assert compute_metrics(r).idle_time == 3
    assert sch.round_robin(ps, 1).makespan == 6
    assert sch.priority_preemptive(ps).makespan == 6


def test_invalid_process_rejected():
    with pytest.raises(ValueError):
        Process("X", "x", 0, 0, 1)
