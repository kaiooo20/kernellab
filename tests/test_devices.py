import devices as dev
from models import DATA_DIR, load_json


def manager():
    return dev.DeviceManager(dev.AccessMatrix.from_json(load_json(DATA_DIR / "access_matrix.json")))


def test_access_matrix_least_privilege():
    acc = manager().access
    assert acc.check("P4", "audio", "X", exclusive=True)[0]       # só o alarme toca o áudio
    assert not acc.check("P2", "audio", "X")[0]
    assert acc.check("P5", "disco", "W", exclusive=True)[0]       # backup pede o disco inteiro
    assert not acc.check("P6", "disco", "W", exclusive=True)[0]
    assert not acc.check("P3", "logs", "W")[0]                    # relatórios só leem o log


def test_disk_is_never_shared():
    reqs = [
        {"pid": "P3", "device": "disco", "time": 0, "duration": 3, "op": "W"},
        {"pid": "P5", "device": "disco", "time": 0, "duration": 2, "op": "W", "exclusive": True},
        {"pid": "P6", "device": "disco", "time": 0, "duration": 1, "op": "R"},
    ]
    sim = manager().simulate(reqs)
    assert sim.violations == []
    assert sim.max_in_use["disco"] == 1
    order = sorted(sim.requests, key=lambda r: r.granted_at)
    assert [(r.pid, r.granted_at) for r in order] == [("P3", 0), ("P5", 3), ("P6", 5)]


def test_network_semaphore_allows_two():
    reqs = [{"pid": p, "device": "rede", "time": 0, "duration": 2, "op": "W"}
            for p in ("P1", "P2", "P4")]
    sim = manager().simulate(reqs)
    assert sim.max_in_use["rede"] == 2
    assert sim.requests[2].granted_at == 2   # terceiro espera uma vaga


def test_exclusive_waits_for_empty_device():
    sem = dev.DeviceSemaphore(2)
    assert sem.try_acquire("A", False)
    assert not sem.try_acquire("B", True)
    sem.release("A", False)
    assert sem.try_acquire("B", True)
    assert not sem.try_acquire("C", False)


def test_unauthorized_request_is_denied():
    sim = manager().simulate([{"pid": "P1", "device": "disco", "time": 0, "duration": 1, "op": "W"}])
    assert sim.requests[0].status == "negado"


def test_default_scenario_runs_clean():
    sim = manager().simulate(load_json(DATA_DIR / "device_requests.json")["requests"])
    assert sim.violations == []
    assert len(sim.denied) == 3
    assert all(r.status in {"concluído", "negado"} for r in sim.requests)


def test_lock_prevents_lost_updates():
    demo = dev.thread_race_demo(threads=4, increments=100)
    assert demo["with_lock"] == demo["expected"]
