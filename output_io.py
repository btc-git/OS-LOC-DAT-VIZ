"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from source_io import file_signature


def write_output_set(contents: Mapping[Path, str]) -> None:
    """Stage siblings before replacing them; restore originals on I/O failure."""
    staged = {}
    backups = {}
    installed = []
    originals = {}
    recovery_failed = False
    for path in contents:
        if path.exists() and not path.is_file():
            raise OSError(f"Output destination is not a file: {path}")
        originals[path] = file_signature(path.stat()) if path.exists() else None

    try:
        for path, text in contents.items():
            descriptor, temporary_name = tempfile.mkstemp(
                prefix='.osloc-', suffix='.tmp', dir=path.parent
            )
            staged[path] = Path(temporary_name)
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(text.encode('utf-8'))
                handle.flush()
                os.fsync(handle.fileno())

        for path, signature in originals.items():
            current = file_signature(path.stat()) if path.exists() else None
            if current != signature:
                raise OSError(f"Output changed while preparing to save: {path}")

        try:
            for path, signature in originals.items():
                if signature is not None:
                    descriptor, backup_name = tempfile.mkstemp(
                        prefix='.osloc-', suffix='.bak', dir=path.parent
                    )
                    os.close(descriptor)
                    backup = Path(backup_name)
                    try:
                        path.replace(backup)
                    except OSError:
                        backup.unlink()
                        raise
                    backups[path] = backup
            for path, temporary_path in staged.items():
                temporary_path.replace(path)
                installed.append(path)
        except OSError as save_error:
            recovery_errors = []
            for path in reversed(installed):
                try:
                    path.unlink()
                except OSError as error:
                    recovery_errors.append(f"{path}: {error}")
            for path, backup in backups.items():
                try:
                    backup.replace(path)
                except OSError as error:
                    recovery_errors.append(f"{path} (backup {backup}): {error}")
            if recovery_errors:
                recovery_failed = True
                raise OSError(
                    f"Save failed: {save_error}. Recovery was incomplete; "
                    "preserve the remaining backup files. "
                    + "; ".join(recovery_errors)
                ) from save_error
            raise
    finally:
        active_error = sys.exc_info()[1]
        cleanup_errors = []
        for temporary_path in staged.values():
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as error:
                cleanup_errors.append(f"{temporary_path}: {error}")
        if not recovery_failed:
            for backup in backups.values():
                try:
                    backup.unlink(missing_ok=True)
                except OSError as error:
                    cleanup_errors.append(f"{backup}: {error}")
        if cleanup_errors:
            message = "Temporary/backup cleanup failed: " + "; ".join(cleanup_errors)
            if active_error is not None:
                message = f"{active_error}. {message}"
            raise OSError(message) from active_error
