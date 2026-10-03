"""
主程序模块
==========
个人单机版物料库存与 BOM 核销管理系统 — 主入口（电子元件与机械零件）。
基于 PySide6 构建桌面 GUI，包含数据看板、物料管理、BOM 导入与核销、
BOM 管理、计划外领料和出入库日志六个功能选项卡。

运行方式: python main.py
"""

import sys
import os
import database as database_module
from datetime import datetime

# ---- PySide6 导入 ----
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLineEdit, QLabel, QSpinBox, QDoubleSpinBox, QComboBox,
    QTextEdit, QMessageBox, QFileDialog, QDialog,
    QFormLayout, QDialogButtonBox, QDateEdit, QGroupBox,
    QSplitter, QFrame, QAbstractItemView, QCheckBox,
    QListWidget, QListWidgetItem, QCompleter, QMenu,
    QStyleOptionViewItem, QStyledItemDelegate,
)
from PySide6.QtCore import Qt, QDate, Signal, QTimer, QRectF, QEvent
from PySide6.QtGui import (
    QColor, QFont, QBrush, QPixmap, QImage, QCloseEvent,
    QStandardItem, QStandardItemModel, QAction, QPainter, QPainterPath,
    QPalette, QPen,
)

# ---- 自定义模块导入 ----
from database import (
    DatabaseManager, PartRepository, WorkOrderRepository,
    TransactionRepository, BomRepository, SupplierRepository,
    init_database,
    generate_part_number, CATEGORY_PREFIX_MAP,
)
from bom_parser import parse_bom, calculate_demand, check_shortage
from qr_label import generate_label, label_to_pixmap, LABEL_WIDTH, LABEL_HEIGHT
from backup import execute_backup, cleanup_old_backups
from dashboard import DashboardTab
from theme_manager import (
    BackgroundWidget, ThemeManager, ThemePreferences, ThemeSettingsDialog,
)
from app_paths import database_path_for_startup


# ============================================================
# 样式常量
# ============================================================
COLOR_GREEN = QColor(0, 150, 0)      # 入库/正数 绿色
COLOR_RED = QColor(220, 30, 30)      # 出库/负数 红色
COLOR_WARNING = QColor(154, 90, 0)   # 锁定/警告
COLOR_SHORTAGE_BG = QColor(255, 230, 230)  # 缺料行背景色（浅红）
COLOR_LOCKED_ROW = QColor(255, 255, 220)   # 工单已锁定行背景色（浅黄）


def set_semantic_colors(colors: dict):
    """Keep status text and shortage highlights legible in either mode."""
    global COLOR_GREEN, COLOR_RED, COLOR_WARNING, COLOR_SHORTAGE_BG, COLOR_LOCKED_ROW
    COLOR_GREEN = QColor(colors["success"])
    COLOR_RED = QColor(colors["danger"])
    COLOR_WARNING = QColor(colors["warning"])
    COLOR_SHORTAGE_BG = QColor(colors["danger_bg"])
    COLOR_LOCKED_ROW = QColor(colors["table_alt"])


# ============================================================
# 全局日志缓冲区（用于界面底部日志区）
# ============================================================

def app_log(msg: str):
    """向全局日志区追加一条带时间戳的消息。"""
    global _log_widget
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    if _log_widget is not None:
        _log_widget.append(line)
    print(line)  # 同时输出到控制台


_log_widget: QTextEdit = None  # 由 MainWindow 初始化时赋值


# ============================================================
# 自定义组件：数量表格项（按正负着色）
# ============================================================

class QuantityTableItem(QTableWidgetItem):
    """根据数量正负自动设置前景色的表格项。"""

    def __init__(self, value: int):
        text = f"+{value}" if value > 0 else str(value)
        super().__init__(text)
        if value > 0:
            self.setForeground(QBrush(COLOR_GREEN))
        elif value < 0:
            self.setForeground(QBrush(COLOR_RED))
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)


def paint_parts_checkbox(painter, rect, checked, palette):
    """Draw the same centered selection box in the header and every row."""
    side = min(18, rect.width() - 6, rect.height() - 6)
    if side <= 0:
        return
    box = QRectF(
        rect.center().x() - side / 2,
        rect.center().y() - side / 2,
        side, side,
    )
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    border = palette.color(QPalette.Highlight if checked else QPalette.Text)
    if not checked:
        border.setAlpha(170)
    painter.setPen(QPen(border, 1.5))
    painter.setBrush(palette.color(QPalette.Highlight if checked else QPalette.Base))
    painter.drawRoundedRect(box, 2, 2)
    if checked:
        mark = QPainterPath()
        mark.moveTo(box.left() + 4, box.top() + 9)
        mark.lineTo(box.left() + 7.5, box.top() + 12.5)
        mark.lineTo(box.left() + 14, box.top() + 5.5)
        painter.setPen(QPen(palette.color(QPalette.HighlightedText), 2,
                            Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(mark)
    painter.restore()


class PartsCheckboxDelegate(QStyledItemDelegate):
    """Keep row checkbox painting and its clickable area aligned."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.features &= ~QStyleOptionViewItem.HasCheckIndicator

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        paint_parts_checkbox(
            painter, option.rect, index.data(Qt.CheckStateRole) == Qt.Checked.value,
            option.palette,
        )

    def editorEvent(self, event, model, option, index):
        if (event.type() == QEvent.MouseButtonRelease and
                event.button() == Qt.LeftButton and
                option.rect.contains(event.position().toPoint())):
            checked = index.data(Qt.CheckStateRole) == Qt.Checked.value
            return model.setData(index, Qt.Unchecked.value if checked else Qt.Checked.value,
                                 Qt.CheckStateRole)
        return super().editorEvent(event, model, option, index)


class PartsHeader(QHeaderView):
    """The checkbox header toggles visible rows instead of sorting checkmarks."""

    toggle_checked = Signal()

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._all_checked = False

    def set_all_checked(self, checked: bool):
        if self._all_checked != checked:
            self._all_checked = checked
            self.updateSection(0)

    def paintSection(self, painter, rect, logical_index):
        painter.save()
        super().paintSection(painter, rect, logical_index)
        painter.restore()
        if logical_index == 0:
            paint_parts_checkbox(painter, rect, self._all_checked,
                                 self.parent().palette())

    def mousePressEvent(self, event):
        if (event.button() == Qt.LeftButton and
                self.logicalIndexAt(event.position().toPoint()) == 0):
            self.toggle_checked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


# ============================================================
# 智能名称补全：实时模糊搜索物料
# ============================================================

class PartAutoComplete:
    """
    物料智能补全器 — 为物料输入框（QLineEdit）提供实时模糊搜索补全。

    交互逻辑：
    - 用户在输入框输入字符时，自动从 parts 表模糊匹配料号或名称
    - 下拉列表展示格式：[料号] 名称 (库存: X)
    - 用户选中后触发 on_part_selected 回调
    """

    def __init__(self, line_edit: QLineEdit, part_repo,
                 on_part_selected=None):
        self.line_edit = line_edit
        self.part_repo = part_repo
        self.on_part_selected = on_part_selected
        self._parts_cache: dict = {}  # display_text → part dict

        # 创建补全器
        self.completer = QCompleter(line_edit)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setMaxVisibleItems(10)
        self.completer.activated.connect(self._on_activated)
        line_edit.setCompleter(self.completer)

        # 防抖定时器（200ms）
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._update_completions)
        line_edit.textChanged.connect(lambda: self._timer.start(200))

    def _update_completions(self):
        """查询数据库并更新补全列表。"""
        text = self.line_edit.text().strip()
        if len(text) < 1:
            return

        parts = self.part_repo.search(text)
        model = QStandardItemModel()
        self._parts_cache.clear()

        for p in parts:
            available = p["stock_qty"] - p["locked_qty"]
            display = f"[{p['part_number']}] {p['name']} (库存:{available})"
            item = QStandardItem(display)
            item.setData(p["part_number"], Qt.UserRole)  # 存储料号用于回溯
            item.setData(dict(p), Qt.UserRole + 1)        # 存储完整物料数据
            model.appendRow(item)
            self._parts_cache[p["part_number"]] = dict(p)

        self.completer.setModel(model)
        if model.rowCount() > 0:
            self.completer.complete()

    def _on_activated(self, text: str):
        """用户从下拉列表选中一项。"""
        # 从 model 中查找对应的料号
        model = self.completer.model()
        if model is None:
            return
        # 遍历查找匹配的 item
        for row in range(model.rowCount()):
            item = model.item(row)
            if item.text() == text:
                part = item.data(Qt.UserRole + 1)
                if part and self.on_part_selected:
                    self.on_part_selected(part)
                return


# ============================================================
# 对话框：物料编辑
# ============================================================

class PartEditDialog(QDialog):
    """
    新增 / 编辑物料的对话框。

    新增模式：内部料号由系统根据「类别缩写-年月-六位流水号」规则全自动生成。
    编辑模式：料号为只读展示，不允许修改。
    """

    # 预定义的常用类别下拉选项（取自 CATEGORY_PREFIX_MAP 的去重键）
    PREDEFINED_CATEGORIES = [
        # 电子元件
        "电阻", "电容", "MCU", "集成电路", "LED", "二极管", "三极管",
        "MOS管", "电源IC", "电感", "晶振", "连接器", "排针", "开关",
        "保险丝", "继电器", "传感器", "模块", "线材", "PCB", "散热器",
        "变压器", "光耦", "电池",
        # 机械零件 — 紧固件
        "螺丝", "螺母", "垫圈", "螺栓", "螺柱", "挡圈", "卡簧", "键", "销",
        # 机械零件 — 传动件
        "轴承", "齿轮", "同步带", "同步带轮", "链条", "链轮", "轴", "联轴器",
        # 机械零件 — 导向 / 结构 / 气动
        "导轨", "滑块", "型材", "角码", "法兰", "板材", "管材", "钣金件",
        "机加工件", "弹簧", "气缸", "阀", "气管接头", "密封圈", "3D打印件",
    ]

    def __init__(self, parent=None, part_data: dict = None, db=None):
        super().__init__(parent)
        self.setWindowTitle("编辑物料" if part_data else "新增物料")
        self.setMinimumWidth(450)
        self.part_data = part_data
        self.db = db
        self._generated_pn = ""   # 确认时由 generate_part_number 填充

        layout = QFormLayout(self)

        # ---- 元件类别（可编辑下拉框） ----
        self.combo_cat = QComboBox()
        self.combo_cat.setEditable(True)
        self.combo_cat.addItems(self.PREDEFINED_CATEGORIES)
        self.combo_cat.setCurrentText("")
        self.combo_cat.setInsertPolicy(QComboBox.NoInsert)
        self.combo_cat.lineEdit().setPlaceholderText("请选择或输入物料分类（如：电阻、电容、螺丝、轴承…）")
        if part_data:
            self.combo_cat.setCurrentText(part_data.get("category", ""))
        self.combo_cat.currentTextChanged.connect(self._update_pn_preview)
        layout.addRow("物料类别 *:", self.combo_cat)

        # ---- 料号预览（只读，自动生成） ----
        self.lbl_pn = QLabel()
        self.lbl_pn.setObjectName("partNumberPreview")
        self.lbl_pn.setWordWrap(True)
        self.lbl_pn.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if part_data:
            # 编辑模式：直接显示已有料号
            self.lbl_pn.setText(part_data.get("part_number", ""))
            self.lbl_pn.setToolTip("内部料号在创建后不可修改")
        else:
            self._update_pn_preview()
        layout.addRow("内部料号:", self.lbl_pn)

        # ---- 名称 ----
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("例: 10KΩ 0805 1% 贴片电阻 / M6×20 12.9级 外六角螺栓")
        if part_data:
            self.edit_name.setText(part_data.get("name", ""))
        layout.addRow("名称 *:", self.edit_name)

        # ---- 封装 ----
        self.edit_pkg = QLineEdit()
        self.edit_pkg.setPlaceholderText("例: 0805 / M6×20 / 6202ZZ")
        if part_data:
            self.edit_pkg.setText(part_data.get("package", ""))
        layout.addRow("封装:", self.edit_pkg)

        # ---- 库位 ----
        self.edit_loc = QLineEdit()
        self.edit_loc.setPlaceholderText("例: B-02-05")
        if part_data:
            self.edit_loc.setText(part_data.get("location", ""))
        layout.addRow("库位:", self.edit_loc)

        # ---- 库存数量（仅新增时可填初始库存） ----
        self.edit_stock = QSpinBox()
        self.edit_stock.setRange(0, 9999999)
        if part_data:
            self.edit_stock.setValue(part_data.get("stock_qty", 0))
            self.edit_stock.setReadOnly(True)
            self.edit_stock.setToolTip("库存数量需通过入库/采购流程修改")
            self.combo_cat.setEnabled(False)  # 编辑时类别不可改，料号也不可改
        layout.addRow("库存数量:", self.edit_stock)

        # ---- 安全库存 ----
        self.edit_min = QSpinBox()
        self.edit_min.setRange(0, 9999999)
        if part_data:
            self.edit_min.setValue(part_data.get("min_stock", 0))
        layout.addRow("安全库存下限:", self.edit_min)

        # ---- 单价 ----
        self.edit_price = QDoubleSpinBox()
        self.edit_price.setRange(0.0, 9999999.99)
        self.edit_price.setDecimals(4)
        self.edit_price.setPrefix("¥ ")
        self.edit_price.setToolTip("物料单价（人民币），用于库存总价值估算")
        if part_data:
            self.edit_price.setValue(part_data.get("unit_price", 0.0))
        layout.addRow("单价 (¥):", self.edit_price)

        # ---- 默认供应商 ----
        self.combo_supplier = QComboBox()
        self.combo_supplier.addItem("（无）", None)
        if self.db:
            supplier_repo = SupplierRepository(self.db)
            for s in supplier_repo.get_all():
                self.combo_supplier.addItem(s["name"], s["id"])
        if part_data:
            sid = part_data.get("supplier_id")
            for i in range(self.combo_supplier.count()):
                if self.combo_supplier.itemData(i) == sid:
                    self.combo_supplier.setCurrentIndex(i)
                    break
        layout.addRow("默认供应商:", self.combo_supplier)

        # ---- 按钮 ----
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _update_pn_preview(self):
        """当类别变更时，更新料号预览标签。"""
        if self.part_data:
            return  # 编辑模式下不更新
        cat = self.combo_cat.currentText().strip()
        if not cat:
            self.lbl_pn.setText("（请先选择物料类别）")
            return
        # 显示格式预览
        prefix = CATEGORY_PREFIX_MAP.get(cat)
        if not prefix:
            clean = cat.upper()
            alpha = "".join(c for c in clean if c.isascii() and c.isalpha())
            prefix = alpha[:3] if len(alpha) >= 3 else "GEN"
        now = datetime.now()
        ym = now.strftime("%Y%m")
        self.lbl_pn.setText(f"{prefix}-{ym}-?????? （点击确认后自动分配）")

    def validate_and_accept(self):
        """校验输入，生成料号，并二次确认后接受对话框。"""
        # 编辑模式：料号不可变，只校验名称
        if self.part_data:
            if not self.edit_name.text().strip():
                QMessageBox.warning(self, "输入错误", "物料名称不能为空！")
                return
            self.accept()
            return

        # 新增模式：强制选择类别、填写名称，然后自动生成料号
        cat = self.combo_cat.currentText().strip()
        if not cat:
            QMessageBox.warning(self, "输入错误", "请选择或输入物料类别！")
            self.combo_cat.setFocus()
            return
        if not self.edit_name.text().strip():
            QMessageBox.warning(self, "输入错误", "物料名称不能为空！")
            return

        # 调用 generate_part_number 生成实际料号
        try:
            self._generated_pn = generate_part_number(self.db, cat)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"料号生成失败:\n{e}")
            return

        # 二次确认：向用户展示即将创建的料号
        reply = QMessageBox.question(
            self, "确认新增物料",
            f"系统已自动分配内部料号：\n\n"
            f"    {self._generated_pn}\n\n"
            f"  名称: {self.edit_name.text().strip()}\n"
            f"  类别: {cat}\n"
            f"  初始库存: {self.edit_stock.value()}\n\n"
            f"确认创建该物料？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            self.lbl_pn.setText(self._generated_pn)
            self.accept()

    def get_data(self) -> dict:
        """获取表单数据。新增模式下 part_number 为系统自动生成的值。"""
        if self.part_data:
            pn = self.part_data.get("part_number", "")
            cat = self.combo_cat.currentText().strip()
        else:
            pn = self._generated_pn
            cat = self.combo_cat.currentText().strip()

        return {
            "part_number": pn,
            "name": self.edit_name.text().strip(),
            "package": self.edit_pkg.text().strip(),
            "location": self.edit_loc.text().strip(),
            "category": cat,
            "stock_qty": self.edit_stock.value(),
            "min_stock": self.edit_min.value(),
            "unit_price": self.edit_price.value(),
            "supplier_id": self.combo_supplier.currentData(),
        }


# ============================================================
# 对话框：库存手动修复
# ============================================================

class AdjustStockDialog(QDialog):
    """
    库存手动修复对话框。

    用于盘点差异、供应商多发/少发、录入错误等场景下的人工库存修正。
    强制填写调整原因（备注），确保账目可追溯。
    """

    def __init__(self, parent=None, part_data: dict = None):
        super().__init__(parent)
        self.setWindowTitle("库存手动修复")
        self.setMinimumWidth(450)
        self.part_data = part_data

        layout = QFormLayout(self)

        # 物料信息展示（只读）
        self.lbl_pn = QLabel(part_data.get("part_number", ""))
        self.lbl_pn.setObjectName("resultSummary")
        layout.addRow("内部料号:", self.lbl_pn)

        self.lbl_name = QLabel(part_data.get("name", ""))
        layout.addRow("名称:", self.lbl_name)

        self.lbl_current_stock = QLabel(str(part_data.get("stock_qty", 0)))
        self.lbl_current_stock.setObjectName("accentValue")
        layout.addRow("当前物理库存:", self.lbl_current_stock)

        current_locked = part_data.get("locked_qty", 0)
        self.lbl_locked = QLabel(str(current_locked))
        if current_locked > 0:
            self.lbl_locked.setObjectName("warningValue")
        layout.addRow("当前锁定库存:", self.lbl_locked)

        available = part_data.get("stock_qty", 0) - current_locked
        self.lbl_available = QLabel(str(available))
        layout.addRow("当前可用库存:", self.lbl_available)

        # 分隔线（使用 QFrame）
        from PySide6.QtWidgets import QFrame as QF
        line = QF()
        line.setFrameShape(QF.HLine)
        line.setFrameShadow(QF.Sunken)
        layout.addRow(line)

        # 调整量输入
        self.spin_delta = QSpinBox()
        self.spin_delta.setRange(-9999999, 9999999)
        self.spin_delta.setValue(0)
        self.spin_delta.setToolTip("正数=库存增加，负数=库存减少")
        self.spin_delta.valueChanged.connect(self._on_delta_changed)
        layout.addRow("调整数量 (±):", self.spin_delta)

        # 调整后库存预览
        self.lbl_after = QLabel(str(part_data.get("stock_qty", 0)))
        self.lbl_after.setObjectName("accentValue")
        layout.addRow("调整后库存:", self.lbl_after)

        # 备注（必填）
        self.edit_remark = QLineEdit()
        self.edit_remark.setPlaceholderText(
            "必填！如：盘点发现少2个、供应商多发10个、录入错误修正..."
        )
        layout.addRow("调整原因 *:", self.edit_remark)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _on_delta_changed(self, delta: int):
        """调整量变化时更新预览。"""
        current = self.part_data.get("stock_qty", 0)
        after = current + delta
        self.lbl_after.setText(str(after))
        self.lbl_after.setObjectName("dangerValue" if after < 0 else "successValue")
        self.lbl_after.style().unpolish(self.lbl_after)
        self.lbl_after.style().polish(self.lbl_after)

    def validate_and_accept(self):
        """校验输入后接受对话框。"""
        current = self.part_data.get("stock_qty", 0)
        after = current + self.spin_delta.value()
        if after < 0:
            QMessageBox.warning(self, "输入错误",
                                f"调整后库存 ({after}) 不能为负数！请减小调整幅度。")
            return
        if self.spin_delta.value() == 0:
            QMessageBox.warning(self, "输入错误", "调整数量不能为 0！")
            return
        if not self.edit_remark.text().strip():
            QMessageBox.warning(self, "输入错误", "必须填写调整原因（备注）！")
            self.edit_remark.setFocus()
            return
        self.accept()

    def get_delta(self) -> int:
        """获取调整量。"""
        return self.spin_delta.value()

    def get_remark(self) -> str:
        """获取调整原因。"""
        return self.edit_remark.text().strip()


# ============================================================
# 对话框：批量库存修正
# ============================================================

class BatchAdjustStockDialog(QDialog):
    """批量库存修正对话框 — 对选中的多个物料统一调整库存。"""

    def __init__(self, parent=None, parts: list = None):
        super().__init__(parent)
        self.parts = parts or []
        self.setWindowTitle("批量库存修正")
        self.setMinimumWidth(550)

        layout = QVBoxLayout(self)

        # 顶部信息
        layout.addWidget(QLabel(f"已选择 <b>{len(self.parts)}</b> 种物料"))

        # 预览表格
        preview_table = QTableWidget()
        preview_table.setColumnCount(4)
        preview_table.setHorizontalHeaderLabels(["内部料号", "名称", "当前库存", "调整后库存"])
        preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        preview_table.setRowCount(len(self.parts))
        for i, p in enumerate(self.parts):
            preview_table.setItem(i, 0, QTableWidgetItem(p["part_number"]))
            preview_table.setItem(i, 1, QTableWidgetItem(p["name"]))
            preview_table.setItem(i, 2, QTableWidgetItem(str(p["stock_qty"])))
        preview_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(preview_table)
        self._preview_table = preview_table

        # 调整量输入
        form = QFormLayout()
        self.spin_delta = QSpinBox()
        self.spin_delta.setRange(-9999999, 9999999)
        self.spin_delta.setValue(0)
        self.spin_delta.valueChanged.connect(self._update_preview)
        form.addRow("统一调整量 (+/-):", self.spin_delta)

        self.edit_remark = QLineEdit()
        self.edit_remark.setPlaceholderText("必填！请输入调整原因，如：盘点修正、损耗调整等")
        form.addRow("原因 *:", self.edit_remark)
        layout.addLayout(form)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_preview()

    def _update_preview(self):
        """更新预览表格中的调整后库存。"""
        delta = self.spin_delta.value()
        for i, p in enumerate(self.parts):
            after = p["stock_qty"] + delta
            item = QTableWidgetItem(str(after))
            if after < 0:
                item.setForeground(QBrush(COLOR_RED))
            self._preview_table.setItem(i, 3, item)

    def _validate_and_accept(self):
        """校验输入后接受对话框。"""
        delta = self.spin_delta.value()
        if not self.edit_remark.text().strip():
            QMessageBox.warning(self, "输入错误", "请填写调整原因！")
            return
        # 检查是否有负数结果
        negative = [(p["part_number"], p["stock_qty"] + delta)
                    for p in self.parts if p["stock_qty"] + delta < 0]
        if negative:
            msg = "以下物料调整后库存将为负数，请修正：\n"
            msg += "\n".join(f"  {pn}: {after}" for pn, after in negative[:10])
            QMessageBox.warning(self, "库存不足", msg)
            return
        # 二次确认
        reply = QMessageBox.question(
            self, "确认批量修正",
            f"将对 {len(self.parts)} 种物料统一调整 {'+' if delta > 0 else ''}{delta}。\n"
            f"原因: {self.edit_remark.text().strip()}\n\n确认执行？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.accept()

    def get_delta(self) -> int:
        return self.spin_delta.value()

    def get_remark(self) -> str:
        return self.edit_remark.text().strip()


# ============================================================
# 对话框：批量编辑物料字段
# ============================================================

class BatchEditFieldsDialog(QDialog):
    """批量编辑物料字段 — 对选中的多个物料统一修改字段值。"""

    def __init__(self, parent=None, parts: list = None, db: DatabaseManager = None):
        super().__init__(parent)
        self.parts = parts or []
        self.db = db
        self.setWindowTitle("批量编辑物料字段")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"已选择 <b>{len(self.parts)}</b> 种物料"))

        # 预览表格（只读）
        preview_table = QTableWidget()
        preview_table.setColumnCount(3)
        preview_table.setHorizontalHeaderLabels(["内部料号", "名称", "封装"])
        preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        preview_table.setRowCount(min(len(self.parts), 8))  # 最多显示 8 行
        for i, p in enumerate(self.parts[:8]):
            preview_table.setItem(i, 0, QTableWidgetItem(p["part_number"]))
            preview_table.setItem(i, 1, QTableWidgetItem(p["name"]))
            preview_table.setItem(i, 2, QTableWidgetItem(p.get("package", "")))
        if len(self.parts) > 8:
            preview_table.setRowCount(9)
            preview_table.setItem(8, 0, QTableWidgetItem(f"... 等共 {len(self.parts)} 种"))
        preview_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(preview_table)

        # 可编辑字段（带复选框开关）
        form = QFormLayout()

        # 分类
        cat_row = QHBoxLayout()
        self.chk_category = QCheckBox("修改分类")
        self.combo_category = QComboBox()
        self.combo_category.setEditable(True)
        self.combo_category.addItems(PartEditDialog.PREDEFINED_CATEGORIES)
        self.combo_category.setCurrentText("")
        self.combo_category.setEnabled(False)
        self.chk_category.toggled.connect(self.combo_category.setEnabled)
        cat_row.addWidget(self.chk_category)
        cat_row.addWidget(self.combo_category, 1)
        form.addRow(cat_row)

        # 库位
        loc_row = QHBoxLayout()
        self.chk_location = QCheckBox("修改库位")
        self.edit_location = QLineEdit()
        self.edit_location.setEnabled(False)
        self.chk_location.toggled.connect(self.edit_location.setEnabled)
        loc_row.addWidget(self.chk_location)
        loc_row.addWidget(self.edit_location, 1)
        form.addRow(loc_row)

        # 安全库存
        min_row = QHBoxLayout()
        self.chk_min_stock = QCheckBox("修改安全库存下限")
        self.spin_min_stock = QSpinBox()
        self.spin_min_stock.setRange(0, 9999999)
        self.spin_min_stock.setEnabled(False)
        self.chk_min_stock.toggled.connect(self.spin_min_stock.setEnabled)
        min_row.addWidget(self.chk_min_stock)
        min_row.addWidget(self.spin_min_stock, 1)
        form.addRow(min_row)

        # 供应商
        sup_row = QHBoxLayout()
        self.chk_supplier = QCheckBox("修改供应商")
        self.combo_supplier = QComboBox()
        self.combo_supplier.addItem("（无）", None)
        if self.db:
            supplier_repo = SupplierRepository(self.db)
            for s in supplier_repo.get_all():
                self.combo_supplier.addItem(s["name"], s["id"])
        self.combo_supplier.setEnabled(False)
        self.chk_supplier.toggled.connect(self.combo_supplier.setEnabled)
        sup_row.addWidget(self.chk_supplier)
        sup_row.addWidget(self.combo_supplier, 1)
        form.addRow(sup_row)

        layout.addLayout(form)

        # 提示
        layout.addWidget(QLabel("仅更新勾选的字段，未勾选的保留原值。"))

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self):
        """校验并接受。"""
        has_any = (self.chk_category.isChecked() or self.chk_location.isChecked() or
                   self.chk_min_stock.isChecked() or self.chk_supplier.isChecked())
        if not has_any:
            QMessageBox.warning(self, "未选择", "请至少勾选一个要修改的字段！")
            return
        self.accept()

    def get_updates(self) -> dict:
        """获取要更新的字段字典。"""
        updates = {}
        if self.chk_category.isChecked() and self.combo_category.currentText().strip():
            updates["category"] = self.combo_category.currentText().strip()
        if self.chk_location.isChecked():
            updates["location"] = self.edit_location.text().strip()
        if self.chk_min_stock.isChecked():
            updates["min_stock"] = self.spin_min_stock.value()
        if self.chk_supplier.isChecked():
            updates["supplier_id"] = self.combo_supplier.currentData()
        return updates


# ============================================================
# 对话框：批量导入物料
# ============================================================

class BatchImportPartsDialog(QDialog):
    """批量导入物料 — 从 Excel 文件批量创建物料。"""

    # 列名别名映射（与 BOM 解析类似）
    COLUMN_ALIASES = {
        "category": ["类别", "分类", "物料类别", "category", "Category", "CATEGORY"],
        "name": ["名称", "物料名称", "品名", "name", "Name", "NAME"],
        "package": ["封装", "规格", "型号", "package", "Package", "PACKAGE", "封装类型"],
        "location": ["库位", "存放位置", "location", "Location", "LOCATION"],
        "stock_qty": ["初始库存", "库存数量", "数量", "stock_qty", "Qty", "QTY"],
        "min_stock": ["安全库存", "最低库存", "min_stock", "Min Stock"],
        "unit_price": ["单价", "价格", "unit_price", "Unit Price", "Price"],
        "supplier": ["供应商", "默认供应商", "supplier", "Supplier"],
    }

    REQUIRED_COLS = ["category", "name"]

    def __init__(self, parent=None, db: DatabaseManager = None,
                 part_repo: PartRepository = None, trans_repo: TransactionRepository = None):
        super().__init__(parent)
        self.db = db
        self.part_repo = part_repo
        self.trans_repo = trans_repo
        self._import_data = []  # 解析后的数据
        self.setWindowTitle("批量导入物料")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        # 步骤 1：选择文件
        step1 = QHBoxLayout()
        step1.addWidget(QLabel("1. 选择 Excel 文件:"))
        self.lbl_file = QLabel("未选择文件")
        self.lbl_file.setFrameStyle(QFrame.StyledPanel)
        step1.addWidget(self.lbl_file, 1)
        btn_select = QPushButton("浏览...")
        btn_select.clicked.connect(self._on_select_file)
        step1.addWidget(btn_select)
        layout.addLayout(step1)

        # 步骤 2：预览表格
        layout.addWidget(QLabel("2. 预览数据:"))
        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.setAlternatingRowColors(True)
        layout.addWidget(self.preview_table)

        # 导入选项
        opt_layout = QHBoxLayout()
        self.chk_match_supplier = QCheckBox("尝试按名称匹配供应商")
        self.chk_match_supplier.setChecked(True)
        opt_layout.addWidget(self.chk_match_supplier)
        opt_layout.addStretch()
        layout.addLayout(opt_layout)

        # 导入按钮
        btn_layout2 = QHBoxLayout()
        btn_layout2.addStretch()
        self.btn_import = QPushButton("📥 开始导入")
        self.btn_import.setEnabled(False)
        self.btn_import.setObjectName("primaryButton")
        self.btn_import.clicked.connect(self._on_import)
        btn_layout2.addWidget(self.btn_import)
        btn_layout2.addStretch()
        layout.addLayout(btn_layout2)

    def _normalize_columns(self, df):
        """规范化列名：将 Excel 中的各种列名映射到标准列名。"""
        for std_name, aliases in self.COLUMN_ALIASES.items():
            for col in df.columns:
                if col.strip() in aliases:
                    df.rename(columns={col: std_name}, inplace=True)
                    break
        return df

    def _on_select_file(self):
        """选择 Excel 文件并解析预览。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择导入文件",
            os.path.dirname(database_module.DB_PATH),
            "Excel 文件 (*.xlsx *.xls)"
        )
        if not file_path:
            return

        try:
            import pandas as pd
            df = pd.read_excel(file_path)
            df = df.dropna(how='all').dropna(axis=1, how='all')
            df = self._normalize_columns(df)

            # 检查必填列
            missing = [c for c in self.REQUIRED_COLS if c not in df.columns]
            if missing:
                QMessageBox.warning(self, "格式错误",
                                    f"缺少必填列: {', '.join(missing)}\n\n"
                                    f"必填列: 类别, 名称\n"
                                    f"可选列: 封装, 库位, 初始库存, 安全库存, 单价, 供应商")
                return

            self.lbl_file.setText(os.path.basename(file_path))
            self.lbl_file.setToolTip(file_path)

            # 填充预览表格
            self._import_data = []
            cols = [c for c in ["category", "name", "package", "location",
                                "stock_qty", "min_stock", "unit_price", "supplier"]
                    if c in df.columns]
            self.preview_table.setColumnCount(len(cols))
            self.preview_table.setHorizontalHeaderLabels(cols)
            self.preview_table.setRowCount(len(df))

            for i, (_, row) in enumerate(df.iterrows()):
                item_data = {}
                for j, col in enumerate(cols):
                    val = row.get(col, "")
                    if pd.isna(val):
                        val = ""
                    # 数值列转换
                    if col in ("stock_qty", "min_stock"):
                        val = int(float(val)) if val != "" else 0
                    elif col == "unit_price":
                        val = float(val) if val != "" else 0.0
                    item_data[col] = val
                    self.preview_table.setItem(i, j, QTableWidgetItem(str(val)))
                self._import_data.append(item_data)

            self.preview_table.horizontalHeader().setStretchLastSection(True)
            self.btn_import.setEnabled(len(self._import_data) > 0)

            app_log(f"批量导入预览: {file_path} — {len(self._import_data)} 行")
        except Exception as e:
            QMessageBox.critical(self, "解析失败", f"无法解析 Excel 文件:\n{e}")
            app_log(f"[错误] 批量导入解析失败: {e}")

    def _on_import(self):
        """执行批量导入。"""
        if not self._import_data:
            return

        # 确认
        reply = QMessageBox.question(
            self, "确认导入",
            f"将导入 {len(self._import_data)} 种物料。\n"
            f"系统将自动为每条记录分配料号。\n\n确认开始导入？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        # 预加载供应商映射
        supplier_map = {}
        if self.chk_match_supplier.isChecked() and self.db:
            sr = SupplierRepository(self.db)
            for s in sr.get_all():
                supplier_map[s["name"]] = s["id"]

        success = 0
        skipped = 0
        failed = 0
        failures = []

        from database import generate_part_number

        for item in self._import_data:
            try:
                cat = item.get("category", "").strip()
                name = item.get("name", "").strip()
                if not cat or not name:
                    failed += 1
                    failures.append(f"(空类别或空名称)")
                    continue

                pn = generate_part_number(self.db, cat)

                # 解析供应商
                supplier_id = None
                supplier_name = item.get("supplier", "").strip()
                if supplier_name and supplier_name in supplier_map:
                    supplier_id = supplier_map[supplier_name]

                # 插入物料
                new_id = self.part_repo.insert(
                    part_number=pn,
                    name=name,
                    package=str(item.get("package", "")).strip(),
                    location=str(item.get("location", "")).strip(),
                    category=cat,
                    stock_qty=int(item.get("stock_qty", 0)),
                    min_stock=int(item.get("min_stock", 0)),
                    supplier_id=supplier_id,
                    unit_price=float(item.get("unit_price", 0.0)),
                )

                # 记录入库流水
                stock_qty = int(item.get("stock_qty", 0))
                if stock_qty > 0:
                    self.trans_repo.insert(new_id, "INBOUND", stock_qty,
                                           remark="批量导入初始库存")

                success += 1
            except Exception as e:
                failed += 1
                failures.append(f"{item.get('name', '?')}: {e}")

        msg = f"导入完成！\n成功: {success} 种\n失败: {failed} 种"
        if skipped:
            msg += f"\n跳过(重复): {skipped} 种"
        if failures:
            msg += "\n\n失败详情:\n" + "\n".join(failures[:10])
            if len(failures) > 10:
                msg += f"\n... 等共 {len(failures)} 条"

        app_log(f"批量导入完成: 成功 {success}, 失败 {failed}, 跳过 {skipped}")
        QMessageBox.information(self, "导入完成", msg)

        if success > 0:
            self.accept()


# ============================================================
# 对话框：供应商管理
# ============================================================

class SupplierManageDialog(QDialog):
    """供应商管理对话框：增删改查供应商信息。"""

    def __init__(self, parent=None, db: DatabaseManager = None):
        super().__init__(parent)
        self.setWindowTitle("供应商管理")
        self.setMinimumSize(700, 450)
        self.db = db
        self.supplier_repo = SupplierRepository(db) if db else None

        layout = QVBoxLayout(self)

        # ---- 供应商表格 ----
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "名称", "联系人", "电话", "邮箱", "网址", "备注"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # ---- 按钮栏 ----
        btn_layout = QHBoxLayout()

        self.btn_add = QPushButton("＋ 新增供应商")
        self.btn_add.clicked.connect(self.on_add)
        btn_layout.addWidget(self.btn_add)

        self.btn_edit = QPushButton("✎ 编辑")
        self.btn_edit.clicked.connect(self.on_edit)
        self.btn_edit.setEnabled(False)
        btn_layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton("✕ 删除")
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_delete.setEnabled(False)
        btn_layout.addWidget(self.btn_delete)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.table.selectionModel().selectionChanged.connect(
            lambda: self.btn_edit.setEnabled(True) or self.btn_delete.setEnabled(True)
            if self.table.currentRow() >= 0 else None
        )

        self.refresh_table()

    def refresh_table(self):
        """刷新供应商列表。"""
        if self.supplier_repo is None:
            return
        suppliers = self.supplier_repo.get_all()
        self.table.setRowCount(len(suppliers))
        for i, s in enumerate(suppliers):
            self.table.setItem(i, 0, QTableWidgetItem(s["name"]))
            self.table.setItem(i, 1, QTableWidgetItem(s["contact_person"] or ""))
            self.table.setItem(i, 2, QTableWidgetItem(s["phone"] or ""))
            self.table.setItem(i, 3, QTableWidgetItem(s["email"] or ""))
            self.table.setItem(i, 4, QTableWidgetItem(s["website"] or ""))
            self.table.setItem(i, 5, QTableWidgetItem(s["remark"] or ""))
            self.table.item(i, 0).setData(Qt.UserRole, s["id"])

    def _get_selected_id(self) -> int:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.UserRole)

    def on_add(self):
        """新增供应商。"""
        dialog = SupplierEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.supplier_repo.insert(**data)
            app_log(f"新增供应商: {data['name']}")
            self.refresh_table()

    def on_edit(self):
        """编辑供应商。"""
        sid = self._get_selected_id()
        if sid is None:
            return
        supplier = self.supplier_repo.get_by_id(sid)
        dialog = SupplierEditDialog(self, dict(supplier))
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.supplier_repo.update(sid, **data)
            app_log(f"更新供应商: {data['name']}")
            self.refresh_table()

    def on_delete(self):
        """删除供应商。"""
        sid = self._get_selected_id()
        if sid is None:
            return
        supplier = self.supplier_repo.get_by_id(sid)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除供应商「{supplier['name']}」吗？\n（仅当无关联物料时才可删除）",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        ok = self.supplier_repo.delete(sid)
        if ok:
            app_log(f"删除供应商: {supplier['name']}")
            self.refresh_table()
        else:
            QMessageBox.warning(self, "无法删除", "该供应商下仍有关联物料，请先解除关联。")


class SupplierEditDialog(QDialog):
    """供应商编辑对话框。"""

    def __init__(self, parent=None, data: dict = None):
        super().__init__(parent)
        self.setWindowTitle("编辑供应商" if data else "新增供应商")
        self.setMinimumWidth(400)

        layout = QFormLayout(self)

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("供应商名称（必填）")
        if data:
            self.edit_name.setText(data.get("name", ""))
        layout.addRow("名称 *:", self.edit_name)

        self.edit_contact = QLineEdit()
        self.edit_contact.setPlaceholderText("联系人姓名")
        if data:
            self.edit_contact.setText(data.get("contact_person", ""))
        layout.addRow("联系人:", self.edit_contact)

        self.edit_phone = QLineEdit()
        self.edit_phone.setPlaceholderText("联系电话")
        if data:
            self.edit_phone.setText(data.get("phone", ""))
        layout.addRow("电话:", self.edit_phone)

        self.edit_email = QLineEdit()
        self.edit_email.setPlaceholderText("电子邮箱")
        if data:
            self.edit_email.setText(data.get("email", ""))
        layout.addRow("邮箱:", self.edit_email)

        self.edit_website = QLineEdit()
        self.edit_website.setPlaceholderText("网址")
        if data:
            self.edit_website.setText(data.get("website", ""))
        layout.addRow("网址:", self.edit_website)

        self.edit_address = QLineEdit()
        self.edit_address.setPlaceholderText("地址")
        if data:
            self.edit_address.setText(data.get("address", ""))
        layout.addRow("地址:", self.edit_address)

        self.edit_remark = QLineEdit()
        self.edit_remark.setPlaceholderText("备注")
        if data:
            self.edit_remark.setText(data.get("remark", ""))
        layout.addRow("备注:", self.edit_remark)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def validate_and_accept(self):
        if not self.edit_name.text().strip():
            QMessageBox.warning(self, "输入错误", "供应商名称不能为空！")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "name": self.edit_name.text().strip(),
            "contact_person": self.edit_contact.text().strip(),
            "phone": self.edit_phone.text().strip(),
            "email": self.edit_email.text().strip(),
            "website": self.edit_website.text().strip(),
            "address": self.edit_address.text().strip(),
            "remark": self.edit_remark.text().strip(),
        }


# ============================================================
# 对话框：拣货单（按库位排序的物料清单）
# ============================================================

class PickingListDialog(QDialog):
    """
    拣货单对话框：按库位排序显示待拣物料清单。
    支持勾选确认已拣项目，支持导出 Excel。
    """

    def __init__(self, parent, items: list, title: str = "拣货单"):
        """
        Args:
            items: list of dicts with keys: part_number, name, location, qty_needed
            title: dialog title
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(700, 450)
        self.items = items

        layout = QVBoxLayout(self)

        # ---- 标题行 ----
        info_layout = QHBoxLayout()
        info_layout.addWidget(QLabel(f"共 {len(items)} 种物料需要拣货"))
        info_layout.addStretch()

        self.btn_export = QPushButton("📤 导出拣货单至 Excel")
        self.btn_export.clicked.connect(self._export_excel)
        self.btn_export.setObjectName("primaryButton")
        info_layout.addWidget(self.btn_export)
        layout.addLayout(info_layout)

        # ---- 表格：按库位排序 ----
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "库位", "内部料号", "名称", "需求数量", "已拣确认"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)

        # 按库位排序（空库位排在最后）
        sorted_items = sorted(items, key=lambda x: (x.get("location", "ÿÿÿ") or "ÿÿÿ"))

        self.table.setRowCount(len(sorted_items))
        for i, it in enumerate(sorted_items):
            loc = it.get("location", "-") or "-"
            self.table.setItem(i, 0, QTableWidgetItem(loc))
            self.table.setItem(i, 1, QTableWidgetItem(it["part_number"]))
            self.table.setItem(i, 2, QTableWidgetItem(it.get("name", "")))
            qty_item = QTableWidgetItem(str(it["qty_needed"]))
            qty_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 3, qty_item)

            # 可勾选的已拣确认列
            check_item = QTableWidgetItem("☐")
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Unchecked)
            self.table.setItem(i, 4, check_item)

        layout.addWidget(self.table)

        # ---- 关闭按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

    def _export_excel(self):
        """导出拣货单为 Excel。"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出拣货单",
            os.path.join(os.path.dirname(database_module.DB_PATH), "拣货单.xlsx"),
            "Excel 文件 (*.xlsx)"
        )
        if not file_path:
            return

        import pandas as pd
        data = []
        sorted_items = sorted(self.items, key=lambda x: (x.get("location", "ÿÿÿ") or "ÿÿÿ"))
        for it in sorted_items:
            data.append({
                "库位": it.get("location", "-") or "-",
                "内部料号": it["part_number"],
                "名称": it.get("name", ""),
                "需求数量": it["qty_needed"],
            })
        df = pd.DataFrame(data)
        df.to_excel(file_path, index=False, engine="openpyxl")
        app_log(f"拣货单已导出至 {file_path}")
        QMessageBox.information(self, "导出成功", f"拣货单已保存至:\n{file_path}")


# ============================================================
# Tab 1: 物料管理
# ============================================================

class PartsTab(QWidget):
    """物料管理选项卡：物料的 CRUD、搜索、二维码标签生成。"""

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.repo = PartRepository(db)
        self.trans_repo = TransactionRepository(db)

        # ---- 布局 ----
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # 顶部：搜索栏（关键词 + 分类 + 库存状态筛选 + 防抖）
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入料号/名称/分类进行模糊搜索...")
        # 200ms 防抖：连续输入时仅在停止输入后触发搜索
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.refresh_table)
        self.search_input.textChanged.connect(lambda: self._search_timer.start(200))
        search_layout.addWidget(self.search_input)

        search_layout.addWidget(QLabel("分类:"))
        self.filter_category = QComboBox()
        self.filter_category.addItem("全部")
        self.filter_category.setMinimumWidth(80)
        self.filter_category.currentTextChanged.connect(self.refresh_table)
        search_layout.addWidget(self.filter_category)

        search_layout.addWidget(QLabel("库存:"))
        self.filter_stock = QComboBox()
        self.filter_stock.addItems(["全部", "低库存", "有锁定", "零库存"])
        self.filter_stock.currentTextChanged.connect(self.refresh_table)
        search_layout.addWidget(self.filter_stock)

        self.btn_clear_search = QPushButton("清除")
        self.btn_clear_search.clicked.connect(self.clear_search)
        search_layout.addWidget(self.btn_clear_search)

        search_layout.addStretch()

        self.lbl_results = QLabel("0 种物料")
        self.lbl_results.setObjectName("resultSummary")
        search_layout.addWidget(self.lbl_results)

        main_layout.addLayout(search_layout)

        # 中部：物料表格（第0列为复选框，第1-10列为数据）
        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeader(PartsHeader(Qt.Horizontal, self.table))
        self.table.setItemDelegateForColumn(0, PartsCheckboxDelegate(self.table))
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.setHorizontalHeaderLabels([
            "", "内部料号", "名称", "封装", "库位", "分类",
            "物理库存", "锁定库存", "可用库存", "单价", "供应商"
        ])
        self.table.horizontalHeader().toggle_checked.connect(self._toggle_visible_checks)
        for col in range(1, self.table.columnCount()):
            self.table.horizontalHeaderItem(col).setToolTip(
                "点击列标题排序；箭头表示当前升序或降序"
            )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 42)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # 只读表格
        self.table.setSortingEnabled(False)  # 将在数据加载后启用以保证排序正确的初始状态
        self.table.horizontalHeader().setSortIndicator(1, Qt.AscendingOrder)
        self.table.setAlternatingRowColors(True)
        self.table.selectionModel().selectionChanged.connect(self.on_selection_changed)
        self.table.cellDoubleClicked.connect(lambda row, col: self.on_edit_part())
        # 复选框委托处理勾选切换，cellClicked 更新批量操作和表头状态
        self.table.cellClicked.connect(self._on_cell_clicked)
        main_layout.addWidget(self.table)

        # 底部：操作按钮栏 — 第 1 行（单物料操作）
        btn_layout = QHBoxLayout()

        self.btn_add = QPushButton("＋ 新增物料")
        self.btn_add.setObjectName("primaryButton")
        self.btn_add.clicked.connect(self.on_add_part)
        btn_layout.addWidget(self.btn_add)

        self.btn_import = QPushButton("📥 批量导入")
        self.btn_import.clicked.connect(self.on_batch_import)
        btn_layout.addWidget(self.btn_import)

        self.btn_edit = QPushButton("✎ 编辑物料")
        self.btn_edit.clicked.connect(self.on_edit_part)
        self.btn_edit.setEnabled(False)
        btn_layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton("✕ 删除物料")
        self.btn_delete.setObjectName("dangerButton")
        self.btn_delete.clicked.connect(self.on_delete_part)
        self.btn_delete.setEnabled(False)
        btn_layout.addWidget(self.btn_delete)

        btn_layout.addStretch()

        self.btn_qr = QPushButton("📷 生成二维码标签")
        self.btn_qr.clicked.connect(self.on_generate_qr)
        self.btn_qr.setEnabled(False)
        btn_layout.addWidget(self.btn_qr)

        self.btn_adjust = QPushButton("🔧 库存修正")
        self.btn_adjust.clicked.connect(self.on_adjust_stock)
        self.btn_adjust.setEnabled(False)
        self.btn_adjust.setObjectName("primaryButton")
        btn_layout.addWidget(self.btn_adjust)

        btn_layout.addStretch()

        self.btn_purchase = QPushButton("📋 导出采购清单")
        self.btn_purchase.clicked.connect(self.on_export_purchase_list)
        self.btn_purchase.setObjectName("primaryButton")
        btn_layout.addWidget(self.btn_purchase)

        self.btn_suppliers = QPushButton("🏢 管理供应商")
        self.btn_suppliers.clicked.connect(self.on_manage_suppliers)
        btn_layout.addWidget(self.btn_suppliers)

        main_layout.addLayout(btn_layout)

        # 底部：操作按钮栏 — 第 2 行（批量操作）
        batch_btn_layout = QHBoxLayout()

        self.btn_select_all = QPushButton("☑ 全选")
        self.btn_select_all.clicked.connect(self.on_select_all)
        batch_btn_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("☐ 取消全选")
        self.btn_deselect_all.clicked.connect(self.on_deselect_all)
        batch_btn_layout.addWidget(self.btn_deselect_all)

        batch_btn_layout.addStretch()

        self.btn_batch_adjust = QPushButton("🔧 批量修正库存")
        self.btn_batch_adjust.clicked.connect(self.on_batch_adjust_stock)
        self.btn_batch_adjust.setEnabled(False)
        self.btn_batch_adjust.setObjectName("primaryButton")
        batch_btn_layout.addWidget(self.btn_batch_adjust)

        self.btn_batch_qr = QPushButton("📷 批量生成标签")
        self.btn_batch_qr.clicked.connect(self.on_batch_generate_qr)
        self.btn_batch_qr.setEnabled(False)
        batch_btn_layout.addWidget(self.btn_batch_qr)

        self.btn_batch_edit = QPushButton("✎ 批量编辑字段")
        self.btn_batch_edit.clicked.connect(self.on_batch_edit_fields)
        self.btn_batch_edit.setEnabled(False)
        batch_btn_layout.addWidget(self.btn_batch_edit)

        self.btn_batch_delete = QPushButton("✕ 批量删除")
        self.btn_batch_delete.setObjectName("dangerButton")
        self.btn_batch_delete.clicked.connect(self.on_batch_delete)
        self.btn_batch_delete.setEnabled(False)
        batch_btn_layout.addWidget(self.btn_batch_delete)

        batch_btn_layout.addStretch()

        self.btn_batch_export = QPushButton("📤 批量导出选中")
        self.btn_batch_export.clicked.connect(self.on_batch_export)
        self.btn_batch_export.setEnabled(False)
        batch_btn_layout.addWidget(self.btn_batch_export)

        main_layout.addLayout(batch_btn_layout)

        # 右键菜单
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_context_menu)

        # ---- 键盘快捷键 ----
        from PySide6.QtGui import QShortcut, QKeySequence

        shortcut_search = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_search.activated.connect(lambda: self.search_input.setFocus())

        shortcut_refresh = QShortcut(QKeySequence("F5"), self)
        shortcut_refresh.activated.connect(self.refresh_table)

        shortcut_new = QShortcut(QKeySequence("Ctrl+N"), self)
        shortcut_new.activated.connect(self.on_add_part)

        shortcut_edit = QShortcut(QKeySequence("Ctrl+E"), self)
        shortcut_edit.activated.connect(self.on_edit_part)

        shortcut_delete = QShortcut(QKeySequence("Delete"), self)
        shortcut_delete.activated.connect(self._on_shortcut_delete)

        shortcut_select_all = QShortcut(QKeySequence("Ctrl+A"), self)
        shortcut_select_all.activated.connect(self.on_select_all)

        # 初始加载
        self.refresh_table()

    # ---- 数据刷新 ----

    def load_parts_data(self):
        """从数据库重新加载物料列表并刷新表格（保留滚动条位置和选中行）。"""
        # ---- 保存当前 UI 状态 ----
        selected_id = self._get_selected_part_id()
        checked_ids = set(self._get_checked_part_ids())
        self.table.setSortingEnabled(False)  # 数据加载期间暂停排序
        scrollbar = self.table.verticalScrollBar()
        saved_scroll = scrollbar.value()

        # ---- 读取筛选条件 ----
        keyword = self.search_input.text().strip()
        cat_filter = self.filter_category.currentText()
        stock_filter = self.filter_stock.currentText()

        # 数据库层筛选（关键词 + 分类）
        if keyword or (cat_filter != "全部"):
            rows = self.repo.search_advanced(keyword=keyword, category=cat_filter if cat_filter != "全部" else "")
        else:
            rows = self.repo.get_all()

        # Python 层筛选（库存状态 — available_qty 是计算列）
        if stock_filter == "低库存":
            rows = [r for r in rows if r["available_qty"] < r["min_stock"]]
        elif stock_filter == "有锁定":
            rows = [r for r in rows if r["locked_qty"] > 0]
        elif stock_filter == "零库存":
            rows = [r for r in rows if r["stock_qty"] == 0]

        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            # 第0列：复选框（默认未勾选）
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked if row["id"] in checked_ids else Qt.Unchecked)
            chk_item.setText("")  # 不显示文字
            self.table.setItem(i, 0, chk_item)

            number_item = QTableWidgetItem(row["part_number"])
            number_item.setData(Qt.UserRole, row["id"])
            self.table.setItem(i, 1, number_item)
            self.table.setItem(i, 2, QTableWidgetItem(row["name"]))
            self.table.setItem(i, 3, QTableWidgetItem(row["package"] or ""))
            self.table.setItem(i, 4, QTableWidgetItem(row["location"] or ""))
            self.table.setItem(i, 5, QTableWidgetItem(row["category"] or ""))

            # 库存列：居中对齐，使用数值数据以支持正确排序
            stock_item = QTableWidgetItem()
            stock_item.setData(Qt.DisplayRole, row["stock_qty"])
            stock_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 6, stock_item)

            locked_item = QTableWidgetItem()
            locked_item.setData(Qt.DisplayRole, row["locked_qty"])
            locked_item.setTextAlignment(Qt.AlignCenter)
            if row["locked_qty"] > 0:
                locked_item.setForeground(QBrush(COLOR_WARNING))
            self.table.setItem(i, 7, locked_item)

            available = row["available_qty"]
            avail_item = QTableWidgetItem()
            avail_item.setData(Qt.DisplayRole, available)
            avail_item.setTextAlignment(Qt.AlignCenter)
            if available < row["min_stock"]:
                avail_item.setBackground(QBrush(COLOR_SHORTAGE_BG))  # 低于安全库存时标红
            self.table.setItem(i, 8, avail_item)

            # 单价
            price_val = row["unit_price"] if "unit_price" in row.keys() else 0.0
            price_item = QTableWidgetItem()
            price_item.setData(Qt.DisplayRole, price_val)
            price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 9, price_item)

            # 供应商
            supplier_name = row["supplier_name"] if "supplier_name" in row.keys() else "-"
            self.table.setItem(i, 10, QTableWidgetItem(supplier_name or "-"))

        # ---- 恢复 UI 状态 ----
        self.table.setSortingEnabled(True)
        self.table.clearSelection()
        if selected_id is not None:
            for i in range(self.table.rowCount()):
                if self.table.item(i, 1).data(Qt.UserRole) == selected_id:
                    self.table.selectRow(i)
                    break
        scrollbar.setValue(min(saved_scroll, scrollbar.maximum()))
        self.lbl_results.setText(f"显示 {len(rows)} 种物料 · 已勾选 {self._get_checked_count()} 种")

    # 兼容别名
    def refresh_table(self):
        """刷新物料表格（含筛选下拉框）。"""
        # 刷新分类下拉框（保留当前选中值）
        current_cat = self.filter_category.currentText()
        self.filter_category.blockSignals(True)
        self.filter_category.clear()
        self.filter_category.addItem("全部")
        for cat in self.repo.get_distinct_categories():
            self.filter_category.addItem(cat)
        # 恢复之前选中的分类
        idx = self.filter_category.findText(current_cat)
        if idx >= 0:
            self.filter_category.setCurrentIndex(idx)
        self.filter_category.blockSignals(False)

        self.load_parts_data()
        self._update_button_states()

    def on_search(self):
        self.refresh_table()

    def clear_search(self):
        self.search_input.clear()
        self.filter_category.setCurrentIndex(0)
        self.filter_stock.setCurrentIndex(0)
        self.refresh_table()

    def on_selection_changed(self):
        """表格选中行变化时，更新按钮状态（单选操作基于选中行，批量操作基于复选框）。"""
        self._update_button_states()

    def _update_button_states(self):
        """根据当前选中行和复选框勾选状态更新所有按钮。"""
        current_row = self.table.currentRow()
        has_single = current_row >= 0
        checked_count = self._get_checked_count()
        has_checked = checked_count >= 1

        # 单物料操作按钮：仅选中单行时可用
        self.btn_edit.setEnabled(has_single)
        # 单选也可以操作（基于currentRow）
        self.btn_delete.setEnabled(has_single)
        self.btn_qr.setEnabled(has_single)
        self.btn_adjust.setEnabled(has_single)

        # 批量操作按钮：有勾选行时可用
        self.btn_batch_adjust.setEnabled(has_checked)
        self.btn_batch_qr.setEnabled(has_checked)
        self.btn_batch_edit.setEnabled(has_checked)
        self.btn_batch_delete.setEnabled(has_checked)
        self.btn_batch_export.setEnabled(has_checked)
        self.lbl_results.setText(
            f"显示 {self.table.rowCount()} 种物料 · 已勾选 {checked_count} 种"
        )
        check_header = self.table.horizontalHeaderItem(0)
        if check_header:
            all_checked = self.table.rowCount() > 0 and checked_count == self.table.rowCount()
            self.table.horizontalHeader().set_all_checked(all_checked)
            check_header.setToolTip(
                f"点击{'取消全选' if all_checked else '全选'}当前列表（{checked_count}/{self.table.rowCount()}）"
            )

    def _toggle_visible_checks(self):
        if self.table.rowCount() == 0:
            return
        if self._get_checked_count() == self.table.rowCount():
            self.on_deselect_all()
        else:
            self.on_select_all()

    def _on_cell_clicked(self, row: int, col: int):
        """在复选框委托处理点击后同步表头和批量操作状态。"""
        self._update_button_states()

    def _emit_transaction(self, trans_id: int):
        """从数据库查询流水记录并通过信号发出，供日志界面单条追加。"""
        if hasattr(self, '_new_transaction_signal') and self._new_transaction_signal is not None:
            row = self.trans_repo.get_by_id(trans_id)
            if row:
                self._new_transaction_signal.emit(dict(row))

    def _get_selected_part_id(self) -> int:
        """获取当前选中行对应的物料 ID（用于单选操作）。"""
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        return item.data(Qt.UserRole) if item else None

    def _get_selected_part_data(self) -> dict:
        """获取当前选中行的物料完整数据（用于兼容原有单选代码）。"""
        part_id = self._get_selected_part_id()
        part = self.repo.get_by_id(part_id) if part_id is not None else None
        return dict(part) if part else None

    def _get_checked_part_ids(self) -> list:
        """获取所有复选框已勾选行对应的物料 ID 列表（用于批量操作）。"""
        ids = []
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, 0)
            if chk_item and chk_item.checkState() == Qt.Checked:
                number_item = self.table.item(row, 1)
                if number_item:
                    ids.append(number_item.data(Qt.UserRole))
        return ids

    def _get_checked_part_datas(self) -> list:
        """获取所有复选框已勾选行的物料完整数据列表（用于批量操作）。"""
        ids = self._get_checked_part_ids()
        if not ids:
            return []
        parts = self.repo.get_by_ids(ids)
        return [dict(p) for p in parts]

    def _get_checked_count(self) -> int:
        """获取已勾选的行数。"""
        count = 0
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, 0)
            if chk_item and chk_item.checkState() == Qt.Checked:
                count += 1
        return count

    # ---- CRUD 操作 ----

    def on_add_part(self):
        """新增物料。"""
        dialog = PartEditDialog(self, db=self.db)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            try:
                new_id = self.repo.insert(**data)
                # 记录入库流水（如果初始库存大于0）
                if data["stock_qty"] > 0:
                    trans_id = self.trans_repo.insert(
                        new_id, "INBOUND", data["stock_qty"],
                        remark="初始库存入库")
                    # 实时追加到日志表格
                    self._emit_transaction(trans_id)
                app_log(f"新增物料成功: {data['part_number']} (ID={new_id})")
                self.refresh_table()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"新增物料失败:\n{e}")
                app_log(f"[错误] 新增物料失败: {e}")

    def on_edit_part(self):
        """编辑物料。"""
        part_data = self._get_selected_part_data()
        if part_data is None:
            return

        dialog = PartEditDialog(self, part_data)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            update_fields = {
                "name": data["name"],
                "package": data["package"],
                "location": data["location"],
                "category": data["category"],
                "min_stock": data["min_stock"],
                "unit_price": data.get("unit_price", 0.0),
                "supplier_id": data.get("supplier_id"),
            }
            try:
                self.repo.update(part_data["id"], **update_fields)
                app_log(f"更新物料成功: {part_data['part_number']}")
                self.refresh_table()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"更新物料失败:\n{e}")

    def on_delete_part(self):
        """删除物料。"""
        part_data = self._get_selected_part_data()
        if part_data is None:
            return

        # 二次确认
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除物料 {part_data['part_number']} 吗？\n"
            f"名称: {part_data['name']}\n"
            f"此操作不可撤销！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        success = self.repo.delete(part_data["id"])
        if success:
            app_log(f"删除物料成功: {part_data['part_number']}")
            self.refresh_table()
        else:
            QMessageBox.warning(
                self, "无法删除",
                f"物料 {part_data['part_number']} 存在锁定库存 ({part_data['locked_qty']})，\n"
                f"请先完成或取消关联的工单后再删除。"
            )

    # ---- 二维码标签 ----

    def on_generate_qr(self):
        """生成选中物料的二维码标签。"""
        part_data = self._get_selected_part_data()
        if part_data is None:
            return

        try:
            label_img = generate_label(part_data)
            pixmap = label_to_pixmap(label_img)

            # 弹出预览对话框
            dialog = QDialog(self)
            dialog.setWindowTitle(f"二维码标签 - {part_data['part_number']}")
            dialog.setMinimumSize(LABEL_WIDTH + 40, LABEL_HEIGHT + 100)

            layout = QVBoxLayout(dialog)

            # 预览图片
            img_label = QLabel()
            img_label.setPixmap(pixmap)
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setFrameStyle(QFrame.StyledPanel)
            layout.addWidget(img_label)

            # 保存按钮
            btn_layout = QHBoxLayout()
            btn_save = QPushButton("💾 保存为图片")
            btn_save.clicked.connect(lambda: self._save_label(label_img, part_data))
            btn_layout.addStretch()
            btn_layout.addWidget(btn_save)
            layout.addLayout(btn_layout)

            app_log(f"已生成标签: {part_data['part_number']}")
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成标签失败:\n{e}")
            app_log(f"[错误] 生成标签失败: {e}")

    def _save_label(self, label_img, part_data: dict):
        """保存标签图片到本地文件。"""
        default_name = f"label_{part_data['part_number']}.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存标签图片",
            os.path.join(os.path.dirname(database_module.DB_PATH), "Labels", default_name),
            "PNG 图片 (*.png)"
        )
        if file_path:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            label_img.save(file_path)
            app_log(f"标签已保存: {file_path}")
            QMessageBox.information(self, "保存成功", f"标签已保存至:\n{file_path}")

    # ---- 采购清单导出 ----

    def on_export_purchase_list(self):
        """导出低库存物料的采购清单到 Excel（含供应商信息）。"""
        rows = self.repo.get_all()
        low_stock = [
            r for r in rows
            if (r["stock_qty"] - r["locked_qty"]) < r["min_stock"]
        ]
        if not low_stock:
            QMessageBox.information(self, "提示", "所有物料库存充足，无需采购！")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出采购清单",
            os.path.join(os.path.dirname(database_module.DB_PATH), "采购清单.xlsx"),
            "Excel 文件 (*.xlsx)"
        )
        if not file_path:
            return

        import pandas as pd
        data = []
        for r in low_stock:
            available = r["stock_qty"] - r["locked_qty"]
            shortage = r["min_stock"] - available
            data.append({
                "内部料号": r["part_number"],
                "名称": r["name"],
                "封装": r["package"] or "",
                "库位": r["location"] or "",
                "当前库存": r["stock_qty"],
                "锁定库存": r["locked_qty"],
                "可用库存": available,
                "安全库存": r["min_stock"],
                "缺料数量": shortage,
                "单价": r["unit_price"] or 0,
                "供应商": r["supplier_name"] or "-",
            })
        df = pd.DataFrame(data)
        df.to_excel(file_path, index=False, engine="openpyxl")
        app_log(f"采购清单已导出至 {file_path}，共 {len(data)} 种物料需采购")
        QMessageBox.information(self, "导出成功",
                                f"采购清单已保存至:\n{file_path}\n"
                                f"共 {len(data)} 种物料需采购")

    # ---- 供应商管理 ----

    def on_manage_suppliers(self):
        """打开供应商管理对话框。"""
        dialog = SupplierManageDialog(self, self.db)
        dialog.exec()
        # 刷新表格以反映供应商变化
        self.refresh_table()

    # ---- 库存手动修复 ----

    def on_adjust_stock(self):
        """打开库存修正对话框，手动调整物料库存。"""
        part_data = self._get_selected_part_data()
        if part_data is None:
            return

        dialog = AdjustStockDialog(self, part_data)
        if dialog.exec() == QDialog.Accepted:
            delta = dialog.get_delta()
            remark = dialog.get_remark()

            try:
                # 更新物理库存
                self.repo.adjust_stock(part_data["id"], delta)

                # 记录流水（ADJUSTMENT 类型）
                trans_id = self.trans_repo.insert(
                    part_data["id"], "ADJUSTMENT", delta,
                    remark=f"库存修正: {remark}"
                )
                self._emit_transaction(trans_id)

                app_log(
                    f"库存修正: {part_data['part_number']} "
                    f"{'+' if delta > 0 else ''}{delta}（原因: {remark}）"
                )
                QMessageBox.information(
                    self, "修正完成",
                    f"物料 {part_data['part_number']} 库存已调整\n"
                    f"调整量: {'+' if delta > 0 else ''}{delta}\n"
                    f"当前库存: {part_data['stock_qty'] + delta}"
                )
                self.refresh_table()

                # 跨模块刷新（通过信号通知其他选项卡）
                if hasattr(self, '_stock_changed_signal') and self._stock_changed_signal is not None:
                    self._stock_changed_signal.emit()

            except Exception as e:
                QMessageBox.critical(self, "错误", f"库存修正失败:\n{e}")
                app_log(f"[错误] 库存修正失败: {e}")

    def on_context_menu(self, pos):
        """右键菜单：根据复选框勾选数量自动切换单选 / 批量菜单。"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return

        checked_count = self._get_checked_count()
        if checked_count <= 1:
            # 单选菜单
            self.table.selectRow(row)
            menu = QMenu(self)
            action_adjust = menu.addAction("🔧 库存修正")
            action_qr = menu.addAction("📷 生成二维码标签")
            menu.addSeparator()
            action_edit = menu.addAction("✎ 编辑物料")
            action_delete = menu.addAction("✕ 删除物料")

            action = menu.exec(self.table.viewport().mapToGlobal(pos))
            if action == action_adjust:
                self.on_adjust_stock()
            elif action == action_qr:
                self.on_generate_qr()
            elif action == action_edit:
                self.on_edit_part()
            elif action == action_delete:
                self.on_delete_part()
        else:
            # 批量菜单
            menu = QMenu(self)
            action_batch_adjust = menu.addAction("🔧 批量修正库存")
            action_batch_qr = menu.addAction("📷 批量生成标签")
            action_batch_edit = menu.addAction("✎ 批量编辑字段")
            menu.addSeparator()
            action_batch_delete = menu.addAction("✕ 批量删除")
            action_batch_export = menu.addAction("📤 批量导出选中")

            action = menu.exec(self.table.viewport().mapToGlobal(pos))
            if action == action_batch_adjust:
                self.on_batch_adjust_stock()
            elif action == action_batch_qr:
                self.on_batch_generate_qr()
            elif action == action_batch_edit:
                self.on_batch_edit_fields()
            elif action == action_batch_delete:
                self.on_batch_delete()
            elif action == action_batch_export:
                self.on_batch_export()

    # ---- 批量操作 ----

    def on_select_all(self):
        """全选 — 勾选所有复选框。"""
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, 0)
            if chk_item:
                chk_item.setCheckState(Qt.Checked)
        self.table.blockSignals(False)
        self._update_button_states()

    def on_deselect_all(self):
        """取消全选 — 取消所有复选框勾选。"""
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, 0)
            if chk_item:
                chk_item.setCheckState(Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_button_states()

    def _on_shortcut_delete(self):
        """Delete 键处理：根据勾选数量调用单选或批量删除。"""
        checked_count = self._get_checked_count()
        if checked_count > 1:
            self.on_batch_delete()
        elif checked_count == 1:
            self.on_delete_part()
        elif self.table.currentRow() >= 0:
            self.on_delete_part()

    def on_batch_adjust_stock(self):
        """批量库存修正。"""
        parts = self._get_checked_part_datas()
        if not parts:
            QMessageBox.information(self, "提示", "请先勾选需要操作的物料行。")
            return
        dialog = BatchAdjustStockDialog(self, parts)
        if dialog.exec() == QDialog.Accepted:
            delta = dialog.get_delta()
            remark = dialog.get_remark()
            trans_records = []
            try:
                for p in parts:
                    self.repo.adjust_stock(p["id"], delta)
                    trans_records.append(
                        (p["id"], "ADJUSTMENT", delta, None, f"批量库存修正: {remark}")
                    )
                # 批量插入流水
                trans_ids = self.trans_repo.batch_insert(trans_records)
                for tid in trans_ids:
                    self._emit_transaction(tid)
                app_log(f"批量库存修正: {len(parts)} 种物料, 调整量 {'+' if delta > 0 else ''}{delta}, 原因: {remark}")
                QMessageBox.information(self, "完成",
                                        f"已对 {len(parts)} 种物料完成库存修正。\n"
                                        f"调整量: {'+' if delta > 0 else ''}{delta}")
                self.refresh_table()
                if hasattr(self, '_stock_changed_signal') and self._stock_changed_signal is not None:
                    self._stock_changed_signal.emit()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"批量库存修正失败:\n{e}")
                app_log(f"[错误] 批量库存修正失败: {e}")

    def on_batch_generate_qr(self):
        """批量生成二维码标签。"""
        parts = self._get_checked_part_datas()
        if not parts:
            QMessageBox.information(self, "提示", "请先勾选需要操作的物料行。")
            return

        # 选择保存目录
        default_dir = os.path.join(os.path.dirname(database_module.DB_PATH), "Labels")
        save_dir = QFileDialog.getExistingDirectory(self, "选择标签保存目录", default_dir)
        if not save_dir:
            return

        os.makedirs(save_dir, exist_ok=True)
        success = 0
        for i, p in enumerate(parts):
            try:
                label_img = generate_label(p)
                file_path = os.path.join(save_dir, f"label_{p['part_number']}.png")
                label_img.save(file_path)
                success += 1
                app_log(f"批量标签 [{i+1}/{len(parts)}]: {p['part_number']}")
            except Exception as e:
                app_log(f"[错误] 标签生成失败 {p['part_number']}: {e}")

        QMessageBox.information(self, "完成",
                                f"成功生成 {success}/{len(parts)} 个标签。\n"
                                f"保存目录: {save_dir}")

    def on_batch_edit_fields(self):
        """批量编辑物料字段。"""
        parts = self._get_checked_part_datas()
        if not parts:
            QMessageBox.information(self, "提示", "请先勾选需要操作的物料行。")
            return
        dialog = BatchEditFieldsDialog(self, parts, self.db)
        if dialog.exec() == QDialog.Accepted:
            updates = dialog.get_updates()
            if not updates:
                return
            part_ids = [p["id"] for p in parts]
            try:
                affected = self.repo.batch_update(part_ids, **updates)
                field_names = ", ".join(updates.keys())
                app_log(f"批量编辑: {affected} 种物料, 修改字段: {field_names}")
                QMessageBox.information(self, "完成",
                                        f"已更新 {affected} 种物料。\n修改字段: {field_names}")
                self.refresh_table()
                if hasattr(self, '_stock_changed_signal') and self._stock_changed_signal is not None:
                    self._stock_changed_signal.emit()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"批量编辑失败:\n{e}")
                app_log(f"[错误] 批量编辑失败: {e}")

    def on_batch_delete(self):
        """批量删除物料。"""
        parts = self._get_checked_part_datas()
        if not parts:
            QMessageBox.information(self, "提示", "请先勾选需要操作的物料行。")
            return

        # 统计锁定库存
        locked_parts = [p for p in parts if p["locked_qty"] > 0]
        deletable = [p for p in parts if p["locked_qty"] == 0]

        if not deletable:
            QMessageBox.warning(self, "无法删除",
                                f"选中的 {len(parts)} 种物料全部存在锁定库存，无法删除。\n"
                                f"请先完成或取消关联的工单。")
            return

        msg = f"已选择 {len(parts)} 种物料。\n"
        if locked_parts:
            msg += f"其中 {len(locked_parts)} 种有锁定库存（将被跳过）。\n"
        msg += f"\n确认删除 {len(deletable)} 种物料？\n此操作不可撤销！"

        reply = QMessageBox.question(self, "确认批量删除", msg,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        part_ids = [p["id"] for p in parts]
        deleted, skipped = self.repo.batch_delete(part_ids)
        app_log(f"批量删除: 成功 {deleted}, 跳过 {len(skipped)}（锁定库存）")
        result_msg = f"成功删除 {deleted} 种物料。"
        if skipped:
            result_msg += f"\n跳过 {len(skipped)} 种（存在锁定库存）:\n" + "\n".join(skipped[:10])
            if len(skipped) > 10:
                result_msg += f"\n... 等共 {len(skipped)} 种"
        QMessageBox.information(self, "删除完成", result_msg)
        self.refresh_table()
        if hasattr(self, '_stock_changed_signal') and self._stock_changed_signal is not None:
            self._stock_changed_signal.emit()

    def on_batch_export(self):
        """批量导出选中物料到 Excel。"""
        parts = self._get_checked_part_datas()
        if not parts:
            QMessageBox.information(self, "提示", "请先勾选需要操作的物料行。")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出选中物料",
            os.path.join(os.path.dirname(database_module.DB_PATH), "选中物料导出.xlsx"),
            "Excel 文件 (*.xlsx)"
        )
        if not file_path:
            return

        import pandas as pd
        data = []
        for p in parts:
            available = p["stock_qty"] - p["locked_qty"]
            data.append({
                "内部料号": p["part_number"],
                "名称": p["name"],
                "封装": p["package"] or "",
                "库位": p["location"] or "",
                "分类": p["category"] or "",
                "物理库存": p["stock_qty"],
                "锁定库存": p["locked_qty"],
                "可用库存": available,
                "单价": p["unit_price"] or 0,
                "供应商": p["supplier_name"] or "-",
            })
        df = pd.DataFrame(data)
        df.to_excel(file_path, index=False, engine="openpyxl")
        app_log(f"批量导出: {len(parts)} 种物料 -> {file_path}")
        QMessageBox.information(self, "导出成功",
                                f"已导出 {len(parts)} 种物料至:\n{file_path}")

    def on_batch_import(self):
        """打开批量导入物料对话框。"""
        dialog = BatchImportPartsDialog(self, self.db, self.repo, self.trans_repo)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_table()
            if hasattr(self, '_stock_changed_signal') and self._stock_changed_signal is not None:
                self._stock_changed_signal.emit()

class BOMTab(QWidget):
    """BOM 导入与核销选项卡。"""

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.wo_repo = WorkOrderRepository(db)
        self.part_repo = PartRepository(db)
        self.trans_repo = TransactionRepository(db)
        self.bom_repo = BomRepository(db)   # 用于导入时保存到本地 BOM 库
        self.current_bom_df = None   # 当前已解析的 BOM DataFrame
        self.current_bom_path = ""   # 当前 BOM 文件路径
        self.current_bom_name = ""   # 文件名或本地 BOM 名称
        self._last_bom_dir = ""      # 记住上次打开的 BOM 目录

        # ---- 布局 ----
        main_layout = QVBoxLayout(self)

        # === 上半部分：BOM 导入区 ===
        import_group = QGroupBox("BOM 导入")
        import_layout = QVBoxLayout(import_group)

        # 第一行：文件选择 + 份数
        top_row = QHBoxLayout()
        self.lbl_file = QLabel("未选择文件")
        self.lbl_file.setObjectName("fileDisplay")
        self.lbl_file.setFrameStyle(QFrame.StyledPanel)
        top_row.addWidget(self.lbl_file, 1)

        self.combo_bom_library = QComboBox()
        self.combo_bom_library.addItem("（从BOM库快捷选择）")
        self.combo_bom_library.setMinimumWidth(160)
        self.combo_bom_library.currentIndexChanged.connect(self._on_bom_library_selected)
        top_row.addWidget(self.combo_bom_library)

        self.btn_select_bom = QPushButton("选择 BOM 文件")
        self.btn_select_bom.clicked.connect(self.on_select_bom)
        top_row.addWidget(self.btn_select_bom)

        top_row.addWidget(QLabel("计划生产份数:"))
        self.spin_planned_qty = QSpinBox()
        self.spin_planned_qty.setRange(1, 999999)
        self.spin_planned_qty.setValue(1)
        self.spin_planned_qty.valueChanged.connect(self._refresh_preview)
        top_row.addWidget(self.spin_planned_qty)

        self.chk_save_to_lib = QCheckBox("保存到本地BOM库")
        self.chk_save_to_lib.setToolTip("勾选后，导入的 BOM 结构将自动存入本地 BOM 库，方便日后复用与导出")
        self.chk_save_to_lib.setEnabled(False)
        top_row.addWidget(self.chk_save_to_lib)

        self.btn_lock = QPushButton("🔒 锁定库存 / 生成工单")
        self.btn_lock.clicked.connect(self.on_lock_stock)
        self.btn_lock.setEnabled(False)
        self.btn_lock.setObjectName("primaryButton")
        top_row.addWidget(self.btn_lock)

        import_layout.addLayout(top_row)

        # BOM 预览表格
        self.bom_table = QTableWidget()
        self.bom_table.setColumnCount(7)
        self.bom_table.setHorizontalHeaderLabels([
            "料号", "名称", "封装", "库位", "单份用量", "总需求", "库存状态"
        ])
        self.bom_table.horizontalHeader().setStretchLastSection(True)
        self.bom_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.bom_table.setSortingEnabled(True)
        self.bom_table.setAlternatingRowColors(True)
        import_layout.addWidget(self.bom_table)

        self.lbl_bom_status = QLabel("选择 Excel 文件或从 BOM 库加载后，可预览库存匹配情况。")
        self.lbl_bom_status.setObjectName("sectionHint")
        import_layout.addWidget(self.lbl_bom_status)

        main_layout.addWidget(import_group)

        # === 下半部分：工单管理区 ===
        order_group = QGroupBox("工单管理")
        order_layout = QVBoxLayout(order_group)

        # 工单筛选
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("状态筛选:"))
        self.combo_status_filter = QComboBox()
        self.combo_status_filter.addItem("全部", "")
        self.combo_status_filter.addItem("已锁定 (LOCKED)", "LOCKED")
        self.combo_status_filter.addItem("已完成 (COMPLETED)", "COMPLETED")
        self.combo_status_filter.addItem("已取消 (CANCELLED)", "CANCELLED")
        self.combo_status_filter.currentTextChanged.connect(self.refresh_order_list)
        filter_row.addWidget(self.combo_status_filter)
        filter_row.addStretch()
        self.btn_refresh_orders = QPushButton("刷新工单列表")
        self.btn_refresh_orders.clicked.connect(self.refresh_order_list)
        filter_row.addWidget(self.btn_refresh_orders)
        order_layout.addLayout(filter_row)

        # 工单分割器：上为工单列表，下为明细
        splitter = QSplitter(Qt.Vertical)

        # 工单列表
        self.order_table = QTableWidget()
        self.order_table.setColumnCount(7)
        self.order_table.setHorizontalHeaderLabels([
            "工单号", "BOM名称", "计划份数", "实际完工", "状态", "创建时间", "备注"
        ])
        self.order_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.order_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.order_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.order_table.setSortingEnabled(True)
        self.order_table.horizontalHeader().setStretchLastSection(True)
        self.order_table.selectionModel().selectionChanged.connect(self.on_order_selected)
        splitter.addWidget(self.order_table)

        # 明细 + 核销操作区
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)

        self.order_items_table = QTableWidget()
        self.order_items_table.setColumnCount(7)
        self.order_items_table.setHorizontalHeaderLabels([
            "料号", "名称", "需求数量", "锁定数量", "理论消耗", "实际消耗", "退库数量"
        ])
        self.order_items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.order_items_table.setSortingEnabled(True)
        self.order_items_table.horizontalHeader().setStretchLastSection(True)
        detail_layout.addWidget(self.order_items_table)

        # 核销操作行
        writeoff_row = QHBoxLayout()
        writeoff_row.addWidget(QLabel("实际完工份数:"))
        self.spin_actual_qty = QSpinBox()
        self.spin_actual_qty.setRange(0, 999999)
        self.spin_actual_qty.setEnabled(False)
        self.spin_actual_qty.valueChanged.connect(self.on_recalc_theory)
        writeoff_row.addWidget(self.spin_actual_qty)

        self.btn_recalc_theory = QPushButton("重置为理论用量")
        self.btn_recalc_theory.clicked.connect(self.on_recalc_theory)
        self.btn_recalc_theory.setEnabled(False)
        self.btn_recalc_theory.setToolTip("实际完工份数变化时会自动计算；此按钮可将手动填写的实耗重置为理论值")
        writeoff_row.addWidget(self.btn_recalc_theory)

        self.btn_confirm_writeoff = QPushButton("✅ 确认核销")
        self.btn_confirm_writeoff.setObjectName("primaryButton")
        self.btn_confirm_writeoff.clicked.connect(self.on_confirm_writeoff)
        self.btn_confirm_writeoff.setEnabled(False)
        writeoff_row.addWidget(self.btn_confirm_writeoff)

        self.btn_cancel_order = QPushButton("✕ 取消工单")
        self.btn_cancel_order.clicked.connect(self.on_cancel_order)
        self.btn_cancel_order.setEnabled(False)
        self.btn_cancel_order.setObjectName("dangerButton")
        writeoff_row.addWidget(self.btn_cancel_order)

        writeoff_row.addStretch()
        detail_layout.addLayout(writeoff_row)

        splitter.addWidget(detail_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        order_layout.addWidget(splitter)

        main_layout.addWidget(order_group)

        # 初始化
        self.current_order_id = None
        self.refresh_order_list()

    def _emit_transaction(self, trans_id: int):
        """从数据库查询流水记录并通过信号发出，供日志界面单条追加。"""
        if hasattr(self, '_new_transaction_signal') and self._new_transaction_signal is not None:
            row = self.trans_repo.get_by_id(trans_id)
            if row:
                self._new_transaction_signal.emit(dict(row))

    # ---- BOM 导入 ----

    def on_select_bom(self):
        """选择并解析 BOM 文件（记住上次目录）。"""
        start_dir = self._last_bom_dir or os.path.dirname(database_module.DB_PATH)
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 BOM 文件",
            start_dir,
            "Excel 文件 (*.xlsx *.xls)"
        )
        if not file_path:
            return

        self._last_bom_dir = os.path.dirname(file_path)
        app_log(f"正在读取 BOM: {file_path} ...")

        df, errors = parse_bom(file_path)
        if df is None:
            QMessageBox.critical(self, "BOM 解析失败", "\n".join(errors))
            app_log(f"[错误] BOM 解析失败: {errors}")
            return

        self.current_bom_df = df
        self.current_bom_path = file_path
        self.current_bom_name = os.path.basename(file_path)
        self.lbl_file.setText(os.path.basename(file_path))
        self.lbl_file.setToolTip(file_path)

        # 预览 BOM
        self._preview_bom(df)
        self.chk_save_to_lib.setEnabled(True)
        app_log(f"BOM 解析成功: {len(df)} 行物料")

    def _refresh_preview(self):
        """生产份数变化时同步更新需求量和库存提示。"""
        if self.current_bom_df is not None:
            self._preview_bom(self.current_bom_df)

    def _preview_bom(self, df):
        """在 BOM 预览表格中显示 BOM 内容，并与库存比对。"""
        planned_qty = self.spin_planned_qty.value()
        demand_df = calculate_demand(df, planned_qty)

        # 构建库存映射
        all_parts = self.part_repo.get_all()
        parts_map = {p["part_number"]: dict(p) for p in all_parts}

        self.bom_table.setSortingEnabled(False)
        self.bom_table.setRowCount(len(demand_df))
        shortage_count = 0
        for i, (_, row) in enumerate(demand_df.iterrows()):
            pn = str(row["part_number"]).strip()
            self.bom_table.setItem(i, 0, QTableWidgetItem(pn))
            self.bom_table.setItem(i, 1, QTableWidgetItem(row["name"]))
            self.bom_table.setItem(i, 2, QTableWidgetItem(str(row.get("package", ""))))
            self.bom_table.setItem(i, 3, QTableWidgetItem(str(row.get("location", ""))))

            unit_qty = QTableWidgetItem(str(int(row["quantity"])))
            unit_qty.setTextAlignment(Qt.AlignCenter)
            self.bom_table.setItem(i, 4, unit_qty)

            total_demand = int(row["total_demand"])
            demand_item = QTableWidgetItem(str(total_demand))
            demand_item.setTextAlignment(Qt.AlignCenter)
            self.bom_table.setItem(i, 5, demand_item)

            # 库存状态判断
            part_info = parts_map.get(pn)
            if part_info is None:
                status = "❌ 未录入"
                status_color = COLOR_RED
            else:
                available = part_info["stock_qty"] - part_info["locked_qty"]
                if available >= total_demand:
                    status = f"✅ 充足 ({available})"
                    status_color = COLOR_GREEN
                else:
                    status = f"⚠ 缺料 (需{total_demand}, 可用{available})"
                    status_color = COLOR_RED

            status_item = QTableWidgetItem(status)
            status_item.setForeground(QBrush(status_color))
            self.bom_table.setItem(i, 6, status_item)

            # 缺料行高亮背景
            if "缺料" in status or "未录入" in status:
                shortage_count += 1
                for col in range(7):
                    self.bom_table.item(i, col).setBackground(QBrush(COLOR_SHORTAGE_BG))

        self.bom_table.setSortingEnabled(True)
        self.btn_lock.setEnabled(shortage_count == 0 and len(demand_df) > 0)
        if shortage_count:
            self.lbl_bom_status.setText(
                f"{len(demand_df)} 种物料 · {shortage_count} 种缺料或未录入，请补齐后生成工单"
            )
            self.btn_lock.setToolTip("当前 BOM 存在缺料或未录入物料")
        else:
            self.lbl_bom_status.setText(
                f"{len(demand_df)} 种物料 · 计划 {planned_qty} 份 · 库存满足，可生成工单"
            )
            self.btn_lock.setToolTip("锁定所需库存并创建生产工单")

    def on_lock_stock(self):
        """锁定库存，生成生产工单。"""
        if self.current_bom_df is None:
            return

        planned_qty = self.spin_planned_qty.value()
        demand_df = calculate_demand(self.current_bom_df, planned_qty)

        # 构建库存映射
        all_parts = self.part_repo.get_all()
        parts_map = {p["part_number"]: dict(p) for p in all_parts}

        # 检查缺料
        shortages = check_shortage(self.current_bom_df, planned_qty, parts_map)
        if shortages:
            shortage_msg = "以下物料库存不足，无法生成工单：\n\n"
            for s in shortages:
                shortage_msg += (f"  • {s['part_number']} {s['name']}\n"
                                 f"    需求: {s['demand']}, 可用: {s['available']}, "
                                 f"缺: {s['shortage']} ({s['reason']})\n\n")

            QMessageBox.warning(self, "缺料提醒", shortage_msg)
            app_log(f"[缺料] 共 {len(shortages)} 种物料不足，锁定操作已阻断")
            return

        # 二次确认
        reply = QMessageBox.question(
            self, "确认锁定库存",
            f"即将锁定以下物料库存，并生成生产工单：\n\n"
            f"  BOM: {self.current_bom_name}\n"
            f"  计划生产份数: {planned_qty}\n"
            f"  物料种类: {len(demand_df)}\n\n"
            f"确认操作？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            # 生成工单号
            now = datetime.now()
            order_number = f"WO-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"

            # 创建工单
            order_id = self.wo_repo.insert(
                order_number=order_number,
                bom_name=self.current_bom_name,
                planned_qty=planned_qty,
            )

            # 逐项锁定库存
            for _, row in demand_df.iterrows():
                pn = str(row["part_number"]).strip()
                demand = int(row["total_demand"])
                part = parts_map[pn]
                part_id = part["id"]

                # 添加明细
                self.wo_repo.insert_item(order_id, part_id, demand, demand)

                # 更新物料的 locked_qty
                self.part_repo.lock_stock(part_id, demand)

                # 记录流水
                trans_id = self.trans_repo.insert(
                    part_id, "WO_LOCK", -demand,
                    work_order_id=order_id,
                    remark=f"工单 {order_number} 锁定"
                )
                self._emit_transaction(trans_id)

            app_log(f"工单 {order_number} 创建成功，已锁定 {len(demand_df)} 种物料")

            # ---- 可选项：将 BOM 结构保存到本地 BOM 库 ----
            if self.chk_save_to_lib.isChecked() and self.current_bom_path:
                bom_name = os.path.splitext(os.path.basename(self.current_bom_path))[0]
                try:
                    # 先删除同名旧 BOM（如果存在），再全量插入
                    existing = self.bom_repo.get_items_by_name(bom_name)
                    if existing:
                        self.bom_repo.delete_bom(bom_name)
                    for _, row in demand_df.iterrows():
                        pn = str(row["part_number"]).strip()
                        qty = int(row["quantity"])  # 单份用量
                        self.bom_repo.insert_item(bom_name, pn, qty, "")
                    app_log(f"BOM「{bom_name}」已保存到本地 BOM 库（{len(demand_df)} 行）")
                except Exception as e:
                    app_log(f"[警告] 保存 BOM 到本地库失败: {e}")

            QMessageBox.information(self, "成功", f"工单 {order_number} 已生成！\n物料库存已锁定。")

            # 询问是否查看拣货单（按库位排序）
            reply = QMessageBox.question(
                self, "拣货单",
                "是否需要查看按库位排序的拣货单？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                picking_items = []
                for _, brow in demand_df.iterrows():
                    pn2 = str(brow["part_number"]).strip()
                    pinfo = parts_map.get(pn2, {})
                    picking_items.append({
                        "part_number": pn2,
                        "name": str(brow["name"]),
                        "location": pinfo.get("location", ""),
                        "qty_needed": int(brow["total_demand"]),
                    })
                dialog = PickingListDialog(self, picking_items,
                                           title=f"拣货单 - 工单 {order_number}")
                dialog.exec()

            self.refresh_order_list()
            # 自动选中刚创建的工单（用户可直接看到预填好的消耗明细）
            for row in range(self.order_table.rowCount()):
                if self.order_table.item(row, 0).text() == order_number:
                    self.order_table.selectRow(row)
                    break
            # 通过信号通知其他选项卡库存已变动
            if hasattr(self, '_stock_changed_signal') and self._stock_changed_signal is not None:
                self._stock_changed_signal.emit()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"工单生成失败:\n{e}")
            app_log(f"[错误] 工单生成失败: {e}")

    # ---- 工单管理 ----

    def load_orders_data(self):
        """从数据库重新加载工单列表并刷新表格（保留滚动位置和选中行）。"""
        # ---- 保存当前 UI 状态 ----
        scrollbar = self.order_table.verticalScrollBar()
        saved_scroll = scrollbar.value()
        selected_id = self.current_order_id
        draft_qty = self.spin_actual_qty.value() if selected_id is not None else None
        draft_consumed = {}
        if selected_id is not None and self.spin_actual_qty.isEnabled():
            for row in range(self.order_items_table.rowCount()):
                id_item = self.order_items_table.item(row, 0)
                actual_item = self.order_items_table.item(row, 5)
                if id_item and actual_item:
                    draft_consumed[id_item.data(Qt.UserRole)] = actual_item.text()

        status = self.combo_status_filter.currentData() or ""

        orders = self.wo_repo.get_all(status_filter=status)
        self.order_table.setSortingEnabled(False)
        self.order_table.setRowCount(len(orders))
        for i, o in enumerate(orders):
            self.order_table.setItem(i, 0, QTableWidgetItem(o["order_number"]))
            self.order_table.setItem(i, 1, QTableWidgetItem(o["bom_name"]))
            pq = QTableWidgetItem(str(o["planned_qty"]))
            pq.setTextAlignment(Qt.AlignCenter)
            self.order_table.setItem(i, 2, pq)
            aq = QTableWidgetItem(str(o["actual_qty"] or "-"))
            aq.setTextAlignment(Qt.AlignCenter)
            self.order_table.setItem(i, 3, aq)

            status_label = {
                "LOCKED": "已锁定 (LOCKED)",
                "COMPLETED": "已完成 (COMPLETED)",
                "CANCELLED": "已取消 (CANCELLED)",
            }.get(o["status"], o["status"])
            status_item = QTableWidgetItem(status_label)
            if o["status"] == "LOCKED":
                status_item.setForeground(QBrush(COLOR_WARNING))
            elif o["status"] == "COMPLETED":
                status_item.setForeground(QBrush(COLOR_GREEN))
            elif o["status"] == "CANCELLED":
                status_item.setForeground(QBrush(COLOR_RED))
            self.order_table.setItem(i, 4, status_item)

            self.order_table.setItem(i, 5, QTableWidgetItem(o["created_at"] or ""))
            self.order_table.setItem(i, 6, QTableWidgetItem(o["remark"] or ""))

            # 存储 order_id 于隐藏数据
            self.order_table.item(i, 0).setData(Qt.UserRole, o["id"])

        # ---- 恢复 UI 状态 ----
        self.order_table.setSortingEnabled(True)
        self.order_table.clearSelection()
        scrollbar.setValue(min(saved_scroll, scrollbar.maximum()))
        if selected_id is not None:
            for i in range(self.order_table.rowCount()):
                if self.order_table.item(i, 0).data(Qt.UserRole) == selected_id:
                    self.order_table.selectRow(i)
                    if draft_consumed and self.spin_actual_qty.isEnabled():
                        self.spin_actual_qty.setValue(draft_qty)
                        for item_id, value in draft_consumed.items():
                            detail_row = self._order_item_row(item_id)
                            if detail_row >= 0:
                                self.order_items_table.item(detail_row, 5).setText(value)
                    break
            else:
                self._clear_order_detail()

    # 兼容别名
    def refresh_order_list(self):
        """刷新工单列表（load_orders_data 的别名）。"""
        self.load_orders_data()
        # 同步刷新 BOM 库下拉框
        self._refresh_bom_library_combo()

    def _refresh_bom_library_combo(self):
        """刷新 BOM 库快捷选择下拉框。"""
        current = self.combo_bom_library.currentText()
        self.combo_bom_library.blockSignals(True)
        self.combo_bom_library.clear()
        self.combo_bom_library.addItem("（从BOM库快捷选择）")
        for name in self.bom_repo.get_all_names():
            self.combo_bom_library.addItem(name)
        idx = self.combo_bom_library.findText(current)
        if idx >= 0:
            self.combo_bom_library.setCurrentIndex(idx)
        self.combo_bom_library.blockSignals(False)

    def _on_bom_library_selected(self, index: int):
        """从 BOM 库下拉框中选择 BOM 并加载预览。"""
        if index <= 0:
            return
        import pandas as pd
        bom_name = self.combo_bom_library.currentText()
        items = self.bom_repo.get_items_by_name(bom_name)
        if not items:
            QMessageBox.warning(self, "提示", f"BOM '{bom_name}' 没有物料项。")
            return

        data = []
        for it in items:
            data.append({
                "part_number": it["part_number"],
                "name": it["part_name"] or "",
                "quantity": it["qty_per_unit"],
                "package": it["package"] or "",
                "location": it["location"] or "",
            })
        df = pd.DataFrame(data)
        self.current_bom_df = df
        self.current_bom_path = ""
        self.current_bom_name = bom_name
        self.lbl_file.setText(f"[BOM库] {bom_name}")
        self.lbl_file.setToolTip(bom_name)
        self.chk_save_to_lib.setChecked(False)
        self.chk_save_to_lib.setEnabled(False)  # 已有，无需再保存
        self._preview_bom(df)
        app_log(f"从 BOM 库加载: {bom_name}，共 {len(items)} 种物料")

    def on_order_selected(self):
        """选中工单时，加载明细。"""
        row = self.order_table.currentRow()
        if row < 0:
            self._clear_order_detail()
            return

        order_id = self.order_table.item(row, 0).data(Qt.UserRole)
        order = self.wo_repo.get_by_id(order_id)
        if order is None:
            return

        self.current_order_id = order_id
        is_locked = order["status"] == "LOCKED"

        # 启用/禁用核销相关按钮
        self.btn_cancel_order.setEnabled(is_locked)
        self.spin_actual_qty.setEnabled(is_locked)
        self.btn_recalc_theory.setEnabled(is_locked)
        self.btn_confirm_writeoff.setEnabled(is_locked)

        if is_locked:
            self.spin_actual_qty.blockSignals(True)
            self.spin_actual_qty.setMinimum(0)
            self.spin_actual_qty.setMaximum(order["planned_qty"])
            self.spin_actual_qty.setValue(order["planned_qty"])
            self.spin_actual_qty.blockSignals(False)

        # 加载明细（LOCKED 工单自动预填理论消耗 = 锁定量）
        items = self.wo_repo.get_items(order_id)
        self.order_items_table.setSortingEnabled(False)
        self.order_items_table.setRowCount(len(items))
        for i, it in enumerate(items):
            self.order_items_table.setItem(i, 0, QTableWidgetItem(it["part_number"]))
            self.order_items_table.setItem(i, 1, QTableWidgetItem(it["part_name"]))
            self.order_items_table.setItem(i, 2, QTableWidgetItem(str(it["required_qty"])))
            self.order_items_table.setItem(i, 3, QTableWidgetItem(str(it["locked_qty"])))

            if is_locked:
                # LOCKED 工单：理论消耗 = 锁定量，实际消耗预填 = 锁定量（用户可直接核销）
                theory = it["locked_qty"]
                self.order_items_table.setItem(i, 4, QTableWidgetItem(str(theory)))
                actual_item = QTableWidgetItem(str(theory))
                actual_item.setFlags(actual_item.flags() | Qt.ItemIsEditable)
                self.order_items_table.setItem(i, 5, actual_item)
            else:
                # 已完成/已取消工单：显示历史值
                self.order_items_table.setItem(i, 4, QTableWidgetItem(str(it["actual_consumed_qty"])))
                self.order_items_table.setItem(i, 5, QTableWidgetItem(str(it["actual_consumed_qty"] or 0)))

            self.order_items_table.setItem(i, 6, QTableWidgetItem(str(it["returned_qty"] or 0)))

            # 存储明细 ID
            self.order_items_table.item(i, 0).setData(Qt.UserRole, it["id"])

        self.order_items_table.setSortingEnabled(True)

    def _clear_order_detail(self):
        """清空工单明细区域。"""
        self.current_order_id = None
        self.order_items_table.setRowCount(0)
        self.btn_confirm_writeoff.setEnabled(False)
        self.btn_cancel_order.setEnabled(False)
        self.btn_recalc_theory.setEnabled(False)
        self.spin_actual_qty.setEnabled(False)

    def _auto_calc_theory(self, order):
        """选中工单时自动预填理论消耗（按计划份数 = 实际完工计算）。
        用户无需手动点击按钮即可看到预填值。"""
        items = self.wo_repo.get_items(order["id"])
        for i, it in enumerate(items):
            # 默认：实际完工 = 计划份数，理论消耗 = 锁定量
            theory = it["locked_qty"]
            self.order_items_table.setItem(i, 4, QTableWidgetItem(str(theory)))
            # 同时预设实际消耗 = 理论消耗
            actual_item = QTableWidgetItem(str(theory))
            actual_item.setFlags(actual_item.flags() | Qt.ItemIsEditable)
            self.order_items_table.setItem(i, 5, actual_item)

    def on_recalc_theory(self):
        """按实际完工份数重新计算各物料的实际消耗（理论值）。"""
        if self.current_order_id is None:
            return

        order = self.wo_repo.get_by_id(self.current_order_id)
        if order is None or order["status"] != "LOCKED":
            return

        actual_qty = self.spin_actual_qty.value()

        items = self.wo_repo.get_items(self.current_order_id)
        ratio = actual_qty / order["planned_qty"]
        self.order_items_table.setSortingEnabled(False)
        for it in items:
            i = self._order_item_row(it["id"])
            if i < 0:
                continue
            # 理论消耗 = 锁定量 × (实际完工份数 / 计划份数)
            theory = max(0, int(it["locked_qty"] * ratio))
            self.order_items_table.setItem(i, 4, QTableWidgetItem(str(theory)))
            # 同时预设实际消耗 = 理论消耗
            actual_item = QTableWidgetItem(str(theory))
            actual_item.setFlags(actual_item.flags() | Qt.ItemIsEditable)
            self.order_items_table.setItem(i, 5, actual_item)

        self.order_items_table.setSortingEnabled(True)

        app_log(f"已重新计算理论消耗（实际完工 {actual_qty}/{order['planned_qty']} 份，比率 {ratio:.2%}）")

    def _order_item_row(self, item_id: int) -> int:
        """排序后仍按明细 ID 定位行，避免实耗写入其他物料。"""
        for row in range(self.order_items_table.rowCount()):
            item = self.order_items_table.item(row, 0)
            if item and item.data(Qt.UserRole) == item_id:
                return row
        return -1

    def on_confirm_writeoff(self):
        """确认完工核销。"""
        if self.current_order_id is None:
            return

        order = self.wo_repo.get_by_id(self.current_order_id)
        if order is None or order["status"] != "LOCKED":
            QMessageBox.warning(self, "提示", "只有 LOCKED 状态的工单才能核销。")
            return

        actual_qty = self.spin_actual_qty.value()
        if actual_qty <= 0:
            QMessageBox.warning(self, "提示", "请输入实际完工份数（大于0）。")
            return

        # 收集各物料明细的实际消耗
        items = self.wo_repo.get_items(self.current_order_id)
        writeoff_data = []  # [(item_id, part_id, actual_consumed, returned)]

        for it in items:
            i = self._order_item_row(it["id"])
            if i < 0:
                QMessageBox.warning(self, "核销失败", "工单明细显示不完整，请刷新后重试。")
                return
            try:
                actual_consumed = int(self.order_items_table.item(i, 5).text())
            except (ValueError, AttributeError):
                QMessageBox.warning(self, "实耗无效", f"{it['part_number']} 的实际消耗必须是整数。")
                self.order_items_table.setCurrentCell(i, 5)
                return
            if not 0 <= actual_consumed <= it["locked_qty"]:
                QMessageBox.warning(
                    self, "实耗超出范围",
                    f"{it['part_number']} 的实际消耗须在 0 至 {it['locked_qty']} 之间。"
                )
                self.order_items_table.setCurrentCell(i, 5)
                return
            returned = it["locked_qty"] - actual_consumed
            writeoff_data.append((it["id"], it["part_id"], actual_consumed, returned))

        # 二次确认
        total_consumed = sum(d[2] for d in writeoff_data)
        total_returned = sum(d[3] for d in writeoff_data)
        reply = QMessageBox.question(
            self, "确认核销",
            f"确认核销工单 {order['order_number']}？\n\n"
            f"  实际完工份数: {actual_qty}\n"
            f"  总消耗物料: {total_consumed} 单位\n"
            f"  总退库物料: {total_returned} 单位\n\n"
            f"此操作将实际扣减库存，不可撤销！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            # 逐项核销
            for item_id, part_id, consumed, returned in writeoff_data:
                # 更新物料库存：扣减 stock_qty + 释放 locked_qty
                self.part_repo.consume_stock(part_id, consumed, consumed + returned)

                # 更新明细
                self.wo_repo.update_item_consumption(item_id, consumed, returned)

                # 记录流水 - 消耗
                if consumed > 0:
                    trans_id = self.trans_repo.insert(
                        part_id, "WO_CONSUME", -consumed,
                        work_order_id=self.current_order_id,
                        remark=f"工单 {order['order_number']} 核销消耗"
                    )
                    self._emit_transaction(trans_id)
                # 记录流水 - 退库
                if returned > 0:
                    trans_id = self.trans_repo.insert(
                        part_id, "WO_RETURN", returned,
                        work_order_id=self.current_order_id,
                        remark=f"工单 {order['order_number']} 余料退库"
                    )
                    self._emit_transaction(trans_id)

            # 更新工单状态
            self.wo_repo.complete(self.current_order_id, actual_qty)

            app_log(f"工单 {order['order_number']} 核销完成！消耗 {total_consumed}，退库 {total_returned}")
            QMessageBox.information(self, "核销完成",
                                    f"工单 {order['order_number']} 已完成核销！\n"
                                    f"消耗: {total_consumed}, 退库: {total_returned}")

            self.refresh_order_list()
            self._clear_order_detail()

            # 通过信号通知其他选项卡库存已变动
            if hasattr(self, '_stock_changed_signal') and self._stock_changed_signal is not None:
                self._stock_changed_signal.emit()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"核销失败:\n{e}")
            app_log(f"[错误] 核销失败: {e}")

    def on_cancel_order(self):
        """取消工单，释放所有锁定库存。"""
        if self.current_order_id is None:
            return

        order = self.wo_repo.get_by_id(self.current_order_id)
        if order is None or order["status"] != "LOCKED":
            return

        reply = QMessageBox.question(
            self, "确认取消工单",
            f"确定要取消工单 {order['order_number']} 吗？\n"
            f"取消后将释放所有已锁定的库存。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            items = self.wo_repo.get_items(self.current_order_id)
            for it in items:
                # 释放锁定库存
                self.part_repo.return_stock(it["part_id"], it["locked_qty"])
                # 记录流水（退库）
                trans_id = self.trans_repo.insert(
                    it["part_id"], "WO_RETURN", it["locked_qty"],
                    work_order_id=self.current_order_id,
                    remark=f"工单 {order['order_number']} 取消，释放锁定"
                )
                self._emit_transaction(trans_id)

            self.wo_repo.cancel(self.current_order_id)
            app_log(f"工单 {order['order_number']} 已取消，库存已释放")
            self.refresh_order_list()
            self._clear_order_detail()

            if hasattr(self, '_stock_changed_signal') and self._stock_changed_signal is not None:
                self._stock_changed_signal.emit()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"取消工单失败:\n{e}")
            app_log(f"[错误] 取消工单失败: {e}")

    def refresh_all(self):
        """外部调用：刷新所有数据。"""
        self.refresh_order_list()
        # 若当前有加载的 BOM，同步刷新库存状态预览
        if self.current_bom_df is not None:
            self._preview_bom(self.current_bom_df)

    def _on_stock_changed(self):
        """库存变动时，刷新当前 BOM 预览的库存状态列。"""
        if self.current_bom_df is not None:
            self._preview_bom(self.current_bom_df)


# ============================================================
# Tab 3: 计划外领料
# ============================================================

class AdHocTab(QWidget):
    """计划外领料 / 紧急出库选项卡。"""

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.part_repo = PartRepository(db)
        self.trans_repo = TransactionRepository(db)
        self._cart_items: list[dict] = []  # 批量领料购物车

        # ---- 布局 ----
        main_layout = QVBoxLayout(self)

        # === 领料操作面板 ===
        issue_group = QGroupBox("紧急领料 / 计划外出库")
        issue_layout = QFormLayout(issue_group)

        # 物料选择行（搜索输入 + 列表）
        search_row = QHBoxLayout()
        self.part_search = QLineEdit()
        self.part_search.setPlaceholderText("输入料号或名称搜索物料...")
        self.part_search.textChanged.connect(self.on_part_search)
        search_row.addWidget(self.part_search)

        self.part_combo = QComboBox()
        self.part_combo.setMinimumWidth(300)
        self._part_cache = {}
        self.part_combo.currentIndexChanged.connect(self._update_available_label)
        search_row.addWidget(self.part_combo)
        issue_layout.addRow("选择物料:", search_row)

        # 数量输入
        qty_row = QHBoxLayout()
        self.spin_qty = QSpinBox()
        self.spin_qty.setRange(1, 9999999)
        self.spin_qty.setMinimumWidth(110)
        self.spin_qty.setToolTip("可直接输入数量，或用右侧箭头每次加减 1")
        qty_row.addWidget(self.spin_qty)

        # 快捷数量按钮
        self.qty_preset_buttons = []
        for label, qty in [("1", 1), ("5", 5), ("10", 10)]:
            btn = QPushButton(label)
            btn.setObjectName("quantityPresetButton")
            btn.setMinimumWidth(56)
            btn.setToolTip(f"快捷设置数量为 {qty}")
            btn.clicked.connect(lambda checked, v=qty: self.spin_qty.setValue(v))
            qty_row.addWidget(btn)
            self.qty_preset_buttons.append(btn)

        btn_all = QPushButton("全部")
        btn_all.setObjectName("quantityPresetButton")
        btn_all.setMinimumWidth(72)
        btn_all.setToolTip("设置为当前全部可用库存")
        btn_all.clicked.connect(self._set_qty_all_available)
        qty_row.addWidget(btn_all)
        self.btn_qty_all = btn_all

        # 显示当前可用库存
        self.lbl_available = QLabel("可用库存: -")
        self.lbl_available.setObjectName("accentValue")
        qty_row.addWidget(self.lbl_available)
        qty_row.addStretch()
        issue_layout.addRow("领用数量:", qty_row)

        # 备注（必填）
        self.edit_remark = QLineEdit()
        self.edit_remark.setPlaceholderText("请输入领用原因（必填）")
        self.edit_remark.setToolTip("例如：调试损耗、样品测试、研发实验")
        issue_layout.addRow("备注 *:", self.edit_remark)

        # 按钮行：快速领料 + 加入批量列表 + 批量模式切换
        btn_row = QHBoxLayout()
        self.chk_batch_mode = QCheckBox("批量领料模式（购物车）")
        self.chk_batch_mode.setToolTip("勾选后可将多种物料加入待领列表，一键提交全部")
        self.chk_batch_mode.toggled.connect(self._on_batch_mode_toggled)
        btn_row.addWidget(self.chk_batch_mode)
        btn_row.addStretch()
        self.btn_add_to_cart = QPushButton("＋ 添加到待领列表")
        self.btn_add_to_cart.clicked.connect(self._add_to_cart)
        self.btn_add_to_cart.setVisible(False)
        btn_row.addWidget(self.btn_add_to_cart)
        self.btn_issue = QPushButton("📤 确认领料（快速）")
        self.btn_issue.clicked.connect(self.on_issue)
        self.btn_issue.setObjectName("primaryButton")
        btn_row.addWidget(self.btn_issue)
        btn_row.addStretch()
        issue_layout.addRow(btn_row)

        main_layout.addWidget(issue_group)

        # === 待领列表（批量领料购物车） ===
        self.cart_group = QGroupBox("待领列表（批量领料）")
        self.cart_group.setVisible(False)
        cart_layout = QVBoxLayout(self.cart_group)

        self.cart_table = QTableWidget()
        self.cart_table.setColumnCount(6)
        self.cart_table.setHorizontalHeaderLabels([
            "内部料号", "名称", "可用库存", "领用数量", "备注", "移除"
        ])
        self.cart_table.horizontalHeader().setStretchLastSection(True)
        self.cart_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
            QAbstractItemView.AnyKeyPressed
        )
        self.cart_table.setAlternatingRowColors(True)
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart_table.itemChanged.connect(self._on_cart_item_changed)
        cart_layout.addWidget(self.cart_table)

        cart_btn_row = QHBoxLayout()
        self.btn_clear_cart = QPushButton("🗑 清空列表")
        self.btn_clear_cart.clicked.connect(self._clear_cart)
        cart_btn_row.addWidget(self.btn_clear_cart)
        cart_btn_row.addStretch()
        self.btn_submit_cart = QPushButton("📤 一键提交全部 (0项)")
        self.btn_submit_cart.clicked.connect(self._submit_cart)
        self.btn_submit_cart.setObjectName("primaryButton")
        cart_btn_row.addWidget(self.btn_submit_cart)
        cart_layout.addLayout(cart_btn_row)

        main_layout.addWidget(self.cart_group)

        # === 最近领料记录 ===
        recent_group = QGroupBox("最近计划外领料记录（最近 20 条）")
        recent_layout = QVBoxLayout(recent_group)

        self.recent_table = QTableWidget()
        self.recent_table.setColumnCount(6)
        self.recent_table.setHorizontalHeaderLabels([
            "流水号", "物料料号", "物料名称", "数量", "备注", "时间"
        ])
        self.recent_table.horizontalHeader().setStretchLastSection(True)
        self.recent_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.recent_table.setSortingEnabled(True)
        self.recent_table.setAlternatingRowColors(True)
        recent_layout.addWidget(self.recent_table)

        main_layout.addWidget(recent_group)

        # 初始化
        self._load_parts()
        self.refresh_recent()

        # 智能名称补全
        self.part_autocomplete = PartAutoComplete(
            self.part_search,
            self.part_repo,
            on_part_selected=self._on_autocomplete_selected,
        )

    def _load_parts(self, keyword: str = ""):
        """加载物料到下拉框。"""
        previous = self._part_cache.get(self.part_combo.currentText())
        previous_id = previous["id"] if previous else None
        self.part_combo.blockSignals(True)
        self.part_combo.clear()
        if keyword:
            parts = self.part_repo.search(keyword)
        else:
            parts = self.part_repo.get_all()

        self._part_cache = {}  # display_text -> part dict
        selected_index = -1
        for p in parts:
            available = p["stock_qty"] - p["locked_qty"]
            display = f"{p['part_number']} | {p['name'][:25]} | 可用:{available}"
            self.part_combo.addItem(display)
            self._part_cache[display] = dict(p)
            if p["id"] == previous_id:
                selected_index = self.part_combo.count() - 1

        if selected_index >= 0:
            self.part_combo.setCurrentIndex(selected_index)
        self.part_combo.blockSignals(False)

        # 更新可用库存标签
        self._update_available_label()

    def _on_autocomplete_selected(self, part: dict):
        """当用户从智能补全中选择一个物料时，同步选中下拉框中对应项。"""
        pn = part["part_number"]
        # 在下拉框中查找以该料号开头的项
        for i in range(self.part_combo.count()):
            text = self.part_combo.itemText(i)
            if text.startswith(pn + " |"):
                self.part_combo.setCurrentIndex(i)
                self._update_available_label()
                return
        # 如果下拉框中没有（搜索未过滤到），则重新加载并选中
        self._load_parts(pn)
        for i in range(self.part_combo.count()):
            text = self.part_combo.itemText(i)
            if text.startswith(pn + " |"):
                self.part_combo.setCurrentIndex(i)
                self._update_available_label()
                return

    def on_part_search(self):
        keyword = self.part_search.text().strip()
        self._load_parts(keyword)

    def _update_available_label(self):
        """更新当前选中物料的可用库存显示。"""
        current = self.part_combo.currentText()
        part = self._part_cache.get(current)
        if part:
            available = part["stock_qty"] - part["locked_qty"]
            self.lbl_available.setText(f"可用库存: {available}")
            self.spin_qty.setMaximum(max(1, available))
            self.btn_issue.setEnabled(available > 0)
            self.btn_add_to_cart.setEnabled(available > 0)
            # 库存紧张时标红
            if available <= 0:
                state = "dangerValue"
            elif available < part.get("min_stock", 0):
                state = "warningValue"
            else:
                state = "accentValue"
        else:
            self.lbl_available.setText("可用库存: -")
            self.spin_qty.setMaximum(1)
            self.btn_issue.setEnabled(False)
            self.btn_add_to_cart.setEnabled(False)
            state = "accentValue"
        self.lbl_available.setObjectName(state)
        self.lbl_available.style().unpolish(self.lbl_available)
        self.lbl_available.style().polish(self.lbl_available)

    def _set_qty_all_available(self):
        """将领用数量设置为当前选中物料的全部可用库存。"""
        current = self.part_combo.currentText()
        part = self._part_cache.get(current)
        if part:
            available = part["stock_qty"] - part["locked_qty"]
            if available > 0:
                self.spin_qty.setValue(available)

    def _emit_transaction(self, trans_id: int):
        """从数据库查询流水记录并通过信号发出，供日志界面单条追加。"""
        if hasattr(self, '_new_transaction_signal') and self._new_transaction_signal is not None:
            row = self.trans_repo.get_by_id(trans_id)
            if row:
                self._new_transaction_signal.emit(dict(row))

    def on_issue(self):
        """执行计划外领料。"""
        current = self.part_combo.currentText()
        part = self._part_cache.get(current)
        if part is None:
            QMessageBox.warning(self, "提示", "请先选择一个物料。")
            return

        qty = self.spin_qty.value()
        available = part["stock_qty"] - part["locked_qty"]
        if qty > available:
            QMessageBox.warning(
                self, "库存不足",
                f"物料 {part['part_number']} 可用库存不足！\n"
                f"  可用库存: {available}\n"
                f"  领用数量: {qty}\n"
                f"  差额: {qty - available}"
            )
            return

        remark = self.edit_remark.text().strip()
        if not remark:
            QMessageBox.warning(self, "提示", "备注为必填项！请填写领用原因。")
            self.edit_remark.setFocus()
            return

        # 二次确认
        reply = QMessageBox.question(
            self, "确认计划外领料",
            f"确认以下计划外领料操作？\n\n"
            f"  物料: {part['part_number']} {part['name']}\n"
            f"  领用数量: {qty}\n"
            f"  可用库存（操作前）: {available}\n"
            f"  备注: {remark}\n\n"
            f"此操作将直接扣减物理库存！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            # 扣减库存
            self.part_repo.adhoc_issue(part["id"], qty)

            # 记录流水
            trans_id = self.trans_repo.insert(
                part["id"], "AD_HOC", -qty,
                remark=f"计划外领料: {remark}"
            )
            self._emit_transaction(trans_id)

            app_log(f"计划外领料完成: {part['part_number']} × {qty}（备注: {remark}）")
            QMessageBox.information(
                self, "完成",
                f"已领用 {part['part_number']} × {qty}\n"
                f"库位: {part.get('location', '-')}\n"
                f"请前往对应库位取料。"
            )

            # 重置输入
            self.spin_qty.setValue(1)
            self.edit_remark.clear()
            self.part_search.blockSignals(True)
            self.part_search.clear()
            self.part_search.blockSignals(False)
            self._load_parts()
            self.refresh_recent()

            # 通过信号通知其他选项卡库存已变动
            if hasattr(self, '_stock_changed_signal') and self._stock_changed_signal is not None:
                self._stock_changed_signal.emit()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"领料失败:\n{e}")
            app_log(f"[错误] 计划外领料失败: {e}")

    # ---- 批量领料购物车 ----

    def _on_batch_mode_toggled(self, checked: bool):
        """切换批量领料模式的购物车显示。"""
        self.cart_group.setVisible(checked)
        self.btn_add_to_cart.setVisible(checked)
        if checked:
            self.btn_issue.setText("📤 确认领料（快速）")

    def _add_to_cart(self):
        """将当前搜索区选中的物料加入待领列表。"""
        current = self.part_combo.currentText()
        part = self._part_cache.get(current)
        if part is None:
            QMessageBox.warning(self, "提示", "请先选择一个物料。")
            return

        qty = self.spin_qty.value()
        available = part["stock_qty"] - part["locked_qty"]
        if qty > available:
            QMessageBox.warning(
                self, "库存不足",
                f"物料 {part['part_number']} 可用库存不足！\n"
                f"  可用库存: {available}\n"
                f"  领用数量: {qty}"
            )
            return

        remark = self.edit_remark.text().strip()
        if not remark:
            QMessageBox.warning(self, "提示", "备注为必填项！请填写领用原因。")
            self.edit_remark.setFocus()
            return

        # 检查是否已存在（同一物料则更新数量和备注）
        for item in self._cart_items:
            if item["part_id"] == part["id"]:
                item["qty"] = qty
                item["remark"] = remark
                item["available"] = available
                self._refresh_cart_table()
                app_log(f"更新待领列表: {part['part_number']} × {qty}")
                # 重置输入
                self.spin_qty.setValue(1)
                self.edit_remark.clear()
                self.part_search.clear()
                self._load_parts()
                return

        self._cart_items.append({
            "part_id": part["id"],
            "part_number": part["part_number"],
            "name": part["name"],
            "available": available,
            "qty": qty,
            "remark": remark,
        })
        self._refresh_cart_table()
        app_log(f"加入待领列表: {part['part_number']} × {qty}（备注: {remark}）")

        # 重置输入，方便搜索下一个物料
        self.spin_qty.setValue(1)
        self.edit_remark.clear()
        self.part_search.clear()
        self._load_parts()

    def _refresh_cart_table(self):
        """刷新待领列表表格。"""
        self.cart_table.blockSignals(True)
        self.cart_table.setRowCount(len(self._cart_items))
        for i, item in enumerate(self._cart_items):
            self.cart_table.setItem(i, 0, QTableWidgetItem(item["part_number"]))
            self.cart_table.setItem(i, 1, QTableWidgetItem(item["name"]))
            avail_item = QTableWidgetItem(str(item["available"]))
            avail_item.setTextAlignment(Qt.AlignCenter)
            # 库存不足时标红
            if item["qty"] > item["available"]:
                avail_item.setForeground(QBrush(COLOR_RED))
            elif item["available"] <= 0:
                avail_item.setForeground(QBrush(COLOR_RED))
            self.cart_table.setItem(i, 2, avail_item)

            qty_item = QTableWidgetItem(str(item["qty"]))
            qty_item.setTextAlignment(Qt.AlignCenter)
            qty_item.setFlags(qty_item.flags() | Qt.ItemIsEditable)
            self.cart_table.setItem(i, 3, qty_item)

            remark_item = QTableWidgetItem(item["remark"])
            remark_item.setFlags(remark_item.flags() | Qt.ItemIsEditable)
            self.cart_table.setItem(i, 4, remark_item)

            # 移除按钮
            btn_remove = QPushButton("✕")
            btn_remove.setFixedSize(24, 24)
            btn_remove.setToolTip(f"移除 {item['part_number']}")
            btn_remove.clicked.connect(lambda checked, idx=i: self._remove_from_cart(idx))
            self.cart_table.setCellWidget(i, 5, btn_remove)

        self.cart_table.blockSignals(False)
        # 更新提交按钮文本
        total_qty = sum(item["qty"] for item in self._cart_items)
        self.btn_submit_cart.setText(f"📤 一键提交全部 ({len(self._cart_items)}项, 共{total_qty})")

    def _on_cart_item_changed(self, item: QTableWidgetItem):
        """当用户在待领列表中编辑数量或备注时，同步到 _cart_items。"""
        row = item.row()
        col = item.column()
        if row < 0 or row >= len(self._cart_items):
            return
        try:
            if col == 3:  # 数量
                new_qty = int(item.text())
                if new_qty <= 0:
                    new_qty = 1
                    self.cart_table.blockSignals(True)
                    item.setText("1")
                    self.cart_table.blockSignals(False)
                self._cart_items[row]["qty"] = new_qty
            elif col == 4:  # 备注
                self._cart_items[row]["remark"] = item.text().strip()
        except ValueError:
            pass
        # 更新提交按钮
        total_qty = sum(i["qty"] for i in self._cart_items)
        self.btn_submit_cart.setText(f"📤 一键提交全部 ({len(self._cart_items)}项, 共{total_qty})")

    def _remove_from_cart(self, index: int):
        """从待领列表中移除指定项。"""
        if 0 <= index < len(self._cart_items):
            removed = self._cart_items.pop(index)
            app_log(f"从待领列表移除: {removed['part_number']}")
            self._refresh_cart_table()

    def _clear_cart(self):
        """清空待领列表。"""
        if not self._cart_items:
            return
        reply = QMessageBox.question(
            self, "确认清空",
            f"确定要清空待领列表中的所有 {len(self._cart_items)} 项吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._cart_items.clear()
            self._refresh_cart_table()
            app_log("待领列表已清空")

    def _submit_cart(self):
        """一键提交待领列表中的所有物料领用。"""
        if not self._cart_items:
            QMessageBox.warning(self, "提示", "待领列表为空，请先添加物料。")
            return

        # 检查库存是否仍然充足
        insufficient = []
        for item in self._cart_items:
            part = self.part_repo.get_by_id(item["part_id"])
            if part is None:
                insufficient.append(f"{item['part_number']} — 物料已删除")
            else:
                available = part["stock_qty"] - part["locked_qty"]
                if item["qty"] > available:
                    insufficient.append(
                        f"{item['part_number']} — 需求 {item['qty']}, 可用 {available}"
                    )

        if insufficient:
            QMessageBox.warning(
                self, "库存不足",
                "以下物料当前库存不足，请调整数量：\n\n" + "\n".join(insufficient)
            )
            # 刷新购物车中的可用库存
            self._refresh_cart_available()
            return

        # 汇总确认
        total_qty = sum(item["qty"] for item in self._cart_items)
        lines = "\n".join(
            f"  • {it['part_number']} {it['name'][:20]} × {it['qty']}（{it['remark']}）"
            for it in self._cart_items
        )
        reply = QMessageBox.question(
            self, "确认批量领料",
            f"即将一次性提交以下 {len(self._cart_items)} 种物料的领料操作：\n\n"
            f"{lines}\n\n"
            f"总数量: {total_qty}\n"
            f"此操作将直接扣减物理库存，不可撤销！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 逐项执行
        success, failed = [], []
        remaining = []
        for item in self._cart_items:
            try:
                self.part_repo.adhoc_issue(item["part_id"], item["qty"])
                trans_id = self.trans_repo.insert(
                    item["part_id"], "AD_HOC", -item["qty"],
                    remark=f"批量领料: {item['remark']}"
                )
                self._emit_transaction(trans_id)
                success.append(f"{item['part_number']} × {item['qty']}")
                app_log(f"批量领料完成: {item['part_number']} × {item['qty']}（备注: {item['remark']}）")
            except Exception as e:
                failed.append(f"{item['part_number']}: {e}")
                remaining.append(item)
                app_log(f"[错误] 批量领料失败 {item['part_number']}: {e}")

        # 结果汇总
        msg = f"批量领料结果：\n\n成功 {len(success)} 项\n"
        if failed:
            msg += f"失败 {len(failed)} 项:\n" + "\n".join(f"  • {f}" for f in failed)
        QMessageBox.information(self, "批量领料完成", msg)

        # 保留失败项，便于修正后重新提交。
        self._cart_items = remaining
        self._refresh_cart_table()
        self.refresh_recent()
        self.part_search.blockSignals(True)
        self.part_search.clear()
        self.part_search.blockSignals(False)
        self._load_parts()

        if hasattr(self, '_stock_changed_signal') and self._stock_changed_signal is not None:
            self._stock_changed_signal.emit()

    def _refresh_cart_available(self):
        """刷新待领列表中各物料的可用库存（在库存变动时调用）。"""
        for item in self._cart_items:
            part = self.part_repo.get_by_id(item["part_id"])
            if part:
                item["available"] = part["stock_qty"] - part["locked_qty"]
        self._refresh_cart_table()

    def load_recent_data(self):
        """从数据库重新加载最近领料记录并刷新表格（保留滚动位置）。"""
        # ---- 保存当前 UI 状态 ----
        scrollbar = self.recent_table.verticalScrollBar()
        saved_scroll = scrollbar.value()
        saved_row = self.recent_table.currentRow()

        transactions = self.trans_repo.get_all(trans_type="AD_HOC")
        # 取最近 20 条
        transactions = transactions[:20]

        self.recent_table.setSortingEnabled(False)
        self.recent_table.setRowCount(len(transactions))
        for i, t in enumerate(transactions):
            self.recent_table.setItem(i, 0, QTableWidgetItem(str(t["id"])))
            self.recent_table.setItem(i, 1, QTableWidgetItem(t["part_number"]))
            self.recent_table.setItem(i, 2, QTableWidgetItem(t["part_name"]))
            self.recent_table.setItem(i, 3, QuantityTableItem(t["quantity"]))
            self.recent_table.setItem(i, 4, QTableWidgetItem(t["remark"] or ""))
            self.recent_table.setItem(i, 5, QTableWidgetItem(t["created_at"] or ""))

        # ---- 恢复 UI 状态 ----
        self.recent_table.setSortingEnabled(True)
        scrollbar.setValue(min(saved_scroll, scrollbar.maximum()))
        if saved_row >= 0 and saved_row < self.recent_table.rowCount():
            self.recent_table.selectRow(saved_row)

    # 兼容别名
    def refresh_recent(self):
        """刷新最近领料记录（load_recent_data 的别名）。"""
        self.load_recent_data()

    def refresh_all(self):
        """外部调用：刷新所有数据。"""
        self._load_parts()
        self.load_recent_data()
        self._refresh_cart_available()

    def _on_stock_changed(self):
        """库存变动时，刷新物料列表中的库存数字和待领列表可用库存。"""
        # 保存当前选中物料的料号
        current_pn = None
        current = self.part_combo.currentText()
        if current in self._part_cache:
            current_pn = self._part_cache[current]["part_number"]
        # 重新加载物料列表
        self._load_parts(self.part_search.text().strip())
        # 恢复选中
        if current_pn:
            for i in range(self.part_combo.count()):
                if self.part_combo.itemText(i).startswith(current_pn + " |"):
                    self.part_combo.setCurrentIndex(i)
                    break
        self._update_available_label()
        # 刷新待领列表中的可用库存
        self._refresh_cart_available()


# ============================================================
# Tab 4: 出入库日志
# ============================================================

class TransactionLogTab(QWidget):
    """出入库日志选项卡：流水查询、筛选、统计。"""

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.trans_repo = TransactionRepository(db)

        # ---- 布局 ----
        main_layout = QVBoxLayout(self)

        # === 筛选栏 ===
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("物料料号:"))
        self.filter_pn = QLineEdit()
        self.filter_pn.setPlaceholderText("模糊搜索...")
        self.filter_pn.returnPressed.connect(self.refresh_table)
        filter_layout.addWidget(self.filter_pn)

        filter_layout.addWidget(QLabel("操作类型:"))
        self.filter_type = QComboBox()
        self.filter_type.addItems([
            "全部", "INBOUND", "OUTBOUND", "WO_LOCK",
            "WO_CONSUME", "WO_RETURN", "AD_HOC", "ADJUSTMENT"
        ])
        filter_layout.addWidget(self.filter_type)

        filter_layout.addWidget(QLabel("开始日期:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))  # 默认一个月前
        filter_layout.addWidget(self.date_from)

        filter_layout.addWidget(QLabel("结束日期:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        filter_layout.addWidget(self.date_to)

        self.btn_search = QPushButton("🔍 搜索")
        self.btn_search.clicked.connect(self.refresh_table)
        filter_layout.addWidget(self.btn_search)

        self.btn_reset = QPushButton("重置")
        self.btn_reset.clicked.connect(self.on_reset_filter)
        filter_layout.addWidget(self.btn_reset)

        filter_layout.addStretch()
        main_layout.addLayout(filter_layout)

        # === 流水表格 ===
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "流水号", "物料料号", "物料名称", "操作类型",
            "变动数量", "关联工单", "备注", "操作时间"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        main_layout.addWidget(self.table)

        # === 底部统计栏 ===
        stats_layout = QHBoxLayout()
        self.lbl_total = QLabel("共 0 条记录")
        stats_layout.addWidget(self.lbl_total)
        stats_layout.addStretch()

        self.lbl_in = QLabel("入库合计: 0")
        self.lbl_in.setObjectName("positiveTotal")
        stats_layout.addWidget(self.lbl_in)

        self.lbl_out = QLabel("出库合计: 0")
        self.lbl_out.setObjectName("negativeTotal")
        stats_layout.addWidget(self.lbl_out)

        stats_layout.addStretch()

        self.btn_export_log = QPushButton("📤 导出日志")
        self.btn_export_log.clicked.connect(self.on_export_log)
        stats_layout.addWidget(self.btn_export_log)

        main_layout.addLayout(stats_layout)

        # 初始化
        self.refresh_table()

    def on_export_log(self):
        """导出当前筛选的流水记录到 Excel。"""
        pn = self.filter_pn.text().strip()
        ttype = self.filter_type.currentText()
        if ttype == "全部":
            ttype = ""
        d_from = self.date_from.date().toString("yyyy-MM-dd")
        d_to = self.date_to.date().toString("yyyy-MM-dd")

        rows = self.trans_repo.get_all(
            part_number=pn, trans_type=ttype,
            date_from=d_from, date_to=d_to,
        )
        if not rows:
            QMessageBox.information(self, "提示", "当前无数据可导出！")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出流水日志",
            os.path.join(os.path.dirname(database_module.DB_PATH), "流水日志导出.xlsx"),
            "Excel 文件 (*.xlsx)"
        )
        if not file_path:
            return

        import pandas as pd
        data = []
        for r in rows:
            data.append({
                "流水号": r["id"],
                "物料料号": r["part_number"],
                "物料名称": r["part_name"],
                "操作类型": r["transaction_type"],
                "变动数量": r["quantity"],
                "关联工单": str(r["work_order_id"] or ""),
                "备注": r["remark"] or "",
                "操作时间": r["created_at"],
            })
        df = pd.DataFrame(data)
        df.to_excel(file_path, index=False, engine="openpyxl")
        app_log(f"日志导出: {len(rows)} 条记录 -> {file_path}")
        QMessageBox.information(self, "导出成功",
                                f"已导出 {len(rows)} 条记录至:\n{file_path}")

    def load_transactions_data(self):
        """从数据库重新加载流水记录并刷新表格（保留滚动位置和选中行）。"""
        # ---- 保存当前 UI 状态 ----
        scrollbar = self.table.verticalScrollBar()
        saved_scroll = scrollbar.value()
        selected_item = self.table.item(self.table.currentRow(), 0)
        selected_id = selected_item.text() if selected_item else None

        pn = self.filter_pn.text().strip()
        ttype = self.filter_type.currentText()
        if ttype == "全部":
            ttype = ""
        d_from = self.date_from.date().toString("yyyy-MM-dd")
        d_to = self.date_to.date().toString("yyyy-MM-dd")

        rows = self.trans_repo.get_all(
            part_number=pn,
            trans_type=ttype,
            date_from=d_from,
            date_to=d_to,
        )

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        total_in = 0
        total_out = 0

        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r["id"])))
            self.table.setItem(i, 1, QTableWidgetItem(r["part_number"]))
            self.table.setItem(i, 2, QTableWidgetItem(r["part_name"]))

            # 操作类型着色
            ttype_item = QTableWidgetItem(r["transaction_type"])
            if r["transaction_type"] in ("INBOUND", "WO_RETURN"):
                ttype_item.setForeground(QBrush(COLOR_GREEN))
            elif r["transaction_type"] in ("OUTBOUND", "WO_LOCK", "WO_CONSUME", "AD_HOC"):
                ttype_item.setForeground(QBrush(COLOR_RED))
            elif r["transaction_type"] == "ADJUSTMENT":
                # 库存修正：根据正负着色
                if r["quantity"] > 0:
                    ttype_item.setForeground(QBrush(COLOR_GREEN))
                else:
                    ttype_item.setForeground(QBrush(COLOR_RED))
            self.table.setItem(i, 3, ttype_item)

            # 数量着色（正绿色/负红色）
            qty = r["quantity"]
            self.table.setItem(i, 4, QuantityTableItem(qty))

            # 关联工单
            self.table.setItem(i, 5, QTableWidgetItem(str(r["work_order_id"] or "-")))

            self.table.setItem(i, 6, QTableWidgetItem(r["remark"] or ""))
            self.table.setItem(i, 7, QTableWidgetItem(r["created_at"] or ""))

            # 累加统计
            if qty > 0:
                total_in += qty
            else:
                total_out += abs(qty)

        self.lbl_total.setText(f"共 {len(rows)} 条记录")
        self.lbl_in.setText(f"入库合计: +{total_in}")
        self.lbl_out.setText(f"出库合计: -{total_out}")

        # ---- 恢复 UI 状态 ----
        self.table.setSortingEnabled(True)
        scrollbar.setValue(min(saved_scroll, scrollbar.maximum()))
        if selected_id:
            for i in range(self.table.rowCount()):
                if self.table.item(i, 0).text() == selected_id:
                    self.table.selectRow(i)
                    break

    def insert_transaction_row(self, transaction: dict):
        """
        单条追加一条流水记录到表格顶部（不重新加载全表）。
        用于操作后实时显示新流水，避免全量刷新带来的闪烁。
        仅在当前筛选条件为「全部 + 无搜索词 + 默认日期范围」时生效，
        否则走全量刷新以保证筛选结果正确。
        """
        # 仅当筛选条件为默认状态时才单条追加（否则走全量刷新）
        has_filter = (
            self.filter_pn.text().strip() or
            self.filter_type.currentText() != "全部" or
            not (
                self.date_from.date().toString("yyyy-MM-dd")
                <= str(transaction.get("created_at", ""))[:10]
                <= self.date_to.date().toString("yyyy-MM-dd")
            )
        )
        if has_filter:
            self.load_transactions_data()
            return

        # 在表格顶部插入新行
        self.table.setSortingEnabled(False)
        self.table.insertRow(0)

        r = transaction
        self.table.setItem(0, 0, QTableWidgetItem(str(r["id"])))
        self.table.setItem(0, 1, QTableWidgetItem(r["part_number"]))
        self.table.setItem(0, 2, QTableWidgetItem(r["part_name"]))

        # 操作类型着色
        ttype_item = QTableWidgetItem(r["transaction_type"])
        if r["transaction_type"] in ("INBOUND", "WO_RETURN"):
            ttype_item.setForeground(QBrush(COLOR_GREEN))
        elif r["transaction_type"] in ("OUTBOUND", "WO_LOCK", "WO_CONSUME", "AD_HOC"):
            ttype_item.setForeground(QBrush(COLOR_RED))
        elif r["transaction_type"] == "ADJUSTMENT":
            if r["quantity"] > 0:
                ttype_item.setForeground(QBrush(COLOR_GREEN))
            else:
                ttype_item.setForeground(QBrush(COLOR_RED))
        self.table.setItem(0, 3, ttype_item)

        # 数量
        self.table.setItem(0, 4, QuantityTableItem(r["quantity"]))

        self.table.setItem(0, 5, QTableWidgetItem(str(r.get("work_order_id", "-") or "-")))
        self.table.setItem(0, 6, QTableWidgetItem(r.get("remark", "") or ""))
        self.table.setItem(0, 7, QTableWidgetItem(r.get("created_at", "") or ""))
        self.table.setSortingEnabled(True)

        # 更新统计标签（从标签文本中解析并更新）
        try:
            current_total = int(self.lbl_total.text().replace("共 ", "").replace(" 条记录", ""))
            current_in = int(self.lbl_in.text().replace("入库合计: +", ""))
            current_out = int(self.lbl_out.text().replace("出库合计: -", ""))
        except (ValueError, AttributeError):
            current_total = 0
            current_in = 0
            current_out = 0

        current_total += 1
        qty = r["quantity"]
        if qty > 0:
            current_in += qty
        else:
            current_out += abs(qty)

        self.lbl_total.setText(f"共 {current_total} 条记录")
        self.lbl_in.setText(f"入库合计: +{current_in}")
        self.lbl_out.setText(f"出库合计: -{current_out}")

        # 滚动到顶部以显示新插入的记录
        self.table.verticalScrollBar().setValue(0)

    # 兼容别名
    def refresh_table(self):
        """刷新流水日志表格（load_transactions_data 的别名）。"""
        self.load_transactions_data()

    def on_reset_filter(self):
        """重置筛选条件。"""
        self.filter_pn.clear()
        self.filter_type.setCurrentIndex(0)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_to.setDate(QDate.currentDate())
        self.refresh_table()

    def refresh_all(self):
        """外部调用：刷新所有数据。"""
        self.refresh_table()


# ============================================================
# Tab 5: BOM 管理（新建 / 编辑 / 导出 BOM 结构）
# ============================================================

class BomManageTab(QWidget):
    """BOM 管理选项卡：新建、编辑、删除、导出 BOM 物料清单。"""

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.bom_repo = BomRepository(db)
        self.part_repo = PartRepository(db)
        self.current_bom_name = None   # 当前正在编辑的 BOM 名称
        self._is_dirty = False         # 明细是否有未保存修改

        # ---- 主布局：左右分栏 ----
        main_layout = QHBoxLayout(self)

        # === 左侧面板：BOM 列表 ===
        left_panel = QWidget()
        left_panel.setFixedWidth(280)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("本地 BOM 库"))

        # 搜索框
        self.bom_search = QLineEdit()
        self.bom_search.setPlaceholderText("搜索 BOM 名称...")
        self.bom_search.textChanged.connect(self.refresh_bom_list)
        left_layout.addWidget(self.bom_search)

        # BOM 列表
        self.bom_list = QListWidget()
        self.bom_list.currentItemChanged.connect(self.on_bom_selected)
        left_layout.addWidget(self.bom_list)

        # 操作按钮
        left_btn_layout = QHBoxLayout()
        self.btn_new_bom = QPushButton("＋ 新建")
        self.btn_new_bom.clicked.connect(self.on_new_bom)
        left_btn_layout.addWidget(self.btn_new_bom)

        self.btn_delete_bom = QPushButton("✕ 删除")
        self.btn_delete_bom.clicked.connect(self.on_delete_bom)
        self.btn_delete_bom.setEnabled(False)
        left_btn_layout.addWidget(self.btn_delete_bom)

        left_layout.addLayout(left_btn_layout)

        self.btn_rename_bom = QPushButton("✎ 重命名")
        self.btn_rename_bom.clicked.connect(self.on_rename_bom)
        self.btn_rename_bom.setEnabled(False)
        left_layout.addWidget(self.btn_rename_bom)

        main_layout.addWidget(left_panel)

        # === 右侧面板：BOM 明细编辑 ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        self.lbl_bom_title = QLabel("请选择或新建一个 BOM")
        self.lbl_bom_title.setObjectName("resultSummary")
        right_layout.addWidget(self.lbl_bom_title)

        # 明细表格（可编辑）
        self.items_table = QTableWidget()
        self.items_table.setColumnCount(5)
        self.items_table.setHorizontalHeaderLabels([
            "内部料号", "物料名称", "单份用量", "封装（自动）", "备注"
        ])
        self.items_table.horizontalHeader().setStretchLastSection(True)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.itemChanged.connect(self._on_item_changed)
        right_layout.addWidget(self.items_table)

        # 明细操作按钮
        item_btn_layout = QHBoxLayout()

        self.btn_add_row = QPushButton("＋ 添加物料行")
        self.btn_add_row.clicked.connect(self.on_add_row)
        self.btn_add_row.setEnabled(False)
        item_btn_layout.addWidget(self.btn_add_row)

        self.btn_delete_row = QPushButton("✕ 删除选中行")
        self.btn_delete_row.clicked.connect(self.on_delete_row)
        self.btn_delete_row.setEnabled(False)
        item_btn_layout.addWidget(self.btn_delete_row)

        item_btn_layout.addStretch()

        self.btn_save_bom = QPushButton("💾 保存 BOM")
        self.btn_save_bom.clicked.connect(self.on_save_bom)
        self.btn_save_bom.setEnabled(False)
        self.btn_save_bom.setObjectName("primaryButton")
        item_btn_layout.addWidget(self.btn_save_bom)

        self.btn_export_bom = QPushButton("📤 导出为 Excel")
        self.btn_export_bom.clicked.connect(self.on_export_bom)
        self.btn_export_bom.setEnabled(False)
        self.btn_export_bom.setObjectName("primaryButton")
        item_btn_layout.addWidget(self.btn_export_bom)

        right_layout.addLayout(item_btn_layout)

        # 提示信息
        self.lbl_hint = QLabel("提示：双击「物料名称」列可从下拉列表中选择物料")
        self.lbl_hint.setObjectName("mutedText")
        right_layout.addWidget(self.lbl_hint)

        main_layout.addWidget(right_panel, 1)

        # 初始化
        self.refresh_bom_list()

    # ---- BOM 列表操作 ----

    def load_bom_list_data(self):
        """从数据库重新加载 BOM 名称列表（保留当前选中项）。"""
        # ---- 保存当前选中 ----
        saved_name = self.current_bom_name

        keyword = self.bom_search.text().strip()
        if keyword:
            names = self.bom_repo.find_by_name(keyword)
        else:
            names = self.bom_repo.get_all_names()

        self.bom_list.clear()
        saved_item = None
        for name in names:
            item = QListWidgetItem(name)
            self.bom_list.addItem(item)
            if name == saved_name:
                saved_item = item

        # ---- 恢复选中项 ----
        if saved_item:
            self.bom_list.setCurrentItem(saved_item)

    # 兼容别名
    def refresh_bom_list(self):
        """刷新 BOM 列表（load_bom_list_data 的别名）。"""
        self.load_bom_list_data()

    def on_bom_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        """选中 BOM 时加载明细到右侧表格。"""
        if current is None:
            self._clear_detail()
            return

        bom_name = current.text()
        self.current_bom_name = bom_name
        self.lbl_bom_title.setText(f"📋 {bom_name}")
        self._is_dirty = False

        items = self.bom_repo.get_items_by_name(bom_name)
        self._load_items_to_table(items)

        # 启用按钮
        self.btn_delete_bom.setEnabled(True)
        self.btn_rename_bom.setEnabled(True)
        self.btn_add_row.setEnabled(True)
        self.btn_delete_row.setEnabled(True)
        self.btn_export_bom.setEnabled(True)
        self.btn_save_bom.setEnabled(False)  # 加载后未修改，无需保存

        # 禁止在选中 BOM 后修改 BOM 名称（防止外键冲突的显示混乱）
        self.bom_search.setEnabled(False)

    def _clear_detail(self):
        """清空右侧明细面板。"""
        self.current_bom_name = None
        self.lbl_bom_title.setText("请选择或新建一个 BOM")
        self.items_table.setRowCount(0)
        self._is_dirty = False
        self.btn_delete_bom.setEnabled(False)
        self.btn_rename_bom.setEnabled(False)
        self.btn_add_row.setEnabled(False)
        self.btn_delete_row.setEnabled(False)
        self.btn_save_bom.setEnabled(False)
        self.btn_export_bom.setEnabled(False)
        self.bom_search.setEnabled(True)

    def _load_items_to_table(self, items):
        """将 BOM 明细加载到右侧表格。"""
        self.items_table.blockSignals(True)  # 加载期间不触发 itemChanged 信号
        self.items_table.setRowCount(len(items))
        for i, it in enumerate(items):
            # 料号
            pn_item = QTableWidgetItem(it["part_number"])
            pn_item.setFlags(pn_item.flags() & ~Qt.ItemIsEditable)  # 料号不可编辑
            pn_item.setData(Qt.UserRole, it["id"])  # 存储 bom_items.id
            self.items_table.setItem(i, 0, pn_item)

            # 名称（自动从 parts 表展示）
            name_item = QTableWidgetItem(it["part_name"] or "")
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.items_table.setItem(i, 1, name_item)

            # 单份用量（可编辑）
            qty_item = QTableWidgetItem()
            qty_item.setData(Qt.EditRole, it["qty_per_unit"])
            self.items_table.setItem(i, 2, qty_item)

            # 封装（自动显示，不可编辑）
            pkg_item = QTableWidgetItem(it["package"] or "")
            pkg_item.setFlags(pkg_item.flags() & ~Qt.ItemIsEditable)
            self.items_table.setItem(i, 3, pkg_item)

            # 备注（可编辑）
            remark_item = QTableWidgetItem(it["remark"] or "")
            self.items_table.setItem(i, 4, remark_item)
        self.items_table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem):
        """明细表格内容变更时标记为脏数据。"""
        self._is_dirty = True
        self.btn_save_bom.setEnabled(True)

    # ---- BOM 增删改 ----

    def on_new_bom(self):
        """新建 BOM。"""
        name, ok = self._prompt_bom_name("新建 BOM", "请输入新 BOM 的名称：")
        if not ok or not name:
            return

        # 检查是否已存在
        existing = self.bom_repo.get_items_by_name(name)
        if existing:
            QMessageBox.warning(self, "名称冲突", f"BOM「{name}」已存在，请使用其他名称。")
            return

        self.current_bom_name = name
        self._is_dirty = False
        self.lbl_bom_title.setText(f"📝 新建: {name}（尚未保存）")
        self.items_table.setRowCount(0)

        self.btn_delete_bom.setEnabled(False)
        self.btn_rename_bom.setEnabled(False)
        self.btn_add_row.setEnabled(True)
        self.btn_delete_row.setEnabled(True)
        self.btn_save_bom.setEnabled(True)
        self.btn_export_bom.setEnabled(False)
        self.bom_search.setEnabled(False)

        app_log(f"开始新建 BOM: {name}")

    def on_delete_bom(self):
        """删除整个 BOM。"""
        if self.current_bom_name is None:
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 BOM「{self.current_bom_name}」及其所有明细吗？\n此操作不可撤销！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.bom_repo.delete_bom(self.current_bom_name)
        app_log(f"BOM「{self.current_bom_name}」已删除")
        self._clear_detail()
        self.refresh_bom_list()

    def on_rename_bom(self):
        """重命名 BOM。"""
        if self.current_bom_name is None:
            return

        new_name, ok = self._prompt_bom_name(
            "重命名 BOM",
            f"请输入新名称（当前: {self.current_bom_name}）：",
            self.current_bom_name
        )
        if not ok or not new_name or new_name == self.current_bom_name:
            return

        self.bom_repo.rename_bom(self.current_bom_name, new_name)
        app_log(f"BOM「{self.current_bom_name}」已重命名为「{new_name}」")
        self.current_bom_name = new_name
        self.lbl_bom_title.setText(f"📋 {new_name}")
        self.refresh_bom_list()

    # ---- 物料行操作 ----

    def on_add_row(self):
        """在明细中添加一行新物料。"""
        if self.current_bom_name is None:
            return

        # 弹出物料选择对话框
        dialog = PartSelectDialog(self, self.part_repo)
        if dialog.exec() != QDialog.Accepted:
            return

        part = dialog.get_selected_part()
        if part is None:
            return

        qty, ok = self._prompt_int("用量", f"请输入「{part['part_number']}」的单份用量：", 1)
        if not ok:
            return

        row = self.items_table.rowCount()
        self.items_table.insertRow(row)

        pn_item = QTableWidgetItem(part["part_number"])
        pn_item.setFlags(pn_item.flags() & ~Qt.ItemIsEditable)
        pn_item.setData(Qt.UserRole, -1)  # -1 表示新增行，尚未写入数据库
        self.items_table.setItem(row, 0, pn_item)

        name_item = QTableWidgetItem(part["name"])
        name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
        self.items_table.setItem(row, 1, name_item)

        qty_item = QTableWidgetItem()
        qty_item.setData(Qt.EditRole, qty)
        self.items_table.setItem(row, 2, qty_item)

        pkg_item = QTableWidgetItem(part["package"] or "")
        pkg_item.setFlags(pkg_item.flags() & ~Qt.ItemIsEditable)
        self.items_table.setItem(row, 3, pkg_item)

        remark_item = QTableWidgetItem("")
        self.items_table.setItem(row, 4, remark_item)

        self._is_dirty = True
        self.btn_save_bom.setEnabled(True)

    def on_delete_row(self):
        """删除选中的物料行。"""
        row = self.items_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在明细表格中选中要删除的行。")
            return

        pn = self.items_table.item(row, 0).text()
        self.items_table.removeRow(row)
        self._is_dirty = True
        self.btn_save_bom.setEnabled(True)
        app_log(f"从 BOM 中移除物料: {pn}")

    # ---- 保存与导出 ----

    def on_save_bom(self):
        """保存 BOM 明细到数据库。"""
        if self.current_bom_name is None:
            return

        # 收集表格中的数据
        new_items = []  # (part_number, qty_per_unit, remark)
        for row in range(self.items_table.rowCount()):
            pn = self.items_table.item(row, 0).text().strip() if self.items_table.item(row, 0) else ""
            if not pn:
                continue
            try:
                qty = int(self.items_table.item(row, 2).data(Qt.EditRole)) if self.items_table.item(row, 2) else 1
            except (ValueError, TypeError):
                qty = 1
            remark = self.items_table.item(row, 4).text().strip() if self.items_table.item(row, 4) else ""
            new_items.append((pn, qty, remark))

        if not new_items:
            QMessageBox.warning(self, "提示", "BOM 至少需要一行物料。")
            return

        try:
            # 删除旧明细，重新插入（全量替换策略）
            self.bom_repo.delete_bom(self.current_bom_name)
            for pn, qty, remark in new_items:
                self.bom_repo.insert_item(self.current_bom_name, pn, qty, remark)

            self._is_dirty = False
            self.btn_save_bom.setEnabled(False)
            self.btn_export_bom.setEnabled(True)
            self.lbl_bom_title.setText(f"📋 {self.current_bom_name}")
            app_log(f"BOM「{self.current_bom_name}」保存成功，共 {len(new_items)} 行物料")

            # 刷新列表（如果是新建的 BOM）
            self.refresh_bom_list()

            QMessageBox.information(self, "保存成功",
                                    f"BOM「{self.current_bom_name}」已保存\n共 {len(new_items)} 种物料")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存 BOM 时发生错误:\n{e}")
            app_log(f"[错误] 保存 BOM 失败: {e}")

    def on_export_bom(self):
        """导出 BOM 为 Excel。"""
        if self.current_bom_name is None:
            return

        default_name = f"{self.current_bom_name}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出 BOM 为 Excel",
            os.path.join(os.path.dirname(database_module.DB_PATH), default_name),
            "Excel 文件 (*.xlsx)"
        )
        if not file_path:
            return

        try:
            count = self.bom_repo.export_to_excel(self.current_bom_name, file_path)
            app_log(f"BOM「{self.current_bom_name}」已导出至 {file_path}（{count} 行）")
            QMessageBox.information(self, "导出成功",
                                    f"BOM 已导出至:\n{file_path}\n共 {count} 种物料")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出时发生错误:\n{e}")

    # ---- 辅助 ----

    def _prompt_bom_name(self, title: str, label: str, default: str = ""):
        """弹出输入框获取 BOM 名称。"""
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, title, label, text=default)
        if ok and name:
            name = name.strip()
        return name, ok

    def _prompt_int(self, title: str, label: str, default: int = 1):
        """弹出输入框获取整数。"""
        from PySide6.QtWidgets import QInputDialog
        value, ok = QInputDialog.getInt(self, title, label, default, 1, 9999999, 1)
        return value, ok

    def refresh_all(self):
        """外部调用：刷新 BOM 列表。"""
        self.refresh_bom_list()
        if self.current_bom_name:
            items = self.bom_repo.get_items_by_name(self.current_bom_name)
            self._load_items_to_table(items)


# ============================================================
# 物料选择对话框（供 BOM 编辑使用）
# ============================================================

class PartSelectDialog(QDialog):
    """从物料库中选择物料的对话框。"""

    def __init__(self, parent, part_repo: PartRepository):
        super().__init__(parent)
        self.setWindowTitle("选择物料")
        self.setMinimumSize(550, 400)
        self.part_repo = part_repo

        layout = QVBoxLayout(self)

        # 搜索
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入料号或名称...")
        self.search_input.textChanged.connect(self._do_search)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["内部料号", "名称", "封装", "可用库存"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        # 确认 / 取消
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._do_search()

    def _do_search(self):
        keyword = self.search_input.text().strip()
        if keyword:
            parts = self.part_repo.search(keyword)
        else:
            parts = self.part_repo.get_all()

        self.table.setRowCount(len(parts))
        for i, p in enumerate(parts):
            self.table.setItem(i, 0, QTableWidgetItem(p["part_number"]))
            self.table.setItem(i, 1, QTableWidgetItem(p["name"]))
            self.table.setItem(i, 2, QTableWidgetItem(p["package"] or ""))
            avail = QTableWidgetItem(str(p["available_qty"]))
            avail.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 3, avail)
            # 存储完整数据
            self.table.item(i, 0).setData(Qt.UserRole, dict(p))

    def get_selected_part(self) -> dict:
        """获取当前选中物料的数据。"""
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.UserRole)


# ============================================================
# 主窗口
# ============================================================

class MainWindow(QMainWindow):
    """主窗口：承载所有功能选项卡和底部日志区域。"""

    # 库存变动信号：当任何操作导致库存变化时发出，各选项卡监听后自动刷新
    stock_changed = Signal()
    # 新交易信号：携带交易记录字典，供日志界面单条追加（避免全量刷新）
    new_transaction = Signal(dict)

    def __init__(self, db: DatabaseManager,
                 theme_preferences: ThemePreferences = None):
        super().__init__()
        self.db = db
        self.theme_preferences = theme_preferences or ThemeManager.load()
        self.theme_colors = ThemeManager.apply(QApplication.instance(),
                                                self.theme_preferences)
        set_semantic_colors(self.theme_colors)

        # 窗口基本设置
        self.setWindowTitle("物料库存与 BOM 核销管理系统 v1.0")
        self.resize(1440, 900)
        self.setMinimumSize(1000, 650)

        # ---- 中央组件 ----
        central = BackgroundWidget()
        central.setObjectName("centralRoot")
        central.set_appearance(self.theme_preferences)
        self.background_widget = central
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(14, 14, 14, 10)
        root_layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("appHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 13, 20, 13)
        title_layout = QVBoxLayout()
        title = QLabel("物料库存工作台")
        title.setObjectName("appTitle")
        title_layout.addWidget(title)
        subtitle = QLabel("库存、BOM 工单与领料，一处完成")
        subtitle.setObjectName("appSubtitle")
        title_layout.addWidget(subtitle)
        header_layout.addLayout(title_layout)
        header_layout.addStretch()

        self.btn_quick_add = QPushButton("＋ 新增物料")
        self.btn_quick_add.setObjectName("headerButton")
        header_layout.addWidget(self.btn_quick_add)
        self.btn_quick_bom = QPushButton("导入 BOM")
        self.btn_quick_bom.setObjectName("headerButton")
        header_layout.addWidget(self.btn_quick_bom)
        self.btn_quick_issue = QPushButton("计划外领料")
        self.btn_quick_issue.setObjectName("headerButton")
        header_layout.addWidget(self.btn_quick_issue)
        self.btn_appearance = QPushButton("外观设置")
        self.btn_appearance.setObjectName("headerButton")
        self.btn_appearance.clicked.connect(self.open_appearance_settings)
        header_layout.addWidget(self.btn_appearance)
        root_layout.addWidget(header)

        # ---- 选项卡 ----
        self.tabs = QTabWidget()

        self.dashboard_tab = DashboardTab(db, self.theme_colors)
        self.parts_tab = PartsTab(db)
        self.bom_tab = BOMTab(db)
        self.bom_manage_tab = BomManageTab(db)
        self.adhoc_tab = AdHocTab(db)
        self.log_tab = TransactionLogTab(db)

        # 将信号注入到各子选项卡（解耦跨模块刷新）
        for tab in [self.dashboard_tab, self.parts_tab, self.bom_tab,
                     self.bom_manage_tab, self.adhoc_tab, self.log_tab]:
            tab._stock_changed_signal = self.stock_changed
            tab._new_transaction_signal = self.new_transaction

        # 当库存变动时，自动刷新所有相关选项卡
        self.stock_changed.connect(self.dashboard_tab.refresh_all)
        self.stock_changed.connect(self.parts_tab.refresh_table)
        self.stock_changed.connect(self.bom_tab._on_stock_changed)
        self.stock_changed.connect(self.bom_tab.refresh_order_list)
        self.stock_changed.connect(self.adhoc_tab._on_stock_changed)
        self.stock_changed.connect(self.log_tab.refresh_table)

        # 新交易产生时，单条追加到日志表格顶部
        self.new_transaction.connect(self.log_tab.insert_transaction_row)

        self.tabs.addTab(self.dashboard_tab, "📈 数据看板")
        self.tabs.addTab(self.parts_tab, "📦 物料管理")
        self.tabs.addTab(self.bom_tab, "📋 BOM 导入与核销")
        self.tabs.addTab(self.bom_manage_tab, "📐 BOM 管理")
        self.tabs.addTab(self.adhoc_tab, "🚨 计划外领料")
        self.tabs.addTab(self.log_tab, "📊 出入库日志")

        self.btn_quick_add.clicked.connect(self._quick_add_part)
        self.btn_quick_bom.clicked.connect(lambda: self.tabs.setCurrentWidget(self.bom_tab))
        self.btn_quick_issue.clicked.connect(self._quick_issue)
        self.dashboard_tab.low_stock_requested.connect(self._show_low_stock)

        # 选项卡切换时自动刷新对应页面
        self.tabs.currentChanged.connect(self.on_tab_changed)

        root_layout.addWidget(self.tabs, 1)

        # ---- 底部日志区域 ----
        log_frame = QFrame()
        log_frame.setObjectName("activityPanel")
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(4, 4, 4, 4)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("操作记录"))
        log_header.addStretch()

        self.btn_toggle_log = QPushButton("展开记录")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.toggled.connect(self._toggle_log)
        log_header.addWidget(self.btn_toggle_log)

        self.btn_clear_log = QPushButton("清空日志")
        self.btn_clear_log.clicked.connect(self.clear_log)
        self.btn_clear_log.setVisible(False)
        log_header.addWidget(self.btn_clear_log)
        log_layout.addLayout(log_header)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(150)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setVisible(False)
        log_layout.addWidget(self.log_area)

        root_layout.addWidget(log_frame)

        # 注册全局日志控件
        global _log_widget
        _log_widget = self.log_area

        # 启动日志
        app_log("==== 系统启动 ====")
        app_log(f"数据库路径: {database_module.DB_PATH}")

        # 状态栏
        self._status_label = QLabel()
        self.statusBar().addPermanentWidget(self._status_label, 1)
        self._update_status_bar()

        # 库存变动时也更新状态栏
        self.stock_changed.connect(self._update_status_bar)

    def _quick_add_part(self):
        self.tabs.setCurrentWidget(self.parts_tab)
        self.parts_tab.on_add_part()

    def _quick_issue(self):
        self.tabs.setCurrentWidget(self.adhoc_tab)
        self.adhoc_tab.part_search.setFocus()

    def _show_low_stock(self):
        self.tabs.setCurrentWidget(self.parts_tab)
        self.parts_tab.filter_stock.setCurrentText("低库存")

    def _toggle_log(self, expanded: bool):
        self.log_area.setVisible(expanded)
        self.btn_clear_log.setVisible(expanded)
        self.btn_toggle_log.setText("收起记录" if expanded else "展开记录")

    def open_appearance_settings(self):
        dialog = ThemeSettingsDialog(self.theme_preferences, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.theme_preferences = dialog.preferences
        ThemeManager.save(self.theme_preferences)
        self.theme_colors = ThemeManager.apply(QApplication.instance(),
                                               self.theme_preferences)
        set_semantic_colors(self.theme_colors)
        self.background_widget.set_appearance(self.theme_preferences)
        self.dashboard_tab.apply_theme(self.theme_colors)
        self.parts_tab.refresh_table()
        self.bom_tab.refresh_all()
        self.adhoc_tab.refresh_all()
        self.log_tab.refresh_all()

    def _update_status_bar(self):
        """更新状态栏：显示物料总数和数据库路径。"""
        try:
            row = self.db.fetch_one("SELECT COUNT(*) AS cnt FROM parts")
            part_count = row["cnt"] if row else 0
            db_name = os.path.basename(database_module.DB_PATH)
            self._status_label.setText(
                f"就绪 | 物料: {part_count} 种 | 数据库: {db_name}"
            )
        except Exception:
            self._status_label.setText("就绪")

    def on_tab_changed(self, index: int):
        """选项卡切换时，刷新当前页面数据。"""
        tab = self.tabs.widget(index)
        if hasattr(tab, "refresh_all"):
            tab.refresh_all()
        self._update_status_bar()

    def refresh_all_tabs(self):
        """刷新所有选项卡的数据（供各子模块调用）。"""
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if hasattr(tab, "refresh_all"):
                tab.refresh_all()

    def clear_log(self):
        """清空日志区域。"""
        self.log_area.clear()
        app_log("日志已清空")

    # ---- 窗口关闭事件（安全退出） ----

    def closeEvent(self, event: QCloseEvent):
        """
        重写关闭事件：
        1. 执行 JSON 备份
        2. 安全断开数据库连接
        3. 退出应用程序
        """
        app_log("正在关闭系统...")

        # ---- 步骤 1: 执行 JSON 备份 ----
        try:
            backup_dir = os.path.join(os.path.dirname(database_module.DB_PATH), "Backups")
            success = execute_backup(database_module.DB_PATH, backup_dir, log_callback=app_log)

            if success:
                # 保留最近 30 份，避免频繁启动时丢失历史恢复点。
                cleanup_old_backups(backup_dir, keep_count=30)
            else:
                app_log("[警告] JSON 备份未成功完成，但不阻断退出流程。")
        except Exception as e:
            app_log(f"[备份异常] 备份过程发生异常: {e}，继续退出。")

        # ---- 步骤 2: 断开数据库连接 ----
        app_log("正在断开数据库连接...")
        try:
            self.db.close()
            app_log("数据库连接已安全关闭。")
        except Exception as e:
            app_log(f"[错误] 关闭数据库时发生异常: {e}")

        # ---- 步骤 3: 接受关闭事件 ----
        app_log("==== 系统退出 ====")
        event.accept()


# ============================================================
# 程序入口
# ============================================================

def main():
    """主程序入口。"""
    # 启动 Qt 应用程序
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # 跨平台一致风格

    # 全局字体设置
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)

    # First launch: choose the database/backup folder. Cancel means exe folder.
    try:
        db_path = database_path_for_startup()
        db = init_database(str(db_path))
    except Exception as exc:
        QMessageBox.critical(None, "启动失败", f"无法打开应用数据：\n{exc}")
        return 1

    # 创建并显示主窗口
    window = MainWindow(db)
    window.show()

    # 进入事件循环
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
