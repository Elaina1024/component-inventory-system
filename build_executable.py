"""Build a one-file desktop executable without bundling runtime data.

Usage:
    python -m pip install -r build-requirements.txt
    python build_executable.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OPTIONAL_MODULES = (
    "PyQt5", "PyQt6", "PySide2", "matplotlib", "scipy", "pytest",
    "IPython", "dask", "distributed", "numba", "notebook", "jupyterlab",
    "bokeh", "h5py", "tables", "sqlalchemy", "botocore", "lxml",
    "pyarrow", "astroid", "sphinx", "black", "qtpy", "panel", "plotly",
    "skimage", "statsmodels", "patsy", "xarray", "sklearn", "intake",
)


def build_command(dist: Path, work: Path, spec: Path) -> list[str]:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "ComponentInventory",
        "--add-data", f"{ROOT / 'theme_assets'}{os.pathsep}theme_assets",
        "--hidden-import", "openpyxl",
        "--hidden-import", "xlrd",
        "--hidden-import", "PySide6.QtSvg",
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(spec),
        str(ROOT / "main.py"),
    ]
    for module in OPTIONAL_MODULES:
        command[4:4] = ["--exclude-module", module]
    return command


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="打包物料库存桌面程序")
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build")
    parser.add_argument("--spec-dir", type=Path, default=ROOT / "build")
    parser.add_argument("--dry-run", action="store_true", help="仅显示打包命令")
    args = parser.parse_args(argv)
    command = build_command(args.dist_dir.resolve(), args.work_dir.resolve(),
                            args.spec_dir.resolve())
    if args.dry_run:
        print(subprocess.list2cmdline(command))
        return 0
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode == 0:
        suffix = ".exe" if os.name == "nt" else ""
        print(f"已生成：{args.dist_dir.resolve() / ('ComponentInventory' + suffix)}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
