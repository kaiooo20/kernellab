"""Algoritmos de escalonamento de CPU (uma única CPU).

Cada algoritmo recebe a lista de processos e devolve um ``ScheduleResult``
com a linha do tempo (segmentos do Diagrama de Gantt). As métricas são
calculadas depois, em ``metrics.py`` — assim os algoritmos só decidem
*quem usa a CPU e quando*, exatamente como o escalonador de um SO.

Convenções (documentadas no README):
* Tempo discreto em unidades inteiras.
* Empates são resolvidos pela ordem de chegada e, depois, pela ordem no arquivo.
* Round Robin: processos que chegam no mesmo instante em que o quantum de
  outro expira entram na fila *antes* do processo preemptado.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from models import Process

IDLE = None  # pid usado para representar CPU ociosa


@dataclass
class Segment:
    """Trecho contínuo da linha do tempo: ``pid`` usou a CPU em [start, end)."""

    pid: Optional[str]
    start: int
    end: int

    @property
    def duration(self) -> int:
        return self.end - self.start


@dataclass
class ScheduleResult:
    algorithm: str
    processes: list[Process]
    segments: list[Segment] = field(default_factory=list)
    short_name: str = ""

    @property
    def execution_order(self) -> list[str]:
        """Sequência de despachos (sem a CPU ociosa)."""
        return [s.pid for s in self.segments if s.pid is not IDLE]

    @property
    def makespan(self) -> int:
        return self.segments[-1].end if self.segments else 0


def _append(segments: list[Segment], pid: Optional[str], start: int, end: int) -> None:
    """Adiciona um segmento, juntando-o ao anterior se for o mesmo processo contínuo."""
    if end <= start:
        return
    if segments and segments[-1].pid == pid and segments[-1].end == start:
        segments[-1].end = end
    else:
        segments.append(Segment(pid, start, end))


def _index(processes: list[Process]) -> dict[str, int]:
    return {p.pid: i for i, p in enumerate(processes)}


# --------------------------------------------------------------------------- #
# FCFS
# --------------------------------------------------------------------------- #
def fcfs(processes: list[Process]) -> ScheduleResult:
    """First Come, First Served: fila por ordem de chegada, não preemptivo."""
    idx = _index(processes)
    result = ScheduleResult("FCFS", list(processes), short_name="FCFS")
    t = 0
    for p in sorted(processes, key=lambda p: (p.arrival, idx[p.pid])):
        if t < p.arrival:
            _append(result.segments, IDLE, t, p.arrival)
            t = p.arrival
        _append(result.segments, p.pid, t, t + p.burst)
        t += p.burst
    return result


# --------------------------------------------------------------------------- #
# Não preemptivos guiados por chave (SJF e Prioridade não preemptiva)
# --------------------------------------------------------------------------- #
def _non_preemptive(processes: list[Process], key: Callable[[Process], tuple],
                    name: str, short: str) -> ScheduleResult:
    result = ScheduleResult(name, list(processes), short_name=short)
    pending = list(processes)
    t = 0
    while pending:
        ready = [p for p in pending if p.arrival <= t]
        if not ready:
            nxt = min(p.arrival for p in pending)
            _append(result.segments, IDLE, t, nxt)
            t = nxt
            continue
        chosen = min(ready, key=key)
        _append(result.segments, chosen.pid, t, t + chosen.burst)
        t += chosen.burst
        pending.remove(chosen)
    return result


def sjf(processes: list[Process]) -> ScheduleResult:
    """Shortest Job First (não preemptivo): escolhe o menor burst entre os prontos."""
    idx = _index(processes)
    return _non_preemptive(processes, lambda p: (p.burst, p.arrival, idx[p.pid]),
                           "SJF (não preemptivo)", "SJF")


def priority_non_preemptive(processes: list[Process]) -> ScheduleResult:
    """Prioridade não preemptiva: menor número = maior prioridade."""
    idx = _index(processes)
    return _non_preemptive(processes, lambda p: (p.priority, p.arrival, idx[p.pid]),
                           "Prioridade (não preemptiva)", "Prio-NP")


# --------------------------------------------------------------------------- #
# Prioridade preemptiva (com aging opcional)
# --------------------------------------------------------------------------- #
def priority_preemptive(processes: list[Process], aging_interval: Optional[int] = None,
                        aging_floor: int = 1) -> ScheduleResult:
    """Prioridade preemptiva, simulada unidade a unidade de tempo.

    A cada instante o processo pronto de maior prioridade (menor número) usa a
    CPU. Se chegar alguém mais prioritário, o atual é preemptado.

    ``aging_interval``: se informado, a cada ``aging_interval`` unidades que um
    processo passa *esperando* na fila de prontos, sua prioridade efetiva
    melhora em 1 (aging). O ganho é acumulado e não é perdido ao executar.
    ``aging_floor``: limite do aging — processos comuns nunca alcançam
    prioridade melhor que ``aging_floor`` (o nível 0 fica reservado ao alarme).
    """
    if aging_interval is not None and aging_interval <= 0:
        raise ValueError("aging_interval deve ser positivo")
    idx = _index(processes)
    remaining = {p.pid: p.burst for p in processes}
    waited = {p.pid: 0 for p in processes}
    if aging_interval:
        name, short = f"Prioridade preemptiva + aging ({aging_interval})", "Prio+Aging"
    else:
        name, short = "Prioridade (preemptiva)", "Prioridade"
    result = ScheduleResult(name, list(processes), short_name=short)

    def effective(p: Process) -> int:
        if not aging_interval or p.priority <= aging_floor:
            return p.priority
        return max(aging_floor, p.priority - waited[p.pid] // aging_interval)

    t, current = 0, None
    while any(remaining.values()):
        ready = [p for p in processes if p.arrival <= t and remaining[p.pid] > 0]
        if not ready:
            nxt = min(p.arrival for p in processes if remaining[p.pid] > 0)
            _append(result.segments, IDLE, t, nxt)
            t, current = nxt, None
            continue
        best = min(ready, key=lambda p: (effective(p), p.arrival, idx[p.pid]))
        cur = next((p for p in ready if p.pid == current), None)
        if cur is not None and effective(cur) <= effective(best):
            best = cur  # empate: mantém quem está executando (evita troca inútil)
        _append(result.segments, best.pid, t, t + 1)
        remaining[best.pid] -= 1
        for p in ready:
            if p.pid != best.pid:
                waited[p.pid] += 1
        current = best.pid
        t += 1
    return result


# --------------------------------------------------------------------------- #
# Round Robin
# --------------------------------------------------------------------------- #
def round_robin(processes: list[Process], quantum: int) -> ScheduleResult:
    """Round Robin: fila circular, cada processo usa no máximo ``quantum`` por vez."""
    if quantum <= 0:
        raise ValueError("quantum deve ser positivo")
    idx = _index(processes)
    order = sorted(processes, key=lambda p: (p.arrival, idx[p.pid]))
    remaining = {p.pid: p.burst for p in processes}
    result = ScheduleResult(f"Round Robin (q={quantum})", list(processes),
                            short_name=f"RR q={quantum}")
    queue: deque[Process] = deque()
    i, t = 0, 0

    def admit(until: int) -> None:
        nonlocal i
        while i < len(order) and order[i].arrival <= until:
            queue.append(order[i])
            i += 1

    admit(0)
    while queue or i < len(order):
        if not queue:
            _append(result.segments, IDLE, t, order[i].arrival)
            t = order[i].arrival
            admit(t)
            continue
        p = queue.popleft()
        run = min(quantum, remaining[p.pid])
        _append(result.segments, p.pid, t, t + run)
        t += run
        remaining[p.pid] -= run
        admit(t)                 # quem chegou durante a fatia entra antes
        if remaining[p.pid] > 0:
            queue.append(p)      # volta para o fim da fila
    return result


def run_all(processes: list[Process], quantum: int, aging_interval: Optional[int] = None,
            aging_floor: int = 1, include_variants: bool = True) -> list[ScheduleResult]:
    """Executa os quatro algoritmos obrigatórios (+ variantes de prioridade)."""
    results = [
        fcfs(processes),
        sjf(processes),
        round_robin(processes, quantum),
        priority_preemptive(processes),
    ]
    if include_variants:
        results.append(priority_non_preemptive(processes))
        if aging_interval:
            results.append(priority_preemptive(processes, aging_interval, aging_floor))
    return results
