"""Estruturas de dados e carregamento dos arquivos de entrada.

Separar os *dados* (JSON) da *lógica* (algoritmos) é o que permite alterar
processos, quantum, frames e sequência de páginas sem tocar no código.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


@dataclass(frozen=True)
class Process:
    """Um processo da tabela de entrada (imutável: os algoritmos não o alteram)."""

    pid: str
    name: str
    arrival: int
    burst: int
    priority: int
    memory_mb: int = 0
    devices: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.arrival < 0:
            raise ValueError(f"{self.pid}: chegada não pode ser negativa")
        if self.burst <= 0:
            raise ValueError(f"{self.pid}: burst deve ser maior que zero")


def _read_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_processes(path: str | Path = DATA_DIR / "processes.json") -> list[Process]:
    """Lê o JSON de processos e valida PIDs duplicados."""
    data = _read_json(path)
    items = data["processes"] if isinstance(data, dict) else data
    processes = [
        Process(
            pid=str(item["pid"]),
            name=str(item.get("name", item["pid"])),
            arrival=int(item["arrival"]),
            burst=int(item["burst"]),
            priority=int(item["priority"]),
            memory_mb=int(item.get("memory_mb", 0)),
            devices=tuple(item.get("devices", [])),
        )
        for item in items
    ]
    pids = [p.pid for p in processes]
    if len(pids) != len(set(pids)):
        raise ValueError("PIDs duplicados no arquivo de processos")
    if not processes:
        raise ValueError("Nenhum processo informado")
    return processes


def load_config(path: str | Path = DATA_DIR / "config.json") -> dict[str, Any]:
    return _read_json(path)


def load_json(path: str | Path) -> Any:
    return _read_json(path)
