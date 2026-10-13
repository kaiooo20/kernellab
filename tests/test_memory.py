import pytest

import memory as mem


def test_fifo(reference_string):
    r = mem.fifo(reference_string, 4)
    assert (r.faults, r.hits) == (12, 5)
    assert r.fault_rate == pytest.approx(12 / 17)
    assert r.steps[6].evicted == 1           # 5 entra no lugar da página mais antiga
    assert r.steps[-1].frames == [4, 5, 1, 2]


def test_lru(reference_string):
    r = mem.lru(reference_string, 4)
    assert (r.faults, r.hits) == (10, 7)
    assert r.steps[6].evicted == 3           # 3 é a menos usada recentemente
    assert r.steps[-1].frames == [5, 2, 3, 1]


def test_optimal(reference_string):
    r = mem.optimal(reference_string, 4)
    assert (r.faults, r.hits) == (7, 10)
    assert r.steps[6].evicted == 4           # 4 é a que demora mais a voltar


def test_optimal_is_lower_bound(reference_string):
    for frames in range(1, 7):
        f, l, o = mem.run_all(reference_string, frames)
        assert o.faults <= l.faults and o.faults <= f.faults


def test_belady_anomaly_fifo():
    refs = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
    assert mem.fifo(refs, 3).faults == 9
    assert mem.fifo(refs, 4).faults == 10    # mais frames, mais faltas (anomalia de Belady)
    assert mem.lru(refs, 4).faults <= mem.lru(refs, 3).faults


def test_best_and_parameters(reference_string):
    results = mem.run_all(reference_string, 4)
    assert mem.best(results) == ["LRU"]
    assert mem.best(results, include_optimal=True) == ["Optimal"]
    assert mem.fifo([1, 1, 1], 2).faults == 1
    with pytest.raises(ValueError):
        mem.lru(reference_string, 0)
