"""Run isolated white-box tests and write a machine-readable result report.

Usage:
    python run_whitebox_tests.py
    python run_whitebox_tests.py --module core
    python run_whitebox_tests.py --module ui --report custom-report.json
"""

import argparse
import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
TEST_MODULES = {
    "core": "tests.test_core",
    "ui": "tests.test_ui",
}


def _test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _test_ids(item)
        else:
            yield item.id()


def main(argv=None):
    parser = argparse.ArgumentParser(description="库存管理系统白盒测试")
    parser.add_argument("--module", choices=("all", *TEST_MODULES), default="all",
                        help="仅运行指定测试模块（默认 all）")
    parser.add_argument("--report", type=Path,
                        default=PROJECT_DIR / "test_reports" / "latest.json",
                        help="JSON 测试报告路径")
    args = parser.parse_args(argv)

    # The GUI tests render in memory and never need a real desktop window.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.chdir(PROJECT_DIR)
    sys.path.insert(0, str(PROJECT_DIR))

    loader = unittest.TestLoader()
    selected = TEST_MODULES if args.module == "all" else {args.module: TEST_MODULES[args.module]}
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in selected.values())
    test_ids = list(_test_ids(suite))
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)

    failures = [{"test": case.id(), "traceback": detail} for case, detail in result.failures]
    errors = [{"test": case.id(), "traceback": detail} for case, detail in result.errors]
    skipped = [{"test": case.id(), "reason": reason} for case, reason in result.skipped]
    not_passed = {entry["test"] for entry in failures + errors + skipped}
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": args.module,
        "tests_run": result.testsRun,
        "passed": sum(test_id not in not_passed for test_id in test_ids),
        "failed": len(failures),
        "errors": len(errors),
        "skipped": len(skipped),
        "successful_tests": [test_id for test_id in test_ids if test_id not in not_passed],
        "failures": failures,
        "error_details": errors,
        "skipped_details": skipped,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n测试报告: {args.report.resolve()}")
    print(f"通过 {report['passed']} / {result.testsRun}；失败 {report['failed']}；错误 {report['errors']}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
