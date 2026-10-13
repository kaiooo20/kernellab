"""Controle de acesso e concorrência nos dispositivos compartilhados.

Duas partes:
1. ``AccessMatrix``: matriz de controle de acesso (R, W, X, U, E) — o "quem pode".
2. ``DeviceManager``: simulação determinística de solicitações concorrentes. Cada
   dispositivo tem uma fila FIFO e um *semáforo contador* com a capacidade do
   dispositivo (capacidade 1 = mutex). Pedidos exclusivos só entram com o
   dispositivo vazio e ocupam todas as vagas — o "quando pode".

Há também ``thread_race_demo``, que usa threads reais do Python para mostrar
uma condição de corrida e como ``threading.Lock`` a evita.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

PERMISSIONS = {
    "R": "ler",
    "W": "gravar",
    "X": "executar",
    "U": "utilizar",
    "E": "acesso exclusivo",
}


# --------------------------------------------------------------------------- #
# Matriz de controle de acesso
# --------------------------------------------------------------------------- #
class AccessMatrix:
    def __init__(self, matrix: dict[str, dict[str, str]], devices: dict[str, dict]):
        self.devices = devices
        self.matrix = {pid: {dev: set(perms.upper()) for dev, perms in row.items()}
                       for pid, row in matrix.items()}
        for pid, row in self.matrix.items():
            for dev, perms in row.items():
                if dev not in devices:
                    raise ValueError(f"{pid}: dispositivo desconhecido '{dev}'")
                invalid = perms - PERMISSIONS.keys()
                if invalid:
                    raise ValueError(f"{pid}/{dev}: permissões inválidas {invalid}")

    @classmethod
    def from_json(cls, data: dict) -> "AccessMatrix":
        return cls(data["matrix"], data["devices"])

    @property
    def pids(self) -> list[str]:
        return list(self.matrix)

    def permissions(self, pid: str, device: str) -> set[str]:
        return self.matrix.get(pid, {}).get(device, set())

    def can(self, pid: str, device: str, perm: str) -> bool:
        return perm.upper() in self.permissions(pid, device)

    def check(self, pid: str, device: str, op: str, exclusive: bool = False) -> tuple[bool, str]:
        """Valida um pedido. Usar o dispositivo exige U + a operação (+ E se exclusivo)."""
        perms = self.permissions(pid, device)
        needed = {"U", op.upper()} | ({"E"} if exclusive else set())
        missing = needed - perms
        if missing:
            names = ", ".join(PERMISSIONS[m] for m in sorted(missing))
            return False, f"negado: {pid} não tem permissão de {names} em '{device}'"
        return True, "autorizado"

    def as_rows(self) -> list[list[str]]:
        """Linhas (processo x dispositivo) no formato 'RWXUE' com '-' para ausência."""
        rows = []
        for pid in self.pids:
            row = [pid]
            for dev in self.devices:
                perms = self.permissions(pid, dev)
                row.append("".join(p if p in perms else "-" for p in PERMISSIONS))
            rows.append(row)
        return rows


# --------------------------------------------------------------------------- #
# Semáforo do dispositivo
# --------------------------------------------------------------------------- #
class DeviceSemaphore:
    """Semáforo contador com suporte a modo exclusivo.

    ``capacity`` vagas; P() (acquire) falha se não houver vaga, V() (release)
    devolve a vaga. Em modo exclusivo o pedido precisa de *todas* as vagas, o
    que equivale a um mutex sobre o dispositivo inteiro.
    """

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacidade deve ser positiva")
        self.capacity = capacity
        self.value = capacity
        self.exclusive_holder: Optional[str] = None

    def try_acquire(self, pid: str, exclusive: bool) -> bool:
        if self.exclusive_holder is not None:
            return False
        if exclusive:
            if self.value != self.capacity:
                return False
            self.value = 0
            self.exclusive_holder = pid
            return True
        if self.value == 0:
            return False
        self.value -= 1
        return True

    def release(self, pid: str, exclusive: bool) -> None:
        if exclusive:
            assert self.exclusive_holder == pid
            self.exclusive_holder = None
            self.value = self.capacity
        else:
            self.value += 1
            assert self.value <= self.capacity, "release sem acquire correspondente"

    @property
    def in_use(self) -> int:
        return self.capacity - self.value


@dataclass
class Request:
    rid: int
    pid: str
    device: str
    time: int
    duration: int
    op: str
    exclusive: bool = False
    status: str = "pendente"        # pendente | negado | em uso | concluído
    reason: str = ""
    granted_at: Optional[int] = None
    finished_at: Optional[int] = None

    @property
    def waited(self) -> Optional[int]:
        return None if self.granted_at is None else self.granted_at - self.time


@dataclass
class DeviceSimulation:
    requests: list[Request]
    log: list[tuple[int, str]] = field(default_factory=list)
    timeline: dict[str, list[tuple[int, list[str], list[str]]]] = field(default_factory=dict)
    max_in_use: dict[str, int] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)

    @property
    def denied(self) -> list[Request]:
        return [r for r in self.requests if r.status == "negado"]

    @property
    def completed(self) -> list[Request]:
        return [r for r in self.requests if r.status == "concluído"]


class DeviceManager:
    def __init__(self, access: AccessMatrix):
        self.access = access

    def simulate(self, raw_requests: list[dict]) -> DeviceSimulation:
        reqs = [Request(i, r["pid"], r["device"], int(r["time"]), int(r["duration"]),
                        r.get("op", "W").upper(), bool(r.get("exclusive", False)))
                for i, r in enumerate(raw_requests)]
        for r in reqs:
            if r.device not in self.access.devices:
                raise ValueError(f"dispositivo desconhecido: {r.device}")
            if r.duration <= 0:
                raise ValueError("duração deve ser positiva")
        sim = DeviceSimulation(reqs)
        sems = {d: DeviceSemaphore(int(cfg.get("capacity", 1)))
                for d, cfg in self.access.devices.items()}
        queues: dict[str, deque[Request]] = {d: deque() for d in sems}
        active: dict[str, list[Request]] = {d: [] for d in sems}
        sim.timeline = {d: [] for d in sems}
        sim.max_in_use = {d: 0 for d in sems}
        arrivals = sorted(reqs, key=lambda r: (r.time, r.rid))
        t, k = 0, 0

        def busy() -> bool:
            return any(queues.values()) or any(active.values())

        while k < len(arrivals) or busy():
            # 1) libera quem terminou (V / signal)
            for dev, lst in active.items():
                for r in [r for r in lst if r.granted_at + r.duration == t]:
                    lst.remove(r)
                    sems[dev].release(r.pid, r.exclusive)
                    r.status, r.finished_at = "concluído", t
                    sim.log.append((t, f"{r.pid} liberou {dev}"))
            # 2) novos pedidos: verificação na matriz e entrada na fila
            while k < len(arrivals) and arrivals[k].time == t:
                r = arrivals[k]
                k += 1
                ok, msg = self.access.check(r.pid, r.device, r.op, r.exclusive)
                if not ok:
                    r.status, r.reason = "negado", msg
                    sim.log.append((t, msg))
                    continue
                queues[r.device].append(r)
                kind = "exclusivo " if r.exclusive else ""
                sim.log.append((t, f"{r.pid} pediu {kind}{r.device} ({r.op}) -> fila"))
            # 3) atende a fila em ordem FIFO estrita (P / wait)
            for dev, q in queues.items():
                while q and sems[dev].try_acquire(q[0].pid, q[0].exclusive):
                    r = q.popleft()
                    r.status, r.granted_at = "em uso", t
                    active[dev].append(r)
                    extra = f" após esperar {r.waited}" if r.waited else ""
                    sim.log.append((t, f"{r.pid} obteve {dev}{extra}"))
                # 4) verificação de invariantes (exclusão mútua)
                users = [r.pid for r in active[dev]]
                if len(users) > sems[dev].capacity:
                    sim.violations.append(f"t={t}: {dev} acima da capacidade")
                if any(r.exclusive for r in active[dev]) and len(users) > 1:
                    sim.violations.append(f"t={t}: {dev} exclusivo compartilhado")
                sim.max_in_use[dev] = max(sim.max_in_use[dev], len(users))
                sim.timeline[dev].append((t, users, [r.pid for r in q]))
            if k >= len(arrivals) and not busy():
                break
            t += 1
        return sim


# --------------------------------------------------------------------------- #
# Demonstração com threads reais
# --------------------------------------------------------------------------- #
def thread_race_demo(threads: int = 4, increments: int = 200) -> dict[str, int]:
    """Vários 'processos' gravam no contador de linhas do arquivo de log.

    Sem lock, a sequência ler -> (troca de contexto) -> gravar perde
    atualizações (condição de corrida). Com ``threading.Lock`` a seção crítica
    é executada por uma thread de cada vez e o resultado é sempre correto.
    ``time.sleep(0)`` força o escalonador do Python a trocar de thread no pior
    momento, deixando o problema visível.
    """
    expected = threads * increments

    def run(use_lock: bool) -> int:
        state = {"lines": 0}
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(increments):
                if use_lock:
                    with lock:
                        current = state["lines"]
                        time.sleep(0)
                        state["lines"] = current + 1
                else:
                    current = state["lines"]
                    time.sleep(0)
                    state["lines"] = current + 1

        ts = [threading.Thread(target=worker) for _ in range(threads)]
        for th in ts:
            th.start()
        for th in ts:
            th.join()
        return state["lines"]

    return {"expected": expected, "without_lock": run(False), "with_lock": run(True)}
