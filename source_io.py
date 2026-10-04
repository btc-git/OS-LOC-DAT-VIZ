"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import hashlib
import os
from pathlib import Path
from typing import BinaryIO, Callable, TypeVar

import pandas as pd


T = TypeVar('T')


def file_signature(stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def read_hashed_source(
    file_path: str | Path, reader: Callable[[BinaryIO], T]
) -> tuple[T, str]:
    """Parse and hash one open file, rejecting changes during the load."""
    path = Path(file_path)
    with path.open('rb') as handle:
        initial_signature = file_signature(os.fstat(handle.fileno()))
        result = reader(handle)
        handle.seek(0)
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
        if (
            file_signature(os.fstat(handle.fileno())) != initial_signature
            or file_signature(path.stat()) != initial_signature
        ):
            raise ValueError(
                f"Source file changed while loading: {path.name}. "
                "Reload the file after it has finished changing."
            )
    return result, digest.hexdigest()


def read_csv_text(handle: BinaryIO, *, header: int = 0,
                  nrows: int | None = None) -> pd.DataFrame:
    """Keep CSV source text and identifiers with existing missing-value rules."""
    return pd.read_csv(
        handle, header=header, nrows=nrows, dtype=str,
    )
