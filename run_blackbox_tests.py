"""Run user-facing black-box tests in an offscreen Qt window.

Usage: python run_blackbox_tests.py [--report path/to/report.json]
"""

import argparse
import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent


def _test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _test_ids(item)
        else:
            yield item.id()


def main(argv=None):
    parser = argparse.ArgumentParser(description="库存管理系统黑盒测试")
    parser.add_argument("--report", type=Path,
                        default=PROJECT_DIR / "test_reports" / "blackbox_latest.json",
                        help="JSON 测试报告路径")
    args = parser.parse_args(argv)

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.chdir(PROJECT_DIR)
    sys.path.insert(0, str(PROJECT_DIR))

    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_blackbox")
    test_ids = list(_test_ids(suite))
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    failures = [{"test": case.id(), "traceback": detail} for case, detail in result.failures]
    errors = [{"test": case.id(), "traceback": detail} for case, detail in result.errors]
    skipped = [{"test": case.id(), "reason": reason} for case, reason in result.skipped]
    not_passed = {entry["test"] for entry in failures + errors + skipped}
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "test_type": "black_box",
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
