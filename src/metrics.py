"""Cálculo das métricas de escalonamento e comparação entre algoritmos.

Definições (para cada processo):
* tempo de retorno (turnaround) = término - chegada
* tempo de espera              = retorno - burst
* tempo de resposta            = primeiro uso da CPU - chegada
* retorno normalizado          = retorno / burst  (1,0 = nunca esperou)

Indicadores de risco:
* atraso excessivo: espera > fator x espera média, ou retorno normalizado >= limite
* risco de starvation: o processo foi "ultrapassado" por processos que chegaram
  depois dele (começaram a executar antes) E esperou pelo menos a média.
  Com um fluxo contínuo de processos assim, ele poderia esperar indefinidamente.

Justiça: índice de Jain sobre x_i = burst_i / retorno_i (fração do tempo de
permanência em que o processo recebeu CPU). 1,0 = todos tratados igualmente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Optional

from schedulers import IDLE, ScheduleResult


@dataclass
class ProcessMetrics:
    pid: str
    name: str
    arrival: int
    burst: int
    priority: int
    first_start: int
    completion: int
    waiting: int
    turnaround: int
    response: int
    normalized_turnaround: float
    overtaken_by: list[str] = field(default_factory=list)
    excessive_delay: bool = False
    starvation_risk: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class ScheduleMetrics:
    algorithm: str
    short_name: str
    result: ScheduleResult
    processes: list[ProcessMetrics]
    avg_waiting: float
    avg_turnaround: float
    avg_response: float
    context_switches: int
    idle_time: int
    cpu_utilization: float
    throughput: float
    fairness_index: float
    max_waiting: int
    std_waiting: float

    def by_pid(self, pid: str) -> ProcessMetrics:
        return next(p for p in self.processes if p.pid == pid)

    @property
    def delayed(self) -> list[str]:
        return [p.pid for p in self.processes if p.excessive_delay]

    @property
    def starving(self) -> list[str]:
        return [p.pid for p in self.processes if p.starvation_risk]


def count_context_switches(result: ScheduleResult) -> int:
    """Número de vezes em que a CPU passa de um processo para outro diferente.

    A carga inicial do primeiro processo não conta como troca; períodos de CPU
    ociosa entre dois trechos do mesmo processo também não.
    """
    order = result.execution_order
    return sum(1 for a, b in zip(order, order[1:]) if a != b)


def jain_index(values: list[float]) -> float:
    if not values or not any(values):
        return 0.0
    return sum(values) ** 2 / (len(values) * sum(v * v for v in values))


def compute_metrics(result: ScheduleResult, wait_factor: float = 1.5,
                    nt_limit: float = 4.0) -> ScheduleMetrics:
    first_start: dict[str, int] = {}
    completion: dict[str, int] = {}
    executed: dict[str, int] = {}
    idle = 0
    for seg in result.segments:
        if seg.pid is IDLE:
            idle += seg.duration
            continue
        first_start.setdefault(seg.pid, seg.start)
        completion[seg.pid] = seg.end
        executed[seg.pid] = executed.get(seg.pid, 0) + seg.duration

    rows: list[ProcessMetrics] = []
    for p in result.processes:
        if executed.get(p.pid) != p.burst:
            raise AssertionError(f"{result.algorithm}: {p.pid} executou "
                                 f"{executed.get(p.pid, 0)} de {p.burst} unidades")
        tat = completion[p.pid] - p.arrival
        rows.append(ProcessMetrics(
            pid=p.pid, name=p.name, arrival=p.arrival, burst=p.burst, priority=p.priority,
            first_start=first_start[p.pid], completion=completion[p.pid],
            waiting=tat - p.burst, turnaround=tat,
            response=first_start[p.pid] - p.arrival,
            normalized_turnaround=tat / p.burst,
        ))

    avg_wait = mean(r.waiting for r in rows)
    for r in rows:
        r.overtaken_by = [o.pid for o in rows
                          if o.arrival > r.arrival and o.first_start < r.first_start]
        if r.waiting > 0 and r.waiting > wait_factor * avg_wait:
            r.excessive_delay = True
            r.notes.append(f"espera {r.waiting} > {wait_factor}x média ({avg_wait:.2f})")
        if r.normalized_turnaround >= nt_limit:
            r.excessive_delay = True
            r.notes.append(f"retorno normalizado {r.normalized_turnaround:.2f} >= {nt_limit}")
        if r.overtaken_by and r.waiting >= avg_wait:
            r.starvation_risk = True
            r.notes.append("ultrapassado por " + ", ".join(r.overtaken_by)
                           + " (chegaram depois)")

    makespan = result.makespan
    start = min(p.arrival for p in result.processes)
    busy = sum(r.burst for r in rows)
    span = makespan - start
    return ScheduleMetrics(
        algorithm=result.algorithm,
        short_name=result.short_name or result.algorithm,
        result=result,
        processes=rows,
        avg_waiting=avg_wait,
        avg_turnaround=mean(r.turnaround for r in rows),
        avg_response=mean(r.response for r in rows),
        context_switches=count_context_switches(result),
        idle_time=idle,
        cpu_utilization=busy / span if span else 1.0,
        throughput=len(rows) / span if span else 0.0,
        fairness_index=jain_index([r.burst / r.turnaround for r in rows]),
        max_waiting=max(r.waiting for r in rows),
        std_waiting=pstdev([r.waiting for r in rows]),
    )


# --------------------------------------------------------------------------- #
# Comparação (Etapa 2)
# --------------------------------------------------------------------------- #
DEFAULT_WEIGHTS = {
    "avg_waiting": 0.20, "avg_response": 0.15, "critical_response": 0.30,
    "fairness": 0.15, "starvation": 0.10, "context_switches": 0.10,
}


def _best(items: list[ScheduleMetrics], value, lower_is_better: bool = True) -> list[str]:
    vals = [value(m) for m in items]
    target = min(vals) if lower_is_better else max(vals)
    def same(v) -> bool:
        return abs(v - target) < 1e-9 if isinstance(v, float) else v == target
    return [m.short_name for m, v in zip(items, vals) if same(v)]


def _critical_cost(m: ScheduleMetrics, critical_pid: str) -> tuple[int, int]:
    c = m.by_pid(critical_pid)
    return (c.response, c.turnaround)


@dataclass
class Comparison:
    lowest_avg_waiting: list[str]
    best_avg_response: list[str]
    best_critical: list[str]
    highest_starvation_risk: list[str]
    fairest: list[str]
    scores: dict[str, float]
    criteria: dict[str, dict[str, float]]
    recommended: str
    critical_pid: str


def compare(all_metrics: list[ScheduleMetrics], critical_pid: Optional[str] = None,
            weights: Optional[dict[str, float]] = None) -> Comparison:
    """Responde às perguntas da Etapa 2 e calcula uma nota multicritério.

    A nota normaliza cada critério para [0, 1] (1 = melhor entre os algoritmos)
    e aplica pesos configuráveis em ``config.json``. O alarme crítico recebe o
    maior peso porque, no cenário hospitalar, atrasá-lo coloca vidas em risco.
    """
    weights = weights or DEFAULT_WEIGHTS
    if critical_pid is None:
        critical_pid = min(all_metrics[0].result.processes, key=lambda p: p.priority).pid

    raw = {
        "avg_waiting": ([m.avg_waiting for m in all_metrics], True),
        "avg_response": ([m.avg_response for m in all_metrics], True),
        "critical_response": ([sum(_critical_cost(m, critical_pid)) for m in all_metrics], True),
        "fairness": ([m.fairness_index for m in all_metrics], False),
        "starvation": ([len(m.starving) for m in all_metrics], True),
        "context_switches": ([m.context_switches for m in all_metrics], True),
    }
    criteria: dict[str, dict[str, float]] = {m.short_name: {} for m in all_metrics}
    for crit, (vals, lower) in raw.items():
        lo, hi = min(vals), max(vals)
        for m, v in zip(all_metrics, vals):
            if hi == lo:
                norm = 1.0
            else:
                norm = (hi - v) / (hi - lo) if lower else (v - lo) / (hi - lo)
            criteria[m.short_name][crit] = norm
    total_w = sum(weights.values())
    scores = {name: sum(weights[c] * v for c, v in crit.items()) / total_w
              for name, crit in criteria.items()}

    starv_counts = [len(m.starving) for m in all_metrics]
    if max(starv_counts) == 0:
        highest = []
    else:
        # desempate: maior espera entre os processos em risco
        key = lambda m: (len(m.starving),
                         max((m.by_pid(p).waiting for p in m.starving), default=0))
        top = max(key(m) for m in all_metrics)
        highest = [m.short_name for m in all_metrics if key(m) == top]

    return Comparison(
        lowest_avg_waiting=_best(all_metrics, lambda m: m.avg_waiting),
        best_avg_response=_best(all_metrics, lambda m: m.avg_response),
        best_critical=_best(all_metrics, lambda m: _critical_cost(m, critical_pid)),
        highest_starvation_risk=highest,
        fairest=_best(all_metrics, lambda m: m.fairness_index, lower_is_better=False),
        scores=scores,
        criteria=criteria,
        recommended=max(scores, key=scores.get),
        critical_pid=critical_pid,
    )
