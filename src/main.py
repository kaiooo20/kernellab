"""KernelLab — simulador de gerenciamento de recursos do cenário MedControl.

Fluxo: entrada dos processos -> escalonamento da CPU -> métricas ->
gerenciamento de memória -> controle de dispositivos -> comparação.

Uso rápido:
    python src/main.py                      # tudo, com os dados de data/
    python src/main.py --quantum 4          # muda o quantum do Round Robin
    python src/main.py --frames 3 --pages 7,0,1,2,0,3,0,4
    python src/main.py --section memory     # só uma etapa
    python src/main.py --help
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import devices as dev
import memory as mem
import metrics as met
import schedulers as sch
import visualization as viz
from models import DATA_DIR, ROOT, load_config, load_json, load_processes


class Output:
    """Imprime no terminal e guarda o mesmo texto para salvar em arquivo."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def title(self, text: str) -> None:
        self("")
        self("=" * 78)
        self(text)
        self("=" * 78)

    def subtitle(self, text: str) -> None:
        self("")
        self(f"--- {text} " + "-" * max(0, 72 - len(text)))


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="KernelLab — simulador de SO (MedControl)")
    ap.add_argument("--processes", default=str(DATA_DIR / "processes.json"),
                    help="JSON com os processos")
    ap.add_argument("--config", default=str(DATA_DIR / "config.json"),
                    help="JSON de configuração (quantum, frames, páginas, pesos)")
    ap.add_argument("--access", default=str(DATA_DIR / "access_matrix.json"),
                    help="JSON com dispositivos e matriz de acesso")
    ap.add_argument("--requests", default=str(DATA_DIR / "device_requests.json"),
                    help="JSON com solicitações concorrentes aos dispositivos")
    ap.add_argument("--quantum", type=int, help="quantum do Round Robin (sobrepõe o config)")
    ap.add_argument("--aging", type=int,
                    help="intervalo de aging da variante de prioridade (0 desliga)")
    ap.add_argument("--frames", type=int, help="quantidade de frames físicos")
    ap.add_argument("--pages", help="sequência de referências separada por vírgula")
    ap.add_argument("--section", choices=["all", "cpu", "memory", "devices"], default="all")
    ap.add_argument("--no-variants", action="store_true",
                    help="mostra só os 4 algoritmos obrigatórios")
    ap.add_argument("--no-charts", action="store_true", help="não gera imagens PNG")
    ap.add_argument("--output", default=str(ROOT / "output"), help="pasta de saída")
    return ap.parse_args(argv)


# --------------------------------------------------------------------------- #
# Etapas 1 e 2 — CPU
# --------------------------------------------------------------------------- #
def run_cpu(out: Output, processes, cfg, args, outdir: Path, export: dict):
    sc = cfg.get("scheduling", {})
    an = cfg.get("analysis", {})
    quantum = args.quantum if args.quantum is not None else int(sc.get("quantum", 3))
    aging = args.aging if args.aging is not None else sc.get("aging_interval")
    aging = aging or None
    critical = sc.get("critical_pid") or min(processes, key=lambda p: p.priority).pid
    if critical not in {p.pid for p in processes}:
        critical = min(processes, key=lambda p: p.priority).pid

    out.title("ENTRADA — PROCESSOS")
    out(viz.table(["PID", "Função", "Chegada", "Burst", "Prioridade", "Memória", "Dispositivos"],
                  [[p.pid, p.name, p.arrival, p.burst, p.priority, f"{p.memory_mb} MB",
                    ", ".join(p.devices)] for p in processes], align="llrrrrl"))
    out(f"Quantum do Round Robin: {quantum}   |   Processo crítico: {critical}   |   "
        "menor número = maior prioridade")

    results = sch.run_all(processes, quantum, aging_interval=aging,
                          aging_floor=int(sc.get("aging_floor", 1)),
                          include_variants=not args.no_variants)
    all_m = [met.compute_metrics(r, an.get("excessive_wait_factor", 1.5),
                                 an.get("excessive_normalized_turnaround", 4.0))
             for r in results]

    out.title("ETAPA 1 — ESCALONAMENTO DA CPU")
    for m in all_m:
        out.subtitle(m.algorithm)
        out("Ordem de execução: " + " -> ".join(m.result.execution_order))
        out("Diagrama de Gantt:")
        out(viz.ascii_gantt(m.result))
        out(viz.table(["PID", "Chegada", "Burst", "Prio", "Início", "Término",
                       "Espera", "Retorno", "Resposta", "Ret.Norm."],
                      [[p.pid, p.arrival, p.burst, p.priority, p.first_start, p.completion,
                        p.waiting, p.turnaround, p.response, f"{p.normalized_turnaround:.2f}"]
                       for p in m.processes]
                      + [["Média", "", "", "", "", "", f"{m.avg_waiting:.2f}",
                          f"{m.avg_turnaround:.2f}", f"{m.avg_response:.2f}", ""]]))
        out(f"Trocas de contexto: {m.context_switches}   |   CPU ociosa: {m.idle_time}   |   "
            f"Utilização: {100 * m.cpu_utilization:.1f}%   |   "
            f"Justiça (Jain): {m.fairness_index:.3f}")
        flagged = [p for p in m.processes if p.notes]
        if flagged:
            out("Atraso excessivo / risco de starvation:")
            for p in flagged:
                tags = []
                if p.excessive_delay:
                    tags.append("ATRASO EXCESSIVO")
                if p.starvation_risk:
                    tags.append("RISCO DE STARVATION")
                out(f"  - {p.pid} [{' + '.join(tags)}]: " + "; ".join(p.notes))
        else:
            out("Atraso excessivo / risco de starvation: nenhum processo sinalizado.")

    # ---------------- Etapa 2 ----------------
    comp = met.compare(all_m, critical, cfg.get("recommendation_weights"))
    out.title("ETAPA 2 — COMPARAÇÃO DOS ESCALONADORES")
    out(viz.table(["Algoritmo", "Espera méd.", "Retorno méd.", "Resposta méd.", "Trocas",
                   f"Resp. {critical}", f"Ret. {critical}", "Jain", "Maior espera",
                   "Starvation", "Nota"],
                  [[m.short_name, f"{m.avg_waiting:.2f}", f"{m.avg_turnaround:.2f}",
                    f"{m.avg_response:.2f}", m.context_switches,
                    m.by_pid(critical).response, m.by_pid(critical).turnaround,
                    f"{m.fairness_index:.3f}", m.max_waiting,
                    ", ".join(m.starving) or "-", f"{comp.scores[m.short_name]:.2f}"]
                   for m in all_m], align="l" + "r" * 10))
    j = " e ".join
    by = {m.short_name: m for m in all_m}
    crit_desc = ", ".join(f"{n}: resposta {by[n].by_pid(critical).response}, "
                          f"retorno {by[n].by_pid(critical).turnaround}"
                          for n in comp.best_critical)
    answers = [
        ("Menor tempo médio de espera", f"{j(comp.lowest_avg_waiting)} "
         f"({by[comp.lowest_avg_waiting[0]].avg_waiting:.2f})"),
        ("Melhor tempo de resposta", f"{j(comp.best_avg_response)} "
         f"({by[comp.best_avg_response[0]].avg_response:.2f})"),
        (f"Tratou o alarme ({critical}) com maior eficiência", f"{j(comp.best_critical)} ({crit_desc})"),
        ("Maior risco de starvation",
         (j(comp.highest_starvation_risk) + " — processos: " +
          "; ".join(f"{n}: {', '.join(by[n].starving)}" for n in comp.highest_starvation_risk))
         if comp.highest_starvation_risk else "nenhum algoritmo sinalizou risco"),
        ("Distribuiu a CPU de forma mais justa", f"{j(comp.fairest)} "
         f"(Jain {by[comp.fairest[0]].fairness_index:.3f})"),
        ("Mais adequado à MedControl (nota multicritério)",
         f"{comp.recommended} ({comp.scores[comp.recommended]:.2f})"),
    ]
    for q, a in answers:
        out(f"• {q}: {a}")
    w = cfg.get("recommendation_weights") or met.DEFAULT_WEIGHTS
    out("Pesos da nota: " + ", ".join(f"{k}={v}" for k, v in w.items()))

    export["cpu"] = {
        "quantum": quantum, "aging_interval": aging, "critical_pid": critical,
        "algorithms": [{
            "name": m.algorithm, "short_name": m.short_name,
            "execution_order": m.result.execution_order,
            "gantt": [{"pid": s.pid, "start": s.start, "end": s.end} for s in m.result.segments],
            "avg_waiting": m.avg_waiting, "avg_turnaround": m.avg_turnaround,
            "avg_response": m.avg_response, "context_switches": m.context_switches,
            "fairness_index": m.fairness_index, "excessive_delay": m.delayed,
            "starvation_risk": m.starving, "score": comp.scores[m.short_name],
            "processes": [{k: getattr(p, k) for k in (
                "pid", "waiting", "turnaround", "response", "first_start", "completion",
                "normalized_turnaround", "overtaken_by")} for p in m.processes],
        } for m in all_m],
        "answers": dict(answers),
    }
    if not args.no_charts:
        g = viz.save_gantt([m.result for m in all_m], outdir / "gantt.png")
        c = viz.save_scheduling_charts(all_m, comp.scores, critical, outdir / "escalonadores.png")
        if g:
            out(f"\nGráficos salvos: {g.relative_to(ROOT) if g.is_relative_to(ROOT) else g}, "
                f"{c.relative_to(ROOT) if c.is_relative_to(ROOT) else c}")
    return all_m, comp


# --------------------------------------------------------------------------- #
# Etapa 3 — Memória
# --------------------------------------------------------------------------- #
def run_memory(out: Output, cfg, args, outdir: Path, export: dict):
    mc = cfg.get("memory", {})
    frames = args.frames if args.frames is not None else int(mc.get("frames", 4))
    if args.pages:
        refs = [int(x) for x in args.pages.replace(" ", "").split(",") if x]
    else:
        refs = [int(x) for x in mc.get("reference_string", [])]
    results = mem.run_all(refs, frames)

    out.title("ETAPA 3 — GERENCIAMENTO DE MEMÓRIA (SUBSTITUIÇÃO DE PÁGINAS)")
    out(f"Frames: {frames}   |   Referências ({len(refs)}): {', '.join(map(str, refs))}")
    for r in results:
        out.subtitle(r.algorithm)
        headers = ["#", "Ref"] + [f"F{i}" for i in range(frames)] + ["Resultado", "Removida"]
        out(viz.table(headers, [[s.index + 1, s.page, *("-" if f is None else f for f in s.frames),
                                 "FAULT" if s.fault else "hit",
                                 "" if s.evicted is None else s.evicted] for s in r.steps]))
        out(f"Page hits: {r.hits}   |   Page faults: {r.faults}   |   "
            f"Taxa de faltas: {100 * r.fault_rate:.2f}%")
    out.subtitle("Resumo")
    out(viz.table(["Algoritmo", "Faults", "Hits", "Taxa de faltas", "Taxa de acertos"],
                  [[r.algorithm, r.faults, r.hits, f"{100 * r.fault_rate:.2f}%",
                    f"{100 * r.hit_rate:.2f}%"] for r in results]))
    out(f"Melhor resultado geral: {', '.join(mem.best(results, include_optimal=True))} "
        f"(referência teórica)")
    out(f"Melhor algoritmo implementável: {', '.join(mem.best(results))}")
    out("Justificativa:")
    for line in mem.explain(results).splitlines():
        out("  " + line)
    export["memory"] = {
        "frames": frames, "references": refs,
        "algorithms": [{"name": r.algorithm, "faults": r.faults, "hits": r.hits,
                        "fault_rate": r.fault_rate,
                        "steps": [{"page": s.page, "frames": s.frames, "fault": s.fault,
                                   "evicted": s.evicted} for s in r.steps]} for r in results],
    }
    if not args.no_charts:
        p = viz.save_memory_charts(results, outdir / "memoria.png")
        if p:
            out(f"\nGráfico salvo: {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}")
    return results


# --------------------------------------------------------------------------- #
# Etapa 4 — Dispositivos
# --------------------------------------------------------------------------- #
def run_devices(out: Output, args, export: dict):
    access = dev.AccessMatrix.from_json(load_json(args.access))
    reqs = load_json(args.requests)
    reqs = reqs["requests"] if isinstance(reqs, dict) else reqs

    out.title("ETAPA 4 — CONTROLE DE DISPOSITIVOS")
    out("Matriz de controle de acesso (R=ler, W=gravar, X=executar, U=utilizar, "
        "E=solicitar exclusivo):")
    out(viz.table(["Processo", *access.devices], access.as_rows(), align="l" + "c" * 4))
    out("Capacidade (vagas do semáforo): " + ", ".join(
        f"{d}={c.get('capacity', 1)}{' (mutex)' if c.get('capacity', 1) == 1 else ''}"
        for d, c in access.devices.items()))

    sim = dev.DeviceManager(access).simulate(reqs)
    out.subtitle("Linha do tempo das solicitações (fila FIFO + semáforo por dispositivo)")
    for t, msg in sim.log:
        out(f"  t={t:>2}  {msg}")
    out.subtitle("Ocupação do disco a cada instante (uso / fila)")
    out(viz.table(["t", "Em uso", "Fila de espera"],
                  [[t, ", ".join(u) or "-", ", ".join(q) or "-"]
                   for t, u, q in sim.timeline.get("disco", [])], align="rll"))
    out.subtitle("Resumo das solicitações")
    out(viz.table(["#", "PID", "Disp.", "Op", "Excl.", "Pedido", "Início", "Fim", "Espera", "Status"],
                  [[r.rid, r.pid, r.device, r.op, "sim" if r.exclusive else "não", r.time,
                    r.granted_at, r.finished_at, r.waited, r.status] for r in sim.requests],
                  align="rlllcrrrrl"))
    out("Uso simultâneo máximo: " + ", ".join(f"{d}={n}" for d, n in sim.max_in_use.items()))
    out("Violações de exclusão mútua: " + ("nenhuma ✔" if not sim.violations
                                           else "; ".join(sim.violations)))

    demo = dev.thread_race_demo()
    out.subtitle("Demonstração com threads reais (condição de corrida no contador do log)")
    out(f"Esperado: {demo['expected']}   |   sem lock: {demo['without_lock']}   |   "
        f"com threading.Lock: {demo['with_lock']}")
    lost = demo["expected"] - demo["without_lock"]
    out(f"Sem exclusão mútua, {lost} gravações se perderam; com o mutex nenhuma." if lost
        else "Nesta execução a corrida não se manifestou, mas o lock garante o resultado.")
    export["devices"] = {
        "matrix": {pid: {d: "".join(sorted(access.permissions(pid, d))) for d in access.devices}
                   for pid in access.pids},
        "requests": [r.__dict__ for r in sim.requests],
        "max_in_use": sim.max_in_use, "violations": sim.violations, "thread_demo": demo,
    }
    return sim


# --------------------------------------------------------------------------- #
# Etapa 5 — Recomendação final
# --------------------------------------------------------------------------- #
def recommendation(out: Output, all_m, comp, mem_results) -> None:
    out.title("ETAPA 5 — RECOMENDAÇÃO TÉCNICA")
    by = {m.short_name: m for m in all_m}
    rec = by[comp.recommended]
    crit = rec.by_pid(comp.critical_pid)
    out(f"Política recomendada: {rec.algorithm}")
    out(f"  • Alarme {comp.critical_pid}: resposta {crit.response}, retorno {crit.turnaround} "
        "— o alarme crítico assume a CPU assim que chega (preempção).")
    out(f"  • Espera média {rec.avg_waiting:.2f} | resposta média {rec.avg_response:.2f} | "
        f"{rec.context_switches} trocas de contexto | Jain {rec.fairness_index:.3f}.")
    aged = next((m for m in all_m if m.short_name == "Prio+Aging"), None)
    plain = by.get("Prioridade")
    if aged and plain:
        low = max(plain.result.processes, key=lambda p: p.priority).pid
        out(f"  • Com aging, a espera do processo menos prioritário ({low}) vai de "
            f"{plain.by_pid(low).waiting} para {aged.by_pid(low).waiting} e os processos em "
            f"risco de starvation passam de {len(plain.starving)} para {len(aged.starving)}, "
            f"mantendo o alarme intacto; em troca, a espera média vai de "
            f"{plain.avg_waiting:.2f} para {aged.avg_waiting:.2f}.")
        out("    Numa carga curta como esta o ganho é pequeno; em operação contínua (novos "
            "alarmes e telemetria chegando sempre) o aging é o que garante que backup e "
            "relatórios terminem. Recomendação: prioridade preemptiva COM aging.")
    else:
        out("  • Em operação contínua, recomenda-se ativar aging (--aging N) para limitar "
            "a espera dos processos de baixa prioridade.")
    rr = next((m for m in all_m if m.short_name.startswith("RR")), None)
    if rr:
        out(f"  • O Round Robin foi o mais justo (Jain {rr.fairness_index:.3f}), mas atrasa o "
            f"alarme (resposta {rr.by_pid(comp.critical_pid).response}); pode ser usado "
            "*dentro* de uma mesma classe de prioridade (filas multinível).")
    if mem_results:
        best = mem.best(mem_results)
        out(f"Memória: {', '.join(best)} — melhor algoritmo implementável; Optimal é só referência.")
    out("Limitações que permanecem:")
    for item in [
        "modelo de CPU única, sem custo de troca de contexto e sem bloqueio por E/S;",
        "bursts conhecidos de antemão (no SO real o SJF precisa estimá-los);",
        "memória e dispositivos simulados de forma independente do escalonador;",
        "fila FIFO simples nos dispositivos, sem prioridade para o alarme nem detecção de deadlock;",
        "tempo discreto e dados de uma única carga — conclusões podem mudar com outras cargas.",
    ]:
        out("  - " + item)


def main(argv=None) -> int:
    args = parse_args(argv)
    out = Output()
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        processes = load_processes(args.processes)
        cfg = load_config(args.config)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Erro ao carregar dados: {exc}", file=sys.stderr)
        return 1

    out("KernelLab — simulador de gerenciamento de recursos | cenário MedControl")
    export: dict = {}
    all_m = comp = mem_results = None
    if args.section in ("all", "cpu"):
        all_m, comp = run_cpu(out, processes, cfg, args, outdir, export)
    if args.section in ("all", "memory"):
        mem_results = run_memory(out, cfg, args, outdir, export)
    if args.section in ("all", "devices"):
        run_devices(out, args, export)
    if all_m:
        recommendation(out, all_m, comp, mem_results)

    (outdir / "resultados.txt").write_text("\n".join(out.lines) + "\n", encoding="utf-8")
    (outdir / "resultados.json").write_text(json.dumps(export, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    print(f"\nSaída completa salva em {outdir}/resultados.txt e resultados.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
