"""CSV helpers with deterministic output, so the same seed produces identical bytes."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Sequence, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


def _to_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return "|".join(str(v) for v in value)
    return str(value)


def write_models(path: Path, rows: Sequence[BaseModel], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        # Force \n so output bytes do not depend on the host platform.
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(list(columns))
        for row in rows:
            data = row.model_dump()
            writer.writerow([_to_cell(data[c]) for c in columns])


def read_models(path: Path, model: type[M]) -> list[M]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [model.model_validate(row) for row in csv.DictReader(fh)]
