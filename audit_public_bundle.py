"""Fail closed if the upload folder gains files or identifiers not reviewed."""

import re
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parent
APPROVED_FILES = {
    ".gitignore", "README.md", "PRIVACY.md", "GITHUB_UPLOAD_GUIDE.md",
    "requirements.txt", "build-requirements.txt", "PACKAGING.md",
    "build_executable.py", "app_paths.py", "audit_public_bundle.py", "example_bom.xlsx",
    "main.py", "database.py", "bom_parser.py", "backup.py", "dashboard.py",
    "qr_label.py", "theme_manager.py", "ui_theme.py", "generate_example_bom.py",
    "run_whitebox_tests.py", "run_blackbox_tests.py",
    "WHITEBOX_TESTING.md", "BLACKBOX_TESTING.md",
    "tests/__init__.py", "tests/demo_fixtures.py", "tests/test_core.py", "tests/test_ui.py",
    "tests/test_blackbox.py",
    "theme_assets/arrow_up_light.svg", "theme_assets/arrow_up_dark.svg",
    "theme_assets/arrow_down_light.svg", "theme_assets/arrow_down_dark.svg",
}

TEXT_SUFFIXES = {".py", ".md", ".txt", ".svg"}
PATTERNS = {
    "个人目录路径": re.compile(r"(?i)\b[A-Z]:[/\\](?:Users|Documents and Settings)[/\\][^/\\\s]+|" + "/" + r"home/[^/\s]+"),
    "本机绝对路径": re.compile(r"(?i)\b[A-Z]:[/\\](?!Windows[/\\]Fonts)[^\s`\"']+"),
    "电子邮箱": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "疑似凭据赋值": re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]{8,}"),
}


def scan_text(label, value, issues):
    for name, pattern in PATTERNS.items():
        if pattern.search(value):
            issues.append(f"{label}: 发现{name}")
    private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"
    if private_key_marker in value:
        issues.append(f"{label}: 发现私钥标记")


def main():
    issues = []
    actual = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*")
              if path.is_file() and ".git" not in path.relative_to(ROOT).parts}
    for name in sorted(actual - APPROVED_FILES):
        issues.append(f"未审核文件: {name}")
    for name in sorted(APPROVED_FILES - actual):
        issues.append(f"缺少预期文件: {name}")

    for name in sorted(actual & APPROVED_FILES):
        path = ROOT / name
        if path.suffix in TEXT_SUFFIXES or path.name == ".gitignore":
            try:
                scan_text(name, path.read_text(encoding="utf-8"), issues)
            except UnicodeDecodeError:
                issues.append(f"{name}: 不是 UTF-8 文本")

    example = ROOT / "example_bom.xlsx"
    if example.is_file():
        try:
            workbook = load_workbook(example, read_only=True, data_only=True)
            if workbook.properties.creator != "Inventory System Demo":
                issues.append("示例 BOM 的作者元数据不是匿名演示值")
            if workbook.properties.lastModifiedBy != "Inventory System Demo":
                issues.append("示例 BOM 的修改者元数据不是匿名演示值")
            for sheet in workbook:
                for row in sheet.values:
                    for value in row:
                        if isinstance(value, str):
                            scan_text("example_bom.xlsx 单元格", value, issues)
            workbook.close()
            with ZipFile(example) as archive:
                if any("externalLinks" in name for name in archive.namelist()):
                    issues.append("示例 BOM 含外部链接")
        except Exception as exc:
            issues.append(f"示例 BOM 无法解析: {exc}")

    if issues:
        print("公开目录审核未通过：")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print(f"公开目录审核通过：{len(APPROVED_FILES)} 个已审文件；未发现个人路径、邮箱或凭据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
