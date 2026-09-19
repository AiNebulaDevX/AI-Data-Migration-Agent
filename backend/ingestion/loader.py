from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class LoadedSourceFile:
    filename: str
    path: Path
    dataframe: pd.DataFrame
    columns: list[str]
    row_count: int


def load_source_file(path: Path) -> LoadedSourceFile:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str, keep_default_na=False)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    df.columns = [str(c).strip() for c in df.columns]
    df = df.fillna("")
    return LoadedSourceFile(
        filename=path.name,
        path=path,
        dataframe=df,
        columns=list(df.columns),
        row_count=len(df),
    )


def profile_column_samples(df: pd.DataFrame, column: str, limit: int = 5) -> list[str]:
    values = df[column].astype(str).head(limit).tolist()
    return [v for v in values if v.strip()]
