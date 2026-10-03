"""Offscreen Qt tests for the main functional tabs and their internal branches."""

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import database
from tests.demo_fixtures import seed_test_data
from main import MainWindow
from qr_label import generate_label, label_to_pixmap
from theme_manager import ThemePreferences


class TestMainWindowWorkflows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_db_path = database.DB_PATH
        database.DatabaseManager().close()
        self.db = database.init_database(os.path.join(self.tmp.name, "ui-test.db"))
        seed_test_data(self.db)
        self.window = MainWindow(self.db, ThemePreferences(mode="dark"))
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        # MainWindow.closeEvent creates a real backup, so hide and close the
        # temporary database directly. Never open the project's inventory.db.
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.db.close()
        database.DB_PATH = self.previous_db_path
        self.tmp.cleanup()

    def _part(self, number="RES-202405-000001"):
        return self.db.fetch_one("SELECT * FROM parts WHERE part_number = ?", (number,))

    def _load_single_bom(self, quantity=2, planned=3):
        tab = self.window.bom_tab
        tab.current_bom_df = pd.DataFrame({
            "part_number": ["RES-202405-000001"],
            "name": ["电阻"], "quantity": [quantity],
        })
        tab.current_bom_name = "白盒测试 BOM"
        tab.current_bom_path = None
        tab.spin_planned_qty.setValue(planned)
        return tab

    def _create_order(self):
        tab = self._load_single_bom()
        with patch.object(QMessageBox, "question", side_effect=[QMessageBox.Yes, QMessageBox.No]), \
             patch.object(QMessageBox, "information"):
            tab.on_lock_stock()
        order = self.db.fetch_one("SELECT * FROM work_orders ORDER BY id DESC LIMIT 1")
        self.assertIsNotNone(order)
        return tab, order

    def test_all_tabs_load_and_refresh_from_temporary_data(self):
        self.assertEqual(self.window.tabs.count(), 6)
        self.assertEqual(self.window.parts_tab.table.rowCount(), 15)
        self.assertGreater(self.window.bom_manage_tab.bom_list.count(), 0)
        self.assertGreater(self.window.log_tab.table.rowCount(), 0)
        self.window.refresh_all_tabs()
        self.assertEqual(self.window.parts_tab.table.rowCount(), 15)
        pixmap = label_to_pixmap(generate_label(dict(self._part())))
        self.assertFalse(pixmap.isNull())

    def test_parts_search_and_bom_editor_persist_changes(self):
        parts_tab = self.window.parts_tab
        parts_tab.search_input.setText("RES-202405-000001")
        parts_tab.on_search()
        self.assertEqual(parts_tab.table.rowCount(), 1)
        parts_tab.clear_search()
        self.assertEqual(parts_tab.table.rowCount(), 15)

        bom_tab = self.window.bom_manage_tab
        bom_tab.bom_list.setCurrentRow(0)
        self.assertGreater(bom_tab.items_table.rowCount(), 0)
        first_part = bom_tab.items_table.item(0, 0).text()
        bom_tab.items_table.item(0, 2).setData(Qt.EditRole, 7)
        self.assertTrue(bom_tab._is_dirty)
        with patch.object(QMessageBox, "information"):
            bom_tab.on_save_bom()
        row = self.db.fetch_one("SELECT qty_per_unit FROM bom_items WHERE bom_name = ? "
                                "AND part_number = ?", (bom_tab.current_bom_name, first_part))
        self.assertEqual(row["qty_per_unit"], 7)
        self.assertFalse(bom_tab._is_dirty)

    def test_parts_header_and_row_checkboxes_share_behavior(self):
        self.window.tabs.setCurrentWidget(self.window.parts_tab)
        self.app.processEvents()
        tab = self.window.parts_tab
        table = tab.table
        header = table.horizontalHeader()
        count = table.rowCount()
        header_point = QPoint(header.sectionViewportPosition(0) + header.sectionSize(0) // 2,
                              header.height() // 2)
        QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=header_point)
        self.app.processEvents()
        self.assertEqual(tab._get_checked_count(), count)
        self.assertTrue(header._all_checked)
        QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=header_point)
        self.app.processEvents()
        self.assertEqual(tab._get_checked_count(), 0)
        row_point = QPoint(table.columnViewportPosition(0) + table.columnWidth(0) // 2,
                           table.rowViewportPosition(0) + table.rowHeight(0) // 2)
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=row_point)
        self.app.processEvents()
        self.assertEqual(tab._get_checked_count(), 1)
        self.assertEqual(table.item(0, 0).checkState(), Qt.Checked)
        self.assertEqual(header.sortIndicatorSection(), 1)

    def test_planless_issue_requires_remark_then_writes_stock_and_log(self):
        tab = self.window.adhoc_tab
        part = self._part()
        tab._on_autocomplete_selected(dict(part))
        tab.spin_qty.setValue(3)
        with patch.object(QMessageBox, "warning") as warning:
            tab.on_issue()
        warning.assert_called_once()
        self.assertEqual(self._part()["stock_qty"], part["stock_qty"])
        tab.edit_remark.setText("测试领料")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
             patch.object(QMessageBox, "information"):
            tab.on_issue()
        self.assertEqual(self._part()["stock_qty"], part["stock_qty"] - 3)
        log = self.db.fetch_one("SELECT * FROM inventory_transactions WHERE part_id = ? "
                                "AND transaction_type = 'AD_HOC' ORDER BY id DESC LIMIT 1",
                                (part["id"],))
        self.assertEqual(log["quantity"], -3)
        self.assertIn("测试领料", log["remark"])

    def test_bom_shortage_blocks_order_creation(self):
        part = self._part()
        tab = self._load_single_bom(quantity=part["stock_qty"] + 1, planned=1)
        with patch.object(QMessageBox, "warning") as warning:
            tab.on_lock_stock()
        warning.assert_called_once()
        self.assertIsNone(self.db.fetch_one("SELECT id FROM work_orders LIMIT 1"))
        self.assertEqual(self._part()["locked_qty"], 0)

    def test_bom_lock_then_cancel_releases_inventory(self):
        tab, order = self._create_order()
        self.assertEqual(order["status"], "LOCKED")
        self.assertEqual(self._part()["locked_qty"], 6)
        tab.current_order_id = order["id"]
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            tab.on_cancel_order()
        self.assertEqual(self._part()["locked_qty"], 0)
        self.assertEqual(tab.wo_repo.get_by_id(order["id"])["status"], "CANCELLED")
        events = self.db.fetch_all("SELECT transaction_type FROM inventory_transactions "
                                   "WHERE work_order_id = ?", (order["id"],))
        self.assertEqual([row["transaction_type"] for row in events],
                         ["WO_LOCK", "WO_RETURN"])

    def test_bom_writeoff_consumes_only_actual_and_returns_remainder(self):
        tab, order = self._create_order()
        tab.refresh_order_list()
        for row in range(tab.order_table.rowCount()):
            if tab.order_table.item(row, 0).data(Qt.UserRole) == order["id"]:
                tab.order_table.selectRow(row)
                break
        tab.on_order_selected()
        self.assertEqual(tab.current_order_id, order["id"])
        item = tab.wo_repo.get_items(order["id"])[0]
        row = tab._order_item_row(item["id"])
        tab.order_items_table.item(row, 5).setText("4")
        tab.spin_actual_qty.setValue(2)
        initial_stock = self._part()["stock_qty"]
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
             patch.object(QMessageBox, "information"):
            tab.on_confirm_writeoff()
        self.assertEqual(tab.wo_repo.get_by_id(order["id"])["status"], "COMPLETED")
        self.assertEqual((self._part()["stock_qty"], self._part()["locked_qty"]),
                         (initial_stock - 4, 0))
        finished_item = tab.wo_repo.get_items(order["id"])[0]
        self.assertEqual((finished_item["actual_consumed_qty"], finished_item["returned_qty"]),
                         (4, 2))

    def test_bom_writeoff_rejects_consumption_above_locked_quantity(self):
        tab, order = self._create_order()
        tab.refresh_order_list()
        for row in range(tab.order_table.rowCount()):
            if tab.order_table.item(row, 0).data(Qt.UserRole) == order["id"]:
                tab.order_table.selectRow(row)
                break
        tab.on_order_selected()
        item = tab.wo_repo.get_items(order["id"])[0]
        tab.order_items_table.item(tab._order_item_row(item["id"]), 5).setText("7")
        initial_stock = self._part()["stock_qty"]
        with patch.object(QMessageBox, "warning") as warning:
            tab.on_confirm_writeoff()
        warning.assert_called_once()
        self.assertEqual(tab.wo_repo.get_by_id(order["id"])["status"], "LOCKED")
        self.assertEqual((self._part()["stock_qty"], self._part()["locked_qty"]),
                         (initial_stock, 6))

    def test_batch_cart_rechecks_stock_before_submission(self):
        tab = self.window.adhoc_tab
        part = self._part()
        tab._cart_items = [{"part_id": part["id"], "part_number": part["part_number"],
                            "name": part["name"], "qty": 5, "available": part["stock_qty"],
                            "remark": "测试批量领料"}]
        tab.part_repo.lock_stock(part["id"], part["stock_qty"] - 4)
        with patch.object(QMessageBox, "warning") as warning:
            tab._submit_cart()
        warning.assert_called_once()
        self.assertEqual(self._part()["stock_qty"], part["stock_qty"])
        self.assertEqual(len(tab._cart_items), 1)
        tab.part_repo.return_stock(part["id"], part["stock_qty"] - 4)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
             patch.object(QMessageBox, "information"):
            tab._submit_cart()
        self.assertEqual(self._part()["stock_qty"], part["stock_qty"] - 5)
        self.assertEqual(tab._cart_items, [])


if __name__ == "__main__":
    unittest.main()
