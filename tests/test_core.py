"""Business-rule tests. Every database mutation uses a temporary SQLite file."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

import pandas as pd
from PySide6.QtCore import QSettings

import backup
import app_paths
import database
from tests.demo_fixtures import seed_test_data
from bom_parser import calculate_demand, check_shortage, parse_bom, validate_bom
from qr_label import LABEL_HEIGHT, LABEL_WIDTH, build_part_info_json, generate_label, generate_qr_image
from theme_manager import ThemeManager, ThemePreferences


class TemporaryDatabaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_db_path = database.DB_PATH
        database.DatabaseManager().close()
        self.db_path = os.path.join(self.tmp.name, "inventory-test.db")
        self.db = database.init_database(self.db_path)
        seed_test_data(self.db)
        self.parts = database.PartRepository(self.db)
        self.orders = database.WorkOrderRepository(self.db)
        self.transactions = database.TransactionRepository(self.db)
        self.boms = database.BomRepository(self.db)
        self.suppliers = database.SupplierRepository(self.db)

    def tearDown(self):
        self.db.close()
        database.DB_PATH = self.previous_db_path
        self.tmp.cleanup()

    def part(self, number="RES-202405-000001"):
        return self.db.fetch_one("SELECT * FROM parts WHERE part_number = ?", (number,))


class TestFreshDatabase(unittest.TestCase):
    def test_new_database_has_empty_business_tables_and_keeps_existing_records(self):
        with tempfile.TemporaryDirectory() as root:
            previous_path = database.DB_PATH
            database.DatabaseManager().close()
            try:
                path = os.path.join(root, "fresh.db")
                db = database.init_database(path)
                for table in (
                    "suppliers", "parts", "work_orders", "work_order_items",
                    "inventory_transactions", "bom_items",
                ):
                    self.assertEqual(db.fetch_one(f"SELECT COUNT(*) AS n FROM {table}")["n"], 0)
                db.execute("INSERT INTO suppliers (name) VALUES (?)", ("已有记录",))
                db.close()

                reopened = database.init_database(path)
                self.assertEqual(reopened.fetch_one("SELECT COUNT(*) AS n FROM suppliers")["n"], 1)
                self.assertEqual(reopened.fetch_one("SELECT COUNT(*) AS n FROM bom_items")["n"], 0)
            finally:
                database.DatabaseManager().close()
                database.DB_PATH = previous_path


class TestDatabaseRules(TemporaryDatabaseCase):
    def test_stock_lock_issue_consume_and_audit(self):
        part = self.part()
        original = part["stock_qty"]
        self.parts.lock_stock(part["id"], 100)
        self.assertEqual(self.parts.get_by_id(part["id"])["available_qty"], original - 100)
        with self.assertRaisesRegex(ValueError, "可用库存不足"):
            self.parts.adhoc_issue(part["id"], original - 99)
        self.assertEqual(self.part()["stock_qty"], original)
        self.parts.adhoc_issue(part["id"], 50)
        self.parts.consume_stock(part["id"], 30, 100)
        self.parts.return_stock(part["id"], 1)  # no locked stock remains
        self.assertEqual((self.part()["stock_qty"], self.part()["locked_qty"]),
                         (original - 80, 0))
        tid = self.transactions.insert(part["id"], "AD_HOC", -50, remark="test")
        self.assertEqual(self.transactions.get_by_id(tid)["part_number"], part["part_number"])
        self.assertEqual(len(self.transactions.get_all(trans_type="AD_HOC")), 1)

    def test_batch_allowlist_and_locked_delete_branch(self):
        first, second = self.part(), self.part("RES-202405-000002")
        self.parts.lock_stock(first["id"], 2)
        changed = self.parts.batch_update(
            [first["id"], second["id"]], location="TEST-A", name="must not change"
        )
        self.assertEqual(changed, 2)
        self.assertEqual(self.part()["location"], "TEST-A")
        self.assertEqual(self.part()["name"], first["name"])
        self.assertEqual(self.parts.batch_update([], location="X"), 0)
        deleted, skipped = self.parts.batch_delete([first["id"], second["id"]])
        self.assertEqual(deleted, 1)
        self.assertEqual(skipped, [first["part_number"]])
        self.assertIsNotNone(self.parts.get_by_id(first["id"]))
        self.assertIsNone(self.parts.get_by_id(second["id"]))

    def test_supplier_bom_and_work_order_repositories(self):
        supplier_id = self.suppliers.insert("测试供应商", phone="123")
        part = self.part()
        self.parts.update(part["id"], supplier_id=supplier_id)
        self.assertEqual(self.parts.get_by_id(part["id"])["supplier_name"], "测试供应商")
        self.assertFalse(self.suppliers.delete(supplier_id))

        bom_id = self.boms.insert_item("测试BOM", part["part_number"], 2, "old")
        self.boms.update_item(bom_id, 3, "new")
        self.assertEqual(self.boms.count_items("测试BOM"), 1)
        self.assertEqual(self.boms.to_dataframe("测试BOM").iloc[0]["单份用量"], 3)
        export_path = os.path.join(self.tmp.name, "bom.xlsx")
        self.assertEqual(self.boms.export_to_excel("测试BOM", export_path), 1)
        self.assertEqual(pd.read_excel(export_path).iloc[0]["单份用量"], 3)
        self.boms.rename_bom("测试BOM", "新BOM")
        self.assertEqual(self.boms.count_items("新BOM"), 1)

        order_id = self.orders.insert("WO-TEST-001", "新BOM", 2)
        self.orders.insert_item(order_id, part["id"], 6, 6)
        item = self.orders.get_items(order_id)[0]
        self.orders.update_item_consumption(item["id"], 4, 2)
        self.orders.complete(order_id, 2)
        self.assertEqual(self.orders.get_by_id(order_id)["status"], "COMPLETED")
        self.assertEqual(self.orders.get_items(order_id)[0]["returned_qty"], 2)
        self.assertEqual(len(self.orders.get_all("COMPLETED")), 1)
        self.boms.delete_bom("新BOM")
        self.assertEqual(self.boms.count_items("新BOM"), 0)
        self.parts.update(part["id"], supplier_id=None)
        self.assertTrue(self.suppliers.delete(supplier_id))

    def test_generated_part_number_sequence_and_fallback(self):
        first = database.generate_part_number(self.db, "电阻")
        self.assertRegex(first, r"^RES-\d{6}-000001$")
        self.parts.insert(first, "test", category="电阻")
        second = database.generate_part_number(self.db, "电阻")
        self.assertEqual(int(second[-6:]), 2)
        self.assertRegex(database.generate_part_number(self.db, "xyz-other"),
                         r"^XYZ-\d{6}-000001$")
        self.assertRegex(database.generate_part_number(self.db, "未知"),
                         r"^GEN-\d{6}-000001$")


class TestBomParsing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_excel_aliases_cleaning_and_optional_fields(self):
        path = os.path.join(self.tmp.name, "bom.xlsx")
        pd.DataFrame({"料号": [" P-1 ", "P-2"], "名称": [" 电阻 ", "电容"],
                      "用量": [2.0, 3.0]}).to_excel(path, index=False)
        frame, errors = parse_bom(path)
        self.assertEqual(errors, [])
        self.assertEqual(frame["part_number"].tolist(), ["P-1", "P-2"])
        self.assertEqual(frame["quantity"].tolist(), [2, 3])
        self.assertIn("package", frame.columns)
        self.assertIn("location", frame.columns)

    def test_invalid_files_and_quantities(self):
        missing, errors = parse_bom(os.path.join(self.tmp.name, "missing.xlsx"))
        self.assertIsNone(missing)
        self.assertIn("文件不存在", errors[0])
        unsupported = os.path.join(self.tmp.name, "bom.csv")
        Path(unsupported).write_text("x", encoding="utf-8")
        self.assertIn("不支持", parse_bom(unsupported)[1][0])
        valid, errors = validate_bom(pd.DataFrame({"part_number": ["", "A", "B"],
            "name": ["n", "", "n"], "quantity": [0, 1.5, "bad"]}))
        self.assertFalse(valid)
        self.assertGreaterEqual(len(errors), 4)
        self.assertFalse(validate_bom(pd.DataFrame({"part_number": ["A"]}))[0])
        empty = os.path.join(self.tmp.name, "empty.xlsx")
        pd.DataFrame({"料号": [None], "名称": [None], "用量": [None]}).to_excel(
            empty, index=False)
        self.assertIn("无有效数据", parse_bom(empty)[1][0])

    def test_duplicate_demand_and_missing_or_short_stock(self):
        frame = pd.DataFrame({"part_number": ["A", "A", "B", "C"],
                              "name": ["a", "a", "b", "c"],
                              "quantity": [2, 3, 1, 1]})
        demand = calculate_demand(frame, 4)
        self.assertEqual(demand.loc[demand.part_number == "A", "total_demand"].iloc[0], 20)
        shortage = check_shortage(frame, 4, {
            "A": {"stock_qty": 30, "locked_qty": 15},
            "B": {"stock_qty": 10, "locked_qty": 0},
        })
        self.assertEqual({s["part_number"]: s["shortage"] for s in shortage},
                         {"A": 5, "C": 4})
        self.assertEqual(next(s for s in shortage if s["part_number"] == "C")["reason"],
                         "物料未录入系统")


class TestBackupAndQr(TemporaryDatabaseCase):
    def test_json_backup_and_retention(self):
        target = os.path.join(self.tmp.name, "backups")
        messages = []
        self.assertTrue(backup.execute_backup(self.db_path, target, messages.append))
        file = next(Path(target).glob("backup_*.json"))
        payload = json.loads(file.read_text(encoding="utf-8"))
        self.assertEqual(payload["backup_metadata"]["record_counts"]["parts"], 15)
        self.assertEqual(len(payload["data"]["bom_items"]), 9)
        self.assertTrue(any("备份成功" in message for message in messages))
        old = Path(target, "backup_old.json")
        old.write_text("{}", encoding="utf-8")
        os.utime(old, (1, 1))
        backup.cleanup_old_backups(target, keep_count=1)
        self.assertFalse(old.exists())
        self.assertTrue(file.exists())

    def test_backup_reports_invalid_database_schema(self):
        broken_db = os.path.join(self.tmp.name, "broken.db")
        Path(broken_db).write_bytes(b"not an SQLite database")
        messages = []
        self.assertFalse(backup.execute_backup(
            broken_db, os.path.join(self.tmp.name, "bad-backup"), messages.append))
        self.assertTrue(any("备份错误" in message for message in messages))

    def test_qr_payload_image_and_label(self):
        part = dict(self.part())
        payload = json.loads(build_part_info_json(part))
        self.assertEqual(payload["pn"], part["part_number"])
        self.assertEqual(payload["qty"], part["stock_qty"])
        self.assertEqual(generate_qr_image("test", size=96).size, (96, 96))
        label = generate_label(part)
        self.assertEqual(label.size, (LABEL_WIDTH, LABEL_HEIGHT))
        self.assertEqual(label.mode, "RGB")


class TestThemeSettings(unittest.TestCase):
    def test_independent_modes_and_invalid_color_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            settings = QSettings(os.path.join(root, "theme.ini"), QSettings.IniFormat)
            prefs = ThemePreferences()
            prefs.accent["dark"] = "#ff5522"
            prefs.background["light"] = "#fafafa"
            prefs.accent["light"] = "invalid"
            prefs.mode = "dark"
            ThemeManager.save(prefs, settings)
            restored = ThemeManager.load(settings)
            self.assertEqual(restored.accent["dark"], "#ff5522")
            self.assertEqual(restored.background["light"], "#fafafa")
            self.assertNotEqual(restored.accent["light"], "invalid")
            dark = ThemeManager.colors(restored)
            restored.mode = "light"
            light = ThemeManager.colors(restored)
            self.assertNotEqual(dark["panel"], light["panel"])
            self.assertIn("arrow_up_dark.svg", dark["spin_up_icon"])
            self.assertIn("arrow_up_light.svg", light["spin_up_icon"])


class TestStartupStorage(unittest.TestCase):
    def test_first_run_custom_folder_is_saved_and_reused(self):
        with tempfile.TemporaryDirectory() as root:
            app_dir = Path(root, "app")
            data_dir = Path(root, "data")
            app_dir.mkdir()
            data_dir.mkdir()
            selected = app_paths.database_path_for_startup(
                app_dir, lambda start: str(data_dir))
            self.assertEqual(selected, data_dir / "inventory.db")
            self.assertTrue((app_dir / "config.ini").is_file())
            store = app_paths.config_store(app_dir)
            self.assertEqual(store.value("storage/data_directory"), str(data_dir))
            self.assertEqual(app_paths.database_path_for_startup(
                app_dir, lambda start: self.fail("二次启动不应再询问目录")), selected)

    def test_cancel_defaults_to_executable_folder_and_is_portable(self):
        with tempfile.TemporaryDirectory() as root:
            app_dir = Path(root, "app")
            app_dir.mkdir()
            selected = app_paths.database_path_for_startup(app_dir, lambda start: "")
            self.assertEqual(selected, app_dir / "inventory.db")
            self.assertEqual(app_paths.config_store(app_dir).value("storage/data_directory"), ".")

    def test_missing_previous_folder_does_not_create_empty_local_database(self):
        with tempfile.TemporaryDirectory() as root:
            app_dir = Path(root, "app")
            data_dir = Path(root, "data")
            app_dir.mkdir()
            data_dir.mkdir()
            app_paths.database_path_for_startup(app_dir, lambda start: str(data_dir))
            data_dir.rmdir()
            with self.assertRaises(app_paths.StorageConfigError):
                app_paths.database_path_for_startup(app_dir, lambda start: "")
            self.assertFalse((app_dir / "inventory.db").exists())

    def test_frozen_executable_and_resource_paths_are_separate(self):
        with tempfile.TemporaryDirectory() as root:
            exe = Path(root, "install", "ComponentInventory.exe")
            resources = Path(root, "extracted")
            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "executable", str(exe)), \
                 patch.object(sys, "_MEIPASS", str(resources), create=True):
                self.assertEqual(app_paths.application_directory(), exe.parent.resolve())
                self.assertEqual(app_paths.resource_directory(), resources.resolve())
                self.assertEqual(app_paths.config_path(), exe.parent.resolve() / "config.ini")

    def test_theme_settings_share_config_beside_application(self):
        with tempfile.TemporaryDirectory() as root:
            app_dir = Path(root)
            prefs = ThemePreferences(mode="dark")
            prefs.accent["dark"] = "#778899"
            with patch.object(app_paths, "application_directory", return_value=app_dir):
                ThemeManager.save(prefs)
                loaded = ThemeManager.load()
            self.assertEqual(loaded.mode, "dark")
            self.assertEqual(loaded.accent["dark"], "#778899")
            self.assertTrue((app_dir / "config.ini").is_file())


if __name__ == "__main__":
    unittest.main()
