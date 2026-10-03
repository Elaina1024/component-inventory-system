"""User-visible scenarios driven through Qt controls, without calling app handlers.

Only the test fixture creates a temporary database. Assertions read controls,
dialog messages, exported files, and the data shown on other application tabs.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QTableWidget,
)

import database
from tests.demo_fixtures import seed_test_data
from main import MainWindow
from theme_manager import ThemePreferences


class TestBlackBoxJourneys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_db_path = database.DB_PATH
        database.DatabaseManager().close()
        self.db = database.init_database(os.path.join(self.tmp.name, "blackbox.db"))
        seed_test_data(self.db)
        self.window = MainWindow(self.db, ThemePreferences(mode="light"))
        self.window.show()
        self.app.processEvents()
        self.tabs = self.window.findChild(QTabWidget)

    def tearDown(self):
        # Avoid the normal close event, which creates an application backup.
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.db.close()
        database.DB_PATH = self.previous_db_path
        self.tmp.cleanup()

    def page(self, title):
        indices = [i for i in range(self.tabs.count()) if title in self.tabs.tabText(i)]
        self.assertEqual(len(indices), 1, f"找不到页面: {title}")
        index = indices[0]
        QTest.mouseClick(self.tabs.tabBar(), Qt.LeftButton,
                         pos=self.tabs.tabBar().tabRect(index).center())
        self.app.processEvents()
        self.assertEqual(self.tabs.currentIndex(), index)
        return self.tabs.widget(index)

    def button(self, scope, text):
        buttons = scope.findChildren(QPushButton)
        matches = [button for button in buttons if button.text() == text]
        if not matches:
            matches = [button for button in buttons if text in button.text()]
        self.assertEqual(len(matches), 1, f"按钮不唯一或不存在: {text}")
        return matches[0]

    def input(self, scope, placeholder):
        matches = [field for field in scope.findChildren(QLineEdit)
                   if placeholder in field.placeholderText()]
        self.assertEqual(len(matches), 1, f"输入框不唯一或不存在: {placeholder}")
        return matches[0]

    def table(self, scope, first_header, second_header=None, distinguishing=None):
        matches = []
        for table in scope.findChildren(QTableWidget):
            if not table.horizontalHeaderItem(0):
                continue
            if table.horizontalHeaderItem(0).text() != first_header:
                continue
            if second_header and table.horizontalHeaderItem(1).text() != second_header:
                continue
            if distinguishing:
                column, label = distinguishing
                if table.horizontalHeaderItem(column).text() != label:
                    continue
            matches.append(table)
        self.assertEqual(len(matches), 1, f"表格不唯一或不存在: {first_header}")
        return matches[0]

    def material_search(self, page, text):
        self.input(page, "搜索").setText(text)
        QTest.qWait(260)  # the visible search box debounces input for 200 ms
        self.app.processEvents()

    def form_field(self, dialog, label_text):
        for form in dialog.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                label = form.itemAt(row, QFormLayout.LabelRole)
                if label and label.widget() and label.widget().text() == label_text:
                    field = form.itemAt(row, QFormLayout.FieldRole)
                    return field.widget() if field else None
        self.fail(f"表单字段不存在: {label_text}")

    def test_navigation_and_dashboard_show_initial_data(self):
        self.assertEqual(self.tabs.count(), 6)
        dashboard = self.page("数据看板")
        self.assertGreaterEqual(len(dashboard.findChildren(QGroupBox)), 1)
        for title, header in [
            ("物料管理", ""), ("BOM 导入与核销", "料号"),
            ("BOM 管理", "内部料号"), ("计划外领料", "内部料号"),
            ("出入库日志", "流水号"),
        ]:
            page = self.page(title)
            if title == "BOM 导入与核销":
                self.assertIsNotNone(self.table(page, header,
                                                 distinguishing=(4, "单份用量")))
            else:
                self.assertIsNotNone(self.table(page, header))

    def test_material_search_sort_and_select_all(self):
        page = self.page("物料管理")
        table = self.table(page, "")
        self.assertEqual(table.rowCount(), 15)
        self.material_search(page, "RES-202405-000001")
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 1).text(), "RES-202405-000001")
        self.button(page, "清除").click()
        self.assertEqual(table.rowCount(), 15)

        self.button(page, "☑ 全选").click()
        self.assertTrue(all(table.item(row, 0).checkState() == Qt.Checked
                            for row in range(table.rowCount())))
        self.button(page, "☐ 取消全选").click()
        self.assertTrue(all(table.item(row, 0).checkState() == Qt.Unchecked
                            for row in range(table.rowCount())))
        header = table.horizontalHeader()
        column = 1
        point = QPoint(header.sectionViewportPosition(column) + header.sectionSize(column) // 2,
                       header.height() // 2)
        before = [table.item(row, column).text() for row in range(table.rowCount())]
        QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=point)
        self.app.processEvents()
        after = [table.item(row, column).text() for row in range(table.rowCount())]
        self.assertEqual(after, list(reversed(before)))

    def test_add_material_dialog_validates_then_displays_new_row(self):
        page = self.page("物料管理")
        problems = []

        def fill_dialog():
            dialog = QApplication.activeModalWidget()
            try:
                self.assertEqual(dialog.windowTitle(), "新增物料")
                buttons = dialog.findChild(QDialogButtonBox)
                QTest.mouseClick(buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
                category = self.form_field(dialog, "物料类别 *:")
                category.setCurrentText("电阻")
                self.form_field(dialog, "名称 *:").setText("黑盒测试电阻")
                self.form_field(dialog, "库存数量:").setValue(7)
                QTest.mouseClick(buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
            except Exception as exc:
                problems.append(exc)
                dialog.reject()

        QTimer.singleShot(0, fill_dialog)
        with patch.object(QMessageBox, "warning") as warning, \
             patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            QTest.mouseClick(self.button(page, "新增物料"), Qt.LeftButton)
        self.assertEqual(problems, [])
        warning.assert_called_once()
        self.material_search(page, "黑盒测试电阻")
        table = self.table(page, "")
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 2).text(), "黑盒测试电阻")
        self.assertEqual(int(table.item(0, 6).text()), 7)

    def test_stock_adjustment_dialog_updates_stock_and_audit_log(self):
        page = self.page("物料管理")
        self.material_search(page, "RES-202405-000001")
        table = self.table(page, "")
        table.selectRow(0)
        problems = []

        def fill_dialog():
            dialog = QApplication.activeModalWidget()
            try:
                self.assertEqual(dialog.windowTitle(), "库存手动修复")
                buttons = dialog.findChild(QDialogButtonBox)
                QTest.mouseClick(buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
                self.form_field(dialog, "调整数量 (±):").setValue(2)
                self.form_field(dialog, "调整原因 *:").setText("黑盒盘点")
                QTest.mouseClick(buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
            except Exception as exc:
                problems.append(exc)
                dialog.reject()

        QTimer.singleShot(0, fill_dialog)
        with patch.object(QMessageBox, "warning") as warning, \
             patch.object(QMessageBox, "information"):
            QTest.mouseClick(self.button(page, "🔧 库存修正"), Qt.LeftButton)
        self.assertEqual(problems, [])
        warning.assert_called_once()
        self.assertEqual(int(table.item(0, 6).text()), 2002)
        log_page = self.page("出入库日志")
        log = self.table(log_page, "流水号")
        self.assertTrue(any(log.item(row, 3).text() == "ADJUSTMENT" and
                            log.item(row, 4).text() == "+2"
                            for row in range(log.rowCount())))

    def test_qr_preview_contains_image(self):
        page = self.page("物料管理")
        self.material_search(page, "RES-202405-000001")
        self.table(page, "").selectRow(0)
        problems = []

        def inspect_preview():
            dialog = QApplication.activeModalWidget()
            try:
                self.assertIn("二维码标签", dialog.windowTitle())
                self.assertTrue(any(label.pixmap() and not label.pixmap().isNull()
                                    for label in dialog.findChildren(QLabel)))
                QTest.keyClick(dialog, Qt.Key_Escape)
            except Exception as exc:
                problems.append(exc)
                dialog.reject()

        QTimer.singleShot(0, inspect_preview)
        QTest.mouseClick(self.button(page, "生成二维码标签"), Qt.LeftButton)
        self.assertEqual(problems, [])

    def test_fast_issue_requires_reason_and_updates_material_and_log(self):
        page = self.page("计划外领料")
        self.input(page, "输入料号").setText("RES-202405-000001")
        combo = next(box for box in page.findChildren(QComboBox)
                     if box.count() and "RES-202405-000001" in box.itemText(0))
        self.assertIn("可用:2000", combo.currentText())
        QTest.mouseClick(self.button(page, "5"), Qt.LeftButton)
        reason = self.input(page, "请输入领用原因")
        with patch.object(QMessageBox, "warning") as warning:
            QTest.mouseClick(self.button(page, "确认领料"), Qt.LeftButton)
        warning.assert_called_once()
        reason.setText("黑盒测试领用")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
             patch.object(QMessageBox, "information"):
            QTest.mouseClick(self.button(page, "确认领料"), Qt.LeftButton)
        recent = self.table(page, "流水号")
        self.assertTrue(any(recent.item(row, 1).text() == "RES-202405-000001" and
                            recent.item(row, 3).text() == "-5"
                            for row in range(recent.rowCount())))
        parts = self.page("物料管理")
        self.material_search(parts, "RES-202405-000001")
        self.assertEqual(int(self.table(parts, "").item(0, 6).text()), 1995)

    def test_batch_cart_add_and_submit_two_materials(self):
        page = self.page("计划外领料")
        mode = next(box for box in page.findChildren(QCheckBox) if "批量领料模式" in box.text())
        QTest.mouseClick(mode, Qt.LeftButton)
        self.assertTrue(mode.isChecked())
        search = self.input(page, "输入料号")
        reason = self.input(page, "请输入领用原因")
        for part_number in ("RES-202405-000001", "RES-202405-000002"):
            search.setText(part_number)
            self.button(page, "5").click()
            reason.setText("批量测试")
            QTest.mouseClick(self.button(page, "添加到待领列表"), Qt.LeftButton)
        cart = self.table(page, "内部料号", "名称")
        self.assertEqual(cart.rowCount(), 2)
        self.assertEqual({cart.item(row, 0).text() for row in range(2)},
                         {"RES-202405-000001", "RES-202405-000002"})
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
             patch.object(QMessageBox, "information"):
            QTest.mouseClick(self.button(page, "一键提交全部"), Qt.LeftButton)
        self.assertEqual(cart.rowCount(), 0)
        recent = self.table(page, "流水号")
        self.assertEqual(recent.rowCount(), 2)

    def test_bom_library_lock_and_cancel_order(self):
        page = self.page("BOM 导入与核销")
        library = next(box for box in page.findChildren(QComboBox)
                       if box.count() and "BOM库快捷选择" in box.itemText(0))
        library.setCurrentIndex(1)
        self.app.processEvents()
        preview = self.table(page, "料号", distinguishing=(4, "单份用量"))
        self.assertEqual(preview.rowCount(), 9)
        lock = self.button(page, "锁定库存")
        self.assertTrue(lock.isEnabled())
        with patch.object(QMessageBox, "question", side_effect=[QMessageBox.Yes, QMessageBox.No]), \
             patch.object(QMessageBox, "information"):
            QTest.mouseClick(lock, Qt.LeftButton)
        orders = self.table(page, "工单号")
        self.assertEqual(orders.rowCount(), 1)
        self.assertIn("LOCKED", orders.item(0, 4).text())
        orders.selectRow(0)
        self.app.processEvents()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            QTest.mouseClick(self.button(page, "取消工单"), Qt.LeftButton)
        status = next(box for box in page.findChildren(QComboBox)
                      if box.findText("已取消 (CANCELLED)") >= 0)
        status.setCurrentText("已取消 (CANCELLED)")
        self.assertEqual(orders.rowCount(), 1)
        self.assertIn("CANCELLED", orders.item(0, 4).text())
        parts = self.page("物料管理")
        self.material_search(parts, "MCU-202405-000001")
        self.assertEqual(int(self.table(parts, "").item(0, 7).text()), 0)

    def test_bom_library_lock_then_complete_order(self):
        page = self.page("BOM 导入与核销")
        library = next(box for box in page.findChildren(QComboBox)
                       if box.count() and "BOM库快捷选择" in box.itemText(0))
        library.setCurrentIndex(1)
        with patch.object(QMessageBox, "question", side_effect=[QMessageBox.Yes, QMessageBox.No]), \
             patch.object(QMessageBox, "information"):
            QTest.mouseClick(self.button(page, "锁定库存"), Qt.LeftButton)
        orders = self.table(page, "工单号")
        orders.selectRow(0)
        self.app.processEvents()
        self.assertTrue(self.button(page, "确认核销").isEnabled())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
             patch.object(QMessageBox, "information"):
            QTest.mouseClick(self.button(page, "确认核销"), Qt.LeftButton)
        status = next(box for box in page.findChildren(QComboBox)
                      if box.findText("已完成 (COMPLETED)") >= 0)
        status.setCurrentText("已完成 (COMPLETED)")
        self.assertEqual(orders.rowCount(), 1)
        self.assertIn("COMPLETED", orders.item(0, 4).text())
        parts = self.page("物料管理")
        self.material_search(parts, "MCU-202405-000001")
        row = self.table(parts, "")
        self.assertEqual(int(row.item(0, 6).text()), 49)
        self.assertEqual(int(row.item(0, 7).text()), 0)

    def test_bom_library_can_export_excel(self):
        page = self.page("BOM 管理")
        listing = page.findChild(QListWidget)
        listing.setCurrentRow(0)
        self.app.processEvents()
        table = self.table(page, "内部料号", "物料名称")
        self.assertEqual(table.rowCount(), 9)
        export = Path(self.tmp.name, "exported-bom.xlsx")
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(export), "Excel")), \
             patch.object(QMessageBox, "information"):
            QTest.mouseClick(self.button(page, "导出为 Excel"), Qt.LeftButton)
        self.assertTrue(export.is_file())
        self.assertEqual(len(pd.read_excel(export)), 9)

    def test_log_filters_and_reset(self):
        page = self.page("出入库日志")
        table = self.table(page, "流水号")
        self.assertEqual(table.rowCount(), 15)
        self.input(page, "模糊搜索").setText("MCU-202405-000001")
        QTest.mouseClick(self.button(page, "搜索"), Qt.LeftButton)
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 1).text(), "MCU-202405-000001")
        kinds = next(box for box in page.findChildren(QComboBox)
                     if box.findText("AD_HOC") >= 0)
        kinds.setCurrentText("AD_HOC")
        QTest.mouseClick(self.button(page, "搜索"), Qt.LeftButton)
        self.assertEqual(table.rowCount(), 0)
        QTest.mouseClick(self.button(page, "重置"), Qt.LeftButton)
        self.assertEqual(table.rowCount(), 15)

    def test_appearance_dialog_offers_both_modes_without_saving(self):
        problems = []
        before = self.app.palette().color(QPalette.Window).name()

        def inspect_dialog():
            dialog = QApplication.activeModalWidget()
            try:
                self.assertEqual(dialog.windowTitle(), "界面外观")
                modes = next(box for box in dialog.findChildren(QComboBox)
                             if box.findText("亮色模式") >= 0)
                self.assertGreaterEqual(modes.findText("暗色模式"), 0)
                modes.setCurrentText("暗色模式")
                self.assertTrue(any("外观预览" in label.text()
                                    for label in dialog.findChildren(QLabel)))
                QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel),
                                 Qt.LeftButton)
            except Exception as exc:
                problems.append(exc)
                dialog.reject()

        QTimer.singleShot(0, inspect_dialog)
        QTest.mouseClick(self.button(self.window, "外观设置"), Qt.LeftButton)
        self.assertEqual(problems, [])
        self.assertEqual(self.app.palette().color(QPalette.Window).name(), before)


if __name__ == "__main__":
    unittest.main()
