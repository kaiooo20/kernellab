import pytest

import schedulers as sch
from metrics import compare, compute_metrics, jain_index


def all_metrics(processes):
    return [compute_metrics(r) for r in sch.run_all(processes, 3, aging_interval=4)]


def test_jain_index_bounds():
    assert jain_index([1, 1, 1]) == pytest.approx(1.0)
    assert jain_index([1, 0, 0, 0]) == pytest.approx(0.25)


def test_response_never_greater_than_waiting(processes):
    for m in all_metrics(processes):
        for p in m.processes:
            assert 0 <= p.response <= p.waiting
            assert p.turnaround == p.waiting + p.burst


def test_starvation_flags(processes):
    by = {m.short_name: m for m in all_metrics(processes)}
    assert by["FCFS"].starving == []
    assert by["RR q=3"].starving == []
    assert set(by["SJF"].starving) == {"P3", "P5"}
    assert set(by["Prioridade"].starving) == {"P3", "P5"}
    assert "P4" in by["FCFS"].delayed      # alarme preso atrás de processos longos


def test_comparison_answers(processes):
    comp = compare(all_metrics(processes), critical_pid="P4")
    assert comp.lowest_avg_waiting == ["Prioridade"]
    assert comp.best_avg_response == ["RR q=3"]
    assert "Prioridade" in comp.best_critical
    assert comp.fairest == ["RR q=3"]
    assert "SJF" in comp.highest_starvation_risk
    assert comp.recommended in {"Prioridade", "Prio+Aging"}
    assert all(0 <= s <= 1 for s in comp.scores.values())
