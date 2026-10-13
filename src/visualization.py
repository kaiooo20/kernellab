"""Saída visual: tabelas e Gantt no terminal + gráficos PNG (matplotlib).

O matplotlib é opcional: sem ele o simulador funciona normalmente no
terminal e apenas pula a geração das imagens.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

from schedulers import IDLE, ScheduleResult

# Paleta categórica validada para daltonismo (um tom por processo, ordem fixa).
PROCESS_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
LABEL_ON_COLOR = {"#2a78d6": "white", "#008300": "white", "#eb6834": "#1a1a19",
                  "#1baf7a": "#1a1a19", "#eda100": "#1a1a19", "#e87ba4": "#1a1a19"}
BAR_COLOR = "#2a78d6"
INK, INK_MUTED, GRID = "#1a1a19", "#6b6a63", "#e4e3dd"
IDLE_COLOR = "#d6d5ce"


# --------------------------------------------------------------------------- #
# Terminal
# --------------------------------------------------------------------------- #
def table(headers: Sequence[str], rows: Iterable[Sequence], align: Optional[str] = None) -> str:
    """Tabela em texto com bordas simples. ``align``: 'l'/'r' por coluna."""
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    headers = [str(h) for h in headers]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h)
              for i, h in enumerate(headers)]
    align = align or "l" + "r" * (len(headers) - 1)

    def fmt(cells: Sequence[str]) -> str:
        out = []
        for i, c in enumerate(cells):
            out.append(c.ljust(widths[i]) if align[i] == "l" else c.rjust(widths[i]))
        return "| " + " | ".join(out) + " |"

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    return "\n".join([sep, fmt(headers), sep.replace("-", "="), *map(fmt, rows), sep])


def markdown_table(headers: Sequence[str], rows: Iterable[Sequence]) -> str:
    lines = ["| " + " | ".join(map(str, headers)) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def ascii_gantt(result: ScheduleResult, unit: int = 3) -> str:
    """Diagrama de Gantt em texto. Cada unidade de tempo ocupa ``unit`` colunas."""
    bar, ticks = "|", "0"
    for seg in result.segments:
        width = seg.duration * unit
        label = "--" if seg.pid is IDLE else seg.pid
        cell = label.center(width - 1)[: width - 1]
        bar += cell + "|"
        end = str(seg.end)
        ticks += end.rjust(width)
    return bar + "\n" + ticks


# --------------------------------------------------------------------------- #
# Gráficos
# --------------------------------------------------------------------------- #
def _plt():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError:  # pragma: no cover - depende do ambiente
        return None


def _style(ax) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_MUTED, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def save_gantt(results: list[ScheduleResult], path: Path) -> Optional[Path]:
    plt = _plt()
    if plt is None:
        return None
    pids = [p.pid for p in results[0].processes]
    color = {pid: PROCESS_COLORS[i % len(PROCESS_COLORS)] for i, pid in enumerate(pids)}
    horizon = max(r.makespan for r in results)
    fig, axes = plt.subplots(len(results), 1, figsize=(11, 1.25 * len(results) + 0.8),
                             sharex=True)
    if len(results) == 1:
        axes = [axes]
    for ax, res in zip(axes, results):
        for seg in res.segments:
            c = IDLE_COLOR if seg.pid is IDLE else color[seg.pid]
            ax.barh(0, seg.duration, left=seg.start, height=0.62, color=c,
                    edgecolor="white", linewidth=2)
            if seg.duration >= 1:
                ax.text(seg.start + seg.duration / 2, 0, "ocioso" if seg.pid is IDLE else seg.pid,
                        ha="center", va="center", fontsize=8.5, fontweight="bold",
                        color=INK if seg.pid is IDLE else LABEL_ON_COLOR.get(c, INK))
        ax.set_yticks([])
        ax.set_ylabel(res.short_name, rotation=0, ha="right", va="center",
                      fontsize=9.5, color=INK)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK_MUTED, length=0)
        ax.set_xlim(0, horizon)
        ax.set_xticks(range(0, horizon + 1, 2))
        ax.xaxis.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
    axes[-1].set_xlabel("tempo (unidades)", color=INK_MUTED)
    fig.suptitle("Diagramas de Gantt", x=0.02, ha="left", fontsize=12, color=INK,
                 fontweight="bold")
    handles = [plt.Rectangle((0, 0), 1, 1, color=color[p]) for p in pids]
    names = {p.pid: p.name for p in results[0].processes}
    fig.legend(handles, [f"{p} {names[p]}" for p in pids], loc="lower center",
               ncol=3, frameon=False, fontsize=8.5, bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.07, 1, 0.97))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _small_multiples(panels: list[tuple[str, list[str], list[float], str]], title: str,
                     path: Path, ncols: int = 3) -> Optional[Path]:
    """Um painel por métrica (sem eixo duplo), uma cor, valores rotulados."""
    plt = _plt()
    if plt is None:
        return None
    nrows = (len(panels) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.0 * ncols, 3.3 * nrows), squeeze=False)
    for ax, (name, labels, values, fmt) in zip(axes.flat, panels):
        best = min(values) if "↓" in name else max(values)
        colors = [BAR_COLOR if v == best else "#9ec5f4" for v in values]
        bars = ax.bar(labels, values, color=colors, width=0.62, edgecolor="white", linewidth=2)
        for b, v in zip(bars, values):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), format(v, fmt),
                    ha="center", va="bottom", fontsize=8.5, color=INK)
        ax.set_title(name, fontsize=10, color=INK, loc="left")
        ax.tick_params(axis="x", labelrotation=30, labelsize=8)
        for lab in ax.get_xticklabels():
            lab.set_ha("right")
        ax.margins(y=0.15)
        if fmt == "d":
            from matplotlib.ticker import MaxNLocator
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        _style(ax)
    for ax in list(axes.flat)[len(panels):]:
        ax.axis("off")
    fig.suptitle(title + "   (barra escura = melhor; ↓ menor é melhor, ↑ maior é melhor)",
                 x=0.02, ha="left", fontsize=11, color=INK, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def save_scheduling_charts(all_metrics, scores: dict[str, float], critical_pid: str,
                           path: Path) -> Optional[Path]:
    labels = [m.short_name for m in all_metrics]
    panels = [
        ("Espera média ↓", labels, [m.avg_waiting for m in all_metrics], ".2f"),
        ("Retorno médio ↓", labels, [m.avg_turnaround for m in all_metrics], ".2f"),
        ("Resposta média ↓", labels, [m.avg_response for m in all_metrics], ".2f"),
        ("Trocas de contexto ↓", labels, [m.context_switches for m in all_metrics], "d"),
        (f"Retorno do alarme {critical_pid} ↓", labels,
         [m.by_pid(critical_pid).turnaround for m in all_metrics], "d"),
        ("Justiça (índice de Jain) ↑", labels, [m.fairness_index for m in all_metrics], ".3f"),
        ("Maior espera individual ↓", labels, [m.max_waiting for m in all_metrics], "d"),
        ("Processos em risco de starvation ↓", labels,
         [len(m.starving) for m in all_metrics], "d"),
        ("Nota multicritério ↑", labels, [scores[l] for l in labels], ".2f"),
    ]
    return _small_multiples(panels, "Comparação dos escalonadores", path)


def save_memory_charts(results, path: Path) -> Optional[Path]:
    labels = [r.algorithm for r in results]
    panels = [
        ("Page faults ↓", labels, [r.faults for r in results], "d"),
        ("Page hits ↑", labels, [r.hits for r in results], "d"),
        ("Taxa de faltas (%) ↓", labels, [round(100 * r.fault_rate, 1) for r in results], ".1f"),
    ]
    return _small_multiples(panels, f"Substituição de páginas ({results[0].frames} frames)", path)
