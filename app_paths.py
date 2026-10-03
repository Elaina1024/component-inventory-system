"""Writable application paths for source runs and frozen executables."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog


CONFIG_NAME = "config.ini"
DATABASE_NAME = "inventory.db"


class StorageConfigError(RuntimeError):
    """The saved data location cannot be used safely."""


def application_directory() -> Path:
    """The executable folder when frozen, otherwise this source folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_directory() -> Path:
    """Read-only bundled files are extracted here by PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent


def config_path(app_dir: Path | None = None) -> Path:
    return (Path(app_dir) if app_dir is not None else application_directory()) / CONFIG_NAME


def config_store(app_dir: Path | None = None) -> QSettings:
    return QSettings(str(config_path(app_dir)), QSettings.IniFormat)


def _choose_data_directory(start: Path) -> str:
    return QFileDialog.getExistingDirectory(
        None,
        "选择数据库和备份存放文件夹（取消则使用程序目录）",
        str(start),
        QFileDialog.ShowDirsOnly,
    )


def _resolve_saved_directory(raw: str, app_dir: Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = app_dir / path
    return path.resolve()


def database_path_for_startup(
    app_dir: Path | None = None,
    choose_directory: Callable[[Path], str] | None = None,
    store: QSettings | None = None,
) -> Path:
    """Choose on first run, then reuse the chosen folder without prompting.

    The default is stored as '.' so moving the executable and config together
    keeps its database beside the executable. If an externally chosen folder
    disappears, cancellation aborts startup instead of creating a new empty DB.
    """
    app_dir = (Path(app_dir) if app_dir is not None else application_directory()).resolve()
    store = store if store is not None else config_store(app_dir)
    chooser = choose_directory or _choose_data_directory
    initialized = store.value("storage/initialized", False, type=bool)

    if initialized:
        raw = str(store.value("storage/data_directory", ".") or ".")
        data_dir = _resolve_saved_directory(raw, app_dir)
        if data_dir.is_dir():
            return data_dir / DATABASE_NAME
        selected = chooser(app_dir)
        if not selected:
            raise StorageConfigError(
                f"原数据目录不可用：{data_dir}。请选择原数据目录或其他现有目录。"
            )
    else:
        selected = chooser(app_dir)

    data_dir = Path(selected).resolve() if selected else app_dir
    if not data_dir.is_dir():
        raise StorageConfigError(f"数据目录不存在：{data_dir}")
    stored_path = "." if data_dir == app_dir else str(data_dir)
    store.setValue("storage/data_directory", stored_path)
    store.setValue("storage/initialized", True)
    store.sync()
    if store.status() != QSettings.NoError:
        raise StorageConfigError(
            f"无法在程序目录保存配置文件：{config_path(app_dir)}。请将程序放在可写入的目录。"
        )
    return data_dir / DATABASE_NAME
