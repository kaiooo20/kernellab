"""Algoritmos de substituição de páginas: FIFO, LRU e Optimal (OPT/Belady).

Cada frame tem uma posição fixa, então a tabela "estado dos frames" mostra
exatamente qual moldura física recebeu cada página.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Step:
    index: int
    page: int
    frames: list[Optional[int]]   # estado APÓS a referência
    fault: bool
    evicted: Optional[int] = None


@dataclass
class PagingResult:
    algorithm: str
    frames: int
    references: list[int]
    steps: list[Step] = field(default_factory=list)

    @property
    def faults(self) -> int:
        return sum(s.fault for s in self.steps)

    @property
    def hits(self) -> int:
        return len(self.steps) - self.faults

    @property
    def fault_rate(self) -> float:
        return self.faults / len(self.steps) if self.steps else 0.0

    @property
    def hit_rate(self) -> float:
        return 1 - self.fault_rate if self.steps else 0.0


def _validate(references: list[int], frames: int) -> None:
    if frames <= 0:
        raise ValueError("a quantidade de frames deve ser positiva")
    if not references:
        raise ValueError("a sequência de referências está vazia")


def _simulate(name: str, references: list[int], frames: int, choose_victim) -> PagingResult:
    """Motor comum: só a escolha da vítima muda entre os algoritmos.

    ``choose_victim(slots, i, meta)`` devolve o índice do frame a substituir.
    ``meta`` guarda, por página, o instante em que foi carregada ('loaded') e o
    último acesso ('used').
    """
    _validate(references, frames)
    slots: list[Optional[int]] = [None] * frames
    meta: dict[int, dict[str, int]] = {}
    result = PagingResult(name, frames, list(references))
    for i, page in enumerate(references):
        evicted = None
        if page in slots:
            fault = False
        else:
            fault = True
            if None in slots:
                pos = slots.index(None)
            else:
                pos = choose_victim(slots, i, meta)
                evicted = slots[pos]
                meta.pop(evicted, None)
            slots[pos] = page
            meta[page] = {"loaded": i}
        meta[page]["used"] = i
        result.steps.append(Step(i, page, list(slots), fault, evicted))
    return result


def fifo(references: list[int], frames: int) -> PagingResult:
    """Substitui a página que está há mais tempo na memória."""
    return _simulate("FIFO", references, frames,
                     lambda slots, i, meta: min(range(len(slots)),
                                                key=lambda k: meta[slots[k]]["loaded"]))


def lru(references: list[int], frames: int) -> PagingResult:
    """Substitui a página usada há mais tempo (Least Recently Used)."""
    return _simulate("LRU", references, frames,
                     lambda slots, i, meta: min(range(len(slots)),
                                                key=lambda k: meta[slots[k]]["used"]))


def optimal(references: list[int], frames: int) -> PagingResult:
    """Substitui a página que demorará mais para ser usada de novo.

    Exige conhecer o futuro, por isso não é implementável num SO real; serve
    como limite inferior de faltas para avaliar FIFO e LRU. Empate (várias
    páginas nunca mais usadas): sai a que está há mais tempo na memória.
    """
    def victim(slots, i, meta):
        def next_use(k: int) -> tuple[float, int]:
            page = slots[k]
            try:
                nxt = references.index(page, i + 1)
            except ValueError:
                nxt = float("inf")
            return (nxt, -meta[page]["loaded"])
        return max(range(len(slots)), key=next_use)
    return _simulate("Optimal", references, frames, victim)


def run_all(references: list[int], frames: int) -> list[PagingResult]:
    return [fifo(references, frames), lru(references, frames), optimal(references, frames)]


def best(results: list[PagingResult], include_optimal: bool = False) -> list[str]:
    """Algoritmo(s) com menos faltas. Por padrão compara só os implementáveis."""
    pool = [r for r in results if include_optimal or r.algorithm != "Optimal"]
    low = min(r.faults for r in pool)
    return [r.algorithm for r in pool if r.faults == low]


def explain(results: list[PagingResult]) -> str:
    """Justificativa textual da diferença entre os algoritmos."""
    by = {r.algorithm: r for r in results}
    f, l, o = by["FIFO"], by["LRU"], by["Optimal"]
    lines = [
        f"FIFO teve {f.faults} faltas, LRU {l.faults} e Optimal {o.faults} "
        f"({f.frames} frames, {len(f.references)} referências).",
        "FIFO considera apenas a ordem de carga: remove páginas antigas mesmo "
        "que estejam sendo muito usadas, e então precisa recarregá-las logo depois.",
        "LRU usa o passado recente como previsão do futuro (localidade temporal), "
        "por isso mantém as páginas 'quentes' e erra menos que o FIFO.",
        "Optimal conhece o futuro e sempre remove a página mais distante de ser "
        "usada; é o limite teórico, inalcançável na prática.",
    ]
    if l.faults < f.faults:
        gap = l.faults - o.faults
        lines.append(f"Entre os implementáveis, LRU é o melhor: ficou a {gap} "
                     f"falta(s) do ótimo, contra {f.faults - o.faults} do FIFO.")
    elif f.faults < l.faults:
        lines.append("Nesta sequência o FIFO superou o LRU: o padrão de acesso "
                     "não favorece a localidade temporal.")
    else:
        lines.append("FIFO e LRU empataram nesta sequência.")
    return "\n".join(lines)
