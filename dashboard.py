"""
数据看板模块 (Dashboard)
========================
功能：展示库存总览、低库存预警、消耗排行等统计信息。
以 QGroupBox 卡片 + 表格的形式展示关键指标。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QAbstractItemView, QFrame, QPushButton,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont

from database import DatabaseManager, PartRepository, TransactionRepository
from theme_manager import ThemeManager, ThemePreferences

# ---- 颜色常量 ----
COLOR_GREEN = QColor(0, 150, 0)
COLOR_RED = QColor(220, 30, 30)
COLOR_BLUE = QColor(41, 128, 185)

class DashboardTab(QWidget):
    """数据看板选项卡：库存总览 + 低库存预警 + 消耗排行。"""

    low_stock_requested = Signal()

    def __init__(self, db: DatabaseManager, theme_colors: dict = None):
        super().__init__()
        self.db = db
        self.theme_colors = theme_colors or ThemeManager.colors(ThemePreferences())
        self.part_repo = PartRepository(db)
        self.trans_repo = TransactionRepository(db)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        heading = QHBoxLayout()
        intro = QLabel("库存概况")
        intro.setObjectName("dashboardHeading")
        heading.addWidget(intro)
        heading.addStretch()
        self.btn_view_low = QPushButton("查看低库存物料 →")
        self.btn_view_low.clicked.connect(self.low_stock_requested.emit)
        heading.addWidget(self.btn_view_low)
        main_layout.addLayout(heading)

        # === 第一行：概览卡片（4个指标） ===
        overview_layout = QHBoxLayout()

        self.card_value = self._make_card("库存总价值", "¥ 0.00", "所有物料的当前库存金额估值")
        overview_layout.addWidget(self.card_value, 1)

        self.card_count = self._make_card("物料种类", "0", "系统中录入的物料种类总数")
        overview_layout.addWidget(self.card_count, 1)

        self.card_low = self._make_card("低库存预警", "0", "可用库存低于安全库存的物料数")
        overview_layout.addWidget(self.card_low, 1)

        self.card_consume = self._make_card("本月核销数量", "0", "本月工单核销消耗的物料总数量")
        overview_layout.addWidget(self.card_consume, 1)

        main_layout.addLayout(overview_layout)

        # === 第二行：表格区域（左：低库存明细 / 右：消耗排行） ===
        table_layout = QHBoxLayout()

        # -- 左侧：低库存明细 --
        low_group = QGroupBox("低库存物料明细")
        low_layout = QVBoxLayout(low_group)

        self.low_table = QTableWidget()
        self.low_table.setColumnCount(6)
        self.low_table.setHorizontalHeaderLabels([
            "内部料号", "名称", "库位", "可用库存", "安全库存", "供应商"
        ])
        self.low_table.horizontalHeader().setStretchLastSection(True)
        self.low_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.low_table.setSortingEnabled(True)
        self.low_table.setAlternatingRowColors(True)
        self.low_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        low_layout.addWidget(self.low_table)
        table_layout.addWidget(low_group, 3)

        # -- 右侧：消耗排行 --
        consume_group = QGroupBox("Top 10 消耗排行 (本月)")
        consume_layout = QVBoxLayout(consume_group)

        self.consume_table = QTableWidget()
        self.consume_table.setColumnCount(3)
        self.consume_table.setHorizontalHeaderLabels([
            "内部料号", "名称", "消耗量"
        ])
        self.consume_table.horizontalHeader().setStretchLastSection(True)
        self.consume_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.consume_table.setSortingEnabled(True)
        self.consume_table.setAlternatingRowColors(True)
        self.consume_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        consume_layout.addWidget(self.consume_table)
        table_layout.addWidget(consume_group, 2)

        main_layout.addLayout(table_layout, 1)

        # 初始加载
        self.refresh_all()

    def _make_card(self, title: str, value: str, hint: str) -> QGroupBox:
        """创建一个 QGroupBox 统计卡片。"""
        card = QGroupBox(title)
        card.setMinimumHeight(100)

        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignCenter)

        lbl_value = QLabel(value)
        lbl_value.setAlignment(Qt.AlignCenter)
        lbl_value.setObjectName("cardValue")
        layout.addWidget(lbl_value)

        lbl_hint = QLabel(hint)
        lbl_hint.setAlignment(Qt.AlignCenter)
        lbl_hint.setObjectName("cardHint")
        layout.addWidget(lbl_hint)

        return card

    def _set_card_value(self, card: QGroupBox, text: str):
        """更新卡片中的数值标签。"""
        lbl = card.findChild(QLabel, "cardValue")
        if lbl:
            lbl.setText(text)

    def apply_theme(self, colors: dict):
        self.theme_colors = colors
        self.refresh_all()

    def refresh_all(self):
        """刷新所有统计数据（保留表格滚动位置和选中行）。"""
        # ---- 保存当前 UI 状态 ----
        low_scrollbar = self.low_table.verticalScrollBar()
        low_saved_scroll = low_scrollbar.value()
        low_saved_row = self.low_table.currentRow()

        consume_scrollbar = self.consume_table.verticalScrollBar()
        consume_saved_scroll = consume_scrollbar.value()
        consume_saved_row = self.consume_table.currentRow()

        # ---- 1. 基础数据 ----
        all_parts = self.part_repo.get_all()

        # 库存总价值
        total_value = sum(
            (p["stock_qty"] or 0) * (p["unit_price"] or 0)
            for p in all_parts
        )
        self._set_card_value(self.card_value, f"¥ {total_value:,.2f}")

        # 物料种类数
        self._set_card_value(self.card_count, str(len(all_parts)))

        # ---- 2. 低库存预警 ----
        low_stock = [
            p for p in all_parts
            if (p["stock_qty"] - p["locked_qty"]) < p["min_stock"]
        ]
        low_count = len(low_stock)
        self._set_card_value(self.card_low, str(low_count))
        lbl = self.card_low.findChild(QLabel, "cardValue")
        if lbl:
            lbl.setProperty("alert", "true" if low_count else "false")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

        # 低库存明细表
        self.low_table.setSortingEnabled(False)
        self.low_table.setRowCount(len(low_stock))
        for i, p in enumerate(low_stock):
            available = p["stock_qty"] - p["locked_qty"]
            self.low_table.setItem(i, 0, QTableWidgetItem(p["part_number"]))
            self.low_table.setItem(i, 1, QTableWidgetItem(p["name"]))
            self.low_table.setItem(i, 2, QTableWidgetItem(p["location"] or "-"))
            avail_item = QTableWidgetItem(str(available))
            avail_item.setForeground(QColor(self.theme_colors["danger"]))
            self.low_table.setItem(i, 3, avail_item)
            self.low_table.setItem(i, 4, QTableWidgetItem(str(p["min_stock"])))
            supplier = p["supplier_name"] or "-"
            self.low_table.setItem(i, 5, QTableWidgetItem(supplier))
        self.low_table.setSortingEnabled(True)

        # ---- 3. 本月消耗 Top 10 ----
        now = datetime.now()
        month_start = now.strftime("%Y-%m-01")
        month_end = now.strftime("%Y-%m-%d") + " 23:59:59"

        all_trans = self.trans_repo.get_all(
            trans_type="WO_CONSUME",
            date_from=month_start,
            date_to=month_end,
        )

        # 按 part_number 聚合消耗量
        consume_map: dict = {}
        for t in all_trans:
            pn = t["part_number"]
            if pn not in consume_map:
                consume_map[pn] = {
                    "part_number": pn,
                    "name": t["part_name"],
                    "count": 0,
                }
            consume_map[pn]["count"] += abs(t["quantity"])

        top10 = sorted(consume_map.values(), key=lambda x: x["count"], reverse=True)[:10]

        self.consume_table.setSortingEnabled(False)
        self.consume_table.setRowCount(len(top10))
        for i, item in enumerate(top10):
            self.consume_table.setItem(i, 0, QTableWidgetItem(item["part_number"]))
            self.consume_table.setItem(i, 1, QTableWidgetItem(item["name"]))
            cnt_item = QTableWidgetItem(str(item["count"]))
            cnt_item.setTextAlignment(Qt.AlignCenter)
            self.consume_table.setItem(i, 2, cnt_item)
        self.consume_table.setSortingEnabled(True)

        # 本月消耗总次数（汇总所有物料的消耗，非仅 Top 10）
        total_consume = sum(item["count"] for item in consume_map.values())
        self._set_card_value(self.card_consume, str(total_consume))

        # ---- 恢复 UI 状态 ----
        low_scrollbar.setValue(min(low_saved_scroll, low_scrollbar.maximum()))
        if low_saved_row >= 0 and low_saved_row < self.low_table.rowCount():
            self.low_table.selectRow(low_saved_row)

        consume_scrollbar.setValue(min(consume_saved_scroll, consume_scrollbar.maximum()))
        if consume_saved_row >= 0 and consume_saved_row < self.consume_table.rowCount():
            self.consume_table.selectRow(consume_saved_row)
