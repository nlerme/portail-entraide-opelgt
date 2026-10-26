"""Real work counters shared by scraper threads and worker processes."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Callable


def _update(change: Callable[[dict], None], *, reset: bool = False) -> None:
    destination = os.getenv("CATALOG_PROGRESS_FILE") or os.getenv("EDELSCHMIEDE_PROGRESS_FILE")
    if not destination:
        return
    path = Path(destination)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # A separate inode remains stable while the JSON snapshot is replaced.
        with path.with_suffix(path.suffix + ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except (OSError, ValueError):
                data = {}
            previous = 5 if reset else int(data.get("progress_percent", 5))
            change(data)
            data["progress_percent"] = max(previous, min(99, int(data.get("progress_percent", 5))))
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
            temporary.replace(path)
    except (OSError, ValueError, TypeError):
        # Reporting must never alter a scraper's result or network behaviour.
        return


def reset_progress(supplier: str) -> None:
    def reset(data):
        data.clear()
        data.update(supplier=supplier, progress_percent=6, message=f"{supplier} : initialisation.", phases={})
    _update(reset, reset=True)


def report_progress(percent: int, message: str) -> None:
    _update(lambda data: data.update(progress_percent=percent, message=message))


def start_phase(key: str, start: int, end: int, total: int, label: str) -> None:
    def start_work(data):
        data.setdefault("phases", {})[key] = {
            "start": start, "end": end, "total": max(0, total), "done": 0, "units": {}, "label": label,
        }
        data.update(progress_percent=start, message=f"{data.get('supplier', 'Catalogue')} : {label} (0/{total}).")
    _update(start_work)


def advance_phase(
    key: str, *, completed: int | None = None, total: int | None = None,
    amount: int = 1, unit: str | None = None, unit_total: int = 1,
    message: str | None = None,
) -> None:
    def advance(data):
        phase = data.setdefault("phases", {}).setdefault(key, {
            "start": 85, "end": 94, "total": 0, "done": 0, "units": {}, "label": "Désignations traitées",
        })
        if total is not None:
            phase["total"] = max(0, total)
        if unit is None:
            phase["done"] = max(phase["done"], completed) if completed is not None else phase["done"] + amount
            done = phase["done"]
        else:
            work = phase["units"].setdefault(str(unit), {"done": 0, "total": max(1, unit_total)})
            work["total"] = max(1, unit_total)
            work["done"] = max(work["done"], completed) if completed is not None else work["done"] + amount
            done = sum(min(1, value["done"] / value["total"]) for value in phase["units"].values())
        fraction = min(1, done / max(1, phase["total"]))
        data["progress_percent"] = phase["start"] + int((phase["end"] - phase["start"]) * fraction)
        data["message"] = message or (
            f"{data.get('supplier', 'Catalogue')} : {phase['label']} ({done:g}/{phase['total']})."
        )
    _update(advance)
