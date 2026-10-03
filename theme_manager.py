"""Persistent light/dark appearance settings and contrast-safe Qt styling."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QPalette, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QColorDialog, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from app_paths import config_store, resource_directory


DEFAULTS = {
    "light": {"accent": "#2878bd", "background": "#f5f7fb"},
    "dark": {"accent": "#4d9ee8", "background": "#101827"},
}


def _valid_color(value: str, fallback: str) -> str:
    color = QColor(value)
    return color.name() if color.isValid() else fallback


def _luminance(value: str) -> float:
    channels = [QColor(value).redF(), QColor(value).greenF(), QColor(value).blueF()]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
              for v in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    a, b = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _mix(first: str, second: str, amount: float) -> str:
    a, b = QColor(first), QColor(second)
    return QColor(
        round(a.red() * (1 - amount) + b.red() * amount),
        round(a.green() * (1 - amount) + b.green() * amount),
        round(a.blue() * (1 - amount) + b.blue() * amount),
    ).name()


def _readable_accent(accent: str, surface: str) -> str:
    """Keep user-selected accents readable as text on either surface."""
    target = "#111827" if _luminance(surface) > 0.35 else "#ffffff"
    for step in range(21):
        candidate = _mix(accent, target, step / 20)
        if _contrast(candidate, surface) >= 4.5:
            return candidate
    return target


@dataclass
class ThemePreferences:
    mode: str = "light"
    accent: dict = field(default_factory=lambda: {
        mode: values["accent"] for mode, values in DEFAULTS.items()
    })
    background: dict = field(default_factory=lambda: {
        mode: values["background"] for mode, values in DEFAULTS.items()
    })
    image: dict = field(default_factory=lambda: {"light": "", "dark": ""})

    def clone(self) -> "ThemePreferences":
        return ThemePreferences(self.mode, self.accent.copy(),
                                self.background.copy(), self.image.copy())


class ThemeManager:
    """Read/write user preferences and apply a complete palette and stylesheet."""

    @staticmethod
    def load(store: QSettings = None) -> ThemePreferences:
        if store is None:
            store = config_store()
            # Bring existing Windows registry appearance choices into the new
            # portable config the first time this version starts.
            if not store.contains("appearance/mode"):
                legacy = QSettings("ComponentInventory", "InventorySystem")
                if legacy.contains("appearance/mode"):
                    migrated = ThemeManager.load(legacy)
                    ThemeManager.save(migrated, store)
                    return migrated
        prefs = ThemePreferences()
        mode = str(store.value("appearance/mode", "light"))
        prefs.mode = mode if mode in DEFAULTS else "light"
        for name in DEFAULTS:
            prefs.accent[name] = _valid_color(
                str(store.value(f"appearance/{name}/accent", DEFAULTS[name]["accent"])),
                DEFAULTS[name]["accent"],
            )
            prefs.background[name] = _valid_color(
                str(store.value(f"appearance/{name}/background", DEFAULTS[name]["background"])),
                DEFAULTS[name]["background"],
            )
            prefs.image[name] = str(store.value(f"appearance/{name}/image", "") or "")
        return prefs

    @staticmethod
    def save(prefs: ThemePreferences, store: QSettings = None):
        store = store if store is not None else config_store()
        store.setValue("appearance/mode", prefs.mode)
        for name in DEFAULTS:
            store.setValue(f"appearance/{name}/accent", prefs.accent[name])
            store.setValue(f"appearance/{name}/background", prefs.background[name])
            store.setValue(f"appearance/{name}/image", prefs.image[name])
        store.sync()

    @staticmethod
    def colors(prefs: ThemePreferences) -> dict:
        dark = prefs.mode == "dark"
        accent = _valid_color(prefs.accent[prefs.mode], DEFAULTS[prefs.mode]["accent"])
        colors = {
            "background": _valid_color(prefs.background[prefs.mode],
                                       DEFAULTS[prefs.mode]["background"]),
            "panel": "#1c2838" if dark else "#ffffff",
            "input": "#172334" if dark else "#ffffff",
            "text": "#edf3fb" if dark else "#172b4d",
            "muted": "#b9c9dd" if dark else "#52647e",
            "line": "#3a4d64" if dark else "#cbd6e4",
            "header": "#0d2038" if dark else "#172b4d",
            "header_text": "#ffffff",
            "tab_hover": "#263b54" if dark else "#edf4fc",
            "button": "#293c52" if dark else "#eef3f9",
            "button_hover": "#38516e" if dark else "#e0ecf8",
            "button_text": "#ecf3fb" if dark else "#264360",
            "disabled": "#263243" if dark else "#f2f4f7",
            "disabled_text": "#a8b8cc" if dark else "#79889c",
            "table_alt": "#223148" if dark else "#f8fafd",
            "table_header": "#293c54" if dark else "#edf3fa",
            "selection": "#345a7d" if dark else "#dbeeff",
            "selection_text": "#ffffff" if dark else "#183b5d",
            "success": "#50d79b" if dark else "#147d52",
            "warning": "#ffd27a" if dark else "#9a5a00",
            "danger": "#ff8989" if dark else "#b83d3d",
            "danger_bg": "#54363d" if dark else "#ffe6e6",
            "accent": accent,
        }
        colors["accent_text"] = _readable_accent(accent, colors["panel"])
        colors["accent_on"] = "#111827" if _contrast("#111827", accent) >= _contrast("#ffffff", accent) else "#ffffff"
        colors["accent_hover"] = _mix(accent, "#ffffff" if dark else "#111827", 0.13)
        has_image = bool(prefs.image[prefs.mode] and os.path.isfile(prefs.image[prefs.mode]))
        colors["header_fill"] = "rgba(13, 32, 56, 220)" if has_image else colors["header"]
        colors["pane_fill"] = (
            "rgba(28, 40, 56, 238)" if dark else "rgba(255, 255, 255, 238)"
        ) if has_image else colors["panel"]
        suffix = "dark" if dark else "light"
        asset_dir = os.path.join(str(resource_directory()), "theme_assets")
        colors["spin_up_icon"] = 'url("' + os.path.join(
            asset_dir, f"arrow_up_{suffix}.svg"
        ).replace("\\", "/") + '")'
        colors["spin_down_icon"] = 'url("' + os.path.join(
            asset_dir, f"arrow_down_{suffix}.svg"
        ).replace("\\", "/") + '")'
        return colors

    @staticmethod
    def apply(app: QApplication, prefs: ThemePreferences) -> dict:
        colors = ThemeManager.colors(prefs)
        palette = QPalette()
        roles = {
            QPalette.Window: colors["background"],
            QPalette.WindowText: colors["text"],
            QPalette.Base: colors["input"],
            QPalette.AlternateBase: colors["table_alt"],
            QPalette.Text: colors["text"],
            QPalette.Button: colors["button"],
            QPalette.ButtonText: colors["button_text"],
            QPalette.Highlight: colors["accent"],
            QPalette.HighlightedText: colors["accent_on"],
            QPalette.ToolTipBase: colors["header"],
            QPalette.ToolTipText: "#ffffff",
            QPalette.PlaceholderText: colors["muted"],
        }
        for role, value in roles.items():
            palette.setColor(role, QColor(value))
        palette.setColor(QPalette.Disabled, QPalette.Text, QColor(colors["disabled_text"]))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(colors["disabled_text"]))
        app.setPalette(palette)
        app.setStyleSheet(ThemeManager.stylesheet(prefs))
        return colors

    @staticmethod
    def stylesheet(prefs: ThemePreferences) -> str:
        return _build_stylesheet(ThemeManager.colors(prefs))


def _build_stylesheet(c: dict) -> str:
    style = """
QWidget { color: @text@; }
QMainWindow, QDialog { background: @background@; }
QFrame#appHeader { background: @header_fill@; border-radius: 12px; }
QFrame#activityPanel { background: @panel@; border: 1px solid @line@; border-radius: 8px; }
QLabel#appTitle { color: @header_text@; font-size: 20px; font-weight: 700; }
QLabel#appSubtitle { color: #b9c9e4; font-size: 12px; }
QLabel#sectionHint, QLabel#mutedText { color: @muted@; font-size: 12px; }
QLabel#resultSummary { color: @text@; font-weight: 600; }
QLabel#dashboardHeading { color: @text@; font-size: 17px; font-weight: 700; }
QLabel#cardValue { color: @accent_text@; font-size: 28px; font-weight: 700; }
QLabel#cardValue[alert="true"] { color: @danger@; }
QLabel#cardHint { color: @muted@; font-size: 11px; }
QLabel#successValue, QLabel#positiveTotal { color: @success@; font-weight: 700; }
QLabel#dangerValue, QLabel#negativeTotal { color: @danger@; font-weight: 700; }
QLabel#warningValue { color: @warning@; font-weight: 700; }
QLabel#accentValue { color: @accent_text@; font-weight: 700; }
QLabel#partNumberPreview {
    color: @accent_text@; background: @tab_hover@; border: 1px solid @line@;
    border-radius: 4px; padding: 6px 10px; font-weight: 700;
}
QLabel#fileDisplay {
    background: @input@; color: @text@; border: 1px solid @line@;
    border-radius: 6px; padding: 6px 9px; min-height: 18px;
}
QTabWidget::pane {
    background: @pane_fill@; border: 1px solid @line@; border-radius: 9px; top: -1px;
}
QTabBar { background: @panel@; border-radius: 6px; }
QTabBar::tab {
    background: transparent; color: @muted@; padding: 10px 15px;
    margin-right: 3px; border-bottom: 3px solid transparent; font-weight: 600;
}
QTabBar::tab:hover { color: @accent_text@; background: @tab_hover@; }
QTabBar::tab:selected { color: @accent_text@; border-bottom-color: @accent_text@; }
QGroupBox {
    background: @panel@; border: 1px solid @line@; border-radius: 9px;
    margin-top: 13px; padding-top: 12px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: @text@; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTextEdit, QListWidget {
    background: @input@; color: @text@; border: 1px solid @line@;
    border-radius: 6px; padding: 5px 7px;
    selection-background-color: @accent@; selection-color: @accent_on@;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QDateEdit:focus, QTextEdit:focus, QListWidget:focus { border-color: @accent@; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {
    background: @disabled@; color: @disabled_text@;
}
QCheckBox:disabled, QRadioButton:disabled { color: @disabled_text@; }
QComboBox::drop-down {
    background: @button@; border-left: 1px solid @line@; width: 21px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QDateEdit::up-button, QDateEdit::down-button {
    background: @button@; border-left: 1px solid @line@; width: 17px;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QDateEdit::up-arrow {
    image: @spin_up_icon@; width: 12px; height: 8px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QDateEdit::down-arrow {
    image: @spin_down_icon@; width: 12px; height: 8px;
}
QComboBox QAbstractItemView, QComboBox QListView {
    background: @input@; color: @text@; border: 1px solid @line@;
    selection-background-color: @accent@; selection-color: @accent_on@;
    outline: 0; padding: 2px;
}
QComboBox QAbstractItemView::item { background: @input@; color: @text@; min-height: 24px; padding: 3px 7px; }
QComboBox QAbstractItemView::item:selected { background: @accent@; color: @accent_on@; }
QPushButton {
    background: @button@; color: @button_text@; border: 1px solid @line@;
    border-radius: 6px; padding: 6px 12px; font-weight: 600;
}
QPushButton:hover { background: @button_hover@; border-color: @accent@; }
QPushButton:pressed { background: @selection@; }
QPushButton:disabled { background: @disabled@; color: @disabled_text@; border-color: @line@; }
QPushButton#primaryButton { background: @accent@; color: @accent_on@; border-color: @accent@; }
QPushButton#primaryButton:hover { background: @accent_hover@; border-color: @accent_hover@; }
QPushButton#primaryButton:disabled { background: @disabled@; color: @disabled_text@; border-color: @line@; }
QPushButton#dangerButton { color: @danger@; border-color: @danger@; }
QPushButton#headerButton { background: @button@; color: @button_text@; border-color: @line@; }
QPushButton#headerButton:hover { background: @button_hover@; }
QPushButton#quantityPresetButton { padding: 6px 8px; }
QTableWidget {
    background: @panel@; color: @text@; alternate-background-color: @table_alt@;
    gridline-color: @line@; border: 1px solid @line@; border-radius: 6px;
    selection-background-color: @selection@; selection-color: @selection_text@;
}
QTableWidget::item:selected { background: @selection@; color: @selection_text@; }
QHeaderView { background: @table_header@; color: @text@; }
QHeaderView::section, QTableCornerButton::section {
    background: @table_header@; color: @text@; border: 0;
    border-right: 1px solid @line@; border-bottom: 1px solid @line@;
    padding: 7px 8px; font-weight: 600;
}
QTableWidget QTableCornerButton::section { background: @table_header@; }
QScrollBar:vertical, QScrollBar:horizontal { background: @panel@; border: 0; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: @line@; border-radius: 4px; min-height: 20px; min-width: 20px;
}
QScrollBar::add-line, QScrollBar::sub-line { background: none; border: 0; }
QMenu { background: @panel@; color: @text@; border: 1px solid @line@; }
QMenu::item:selected { background: @accent@; color: @accent_on@; }
QStatusBar { background: @button@; color: @text@; border-top: 1px solid @line@; }
QToolTip { background: @header@; color: #ffffff; border: 0; padding: 5px; }
"""
    for name, value in c.items():
        style = style.replace(f"@{name}@", value)
    return style


class BackgroundWidget(QWidget):
    """Paint the selected background image behind opaque content panels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._background = QColor(DEFAULTS["light"]["background"])
        self._image = QPixmap()

    def set_appearance(self, prefs: ThemePreferences):
        self._background = QColor(prefs.background[prefs.mode])
        path = prefs.image[prefs.mode]
        self._image = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._background)
        if not self._image.isNull():
            scaled = self._image.scaled(self.size(), Qt.KeepAspectRatioByExpanding,
                                        Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)


class ThemeSettingsDialog(QDialog):
    """Edit light and dark palettes independently before saving changes."""

    def __init__(self, preferences: ThemePreferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle("界面外观")
        self.setMinimumWidth(510)
        self._draft = preferences.clone()
        self._mode = self._draft.mode

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("亮色模式", "light")
        self.mode_combo.addItem("暗色模式", "dark")
        self.mode_combo.setCurrentIndex(0 if self._mode == "light" else 1)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        form.addRow("显示模式:", self.mode_combo)

        self.accent_button = QPushButton()
        self.accent_button.clicked.connect(self._choose_accent)
        form.addRow("界面强调色:", self.accent_button)

        self.background_button = QPushButton()
        self.background_button.clicked.connect(self._choose_background)
        form.addRow("背景颜色:", self.background_button)

        image_row = QHBoxLayout()
        self.image_path = QLineEdit()
        self.image_path.setReadOnly(True)
        self.image_path.setPlaceholderText("未设置背景图片")
        image_row.addWidget(self.image_path, 1)
        choose_image = QPushButton("选择图片")
        choose_image.clicked.connect(self._choose_image)
        image_row.addWidget(choose_image)
        clear_image = QPushButton("清除")
        clear_image.clicked.connect(self._clear_image)
        image_row.addWidget(clear_image)
        form.addRow("背景图片:", image_row)
        layout.addLayout(form)

        hint = QLabel("图片会铺满工作区背景；内容面板保持不透明，文字仍清晰可读。")
        hint.setObjectName("mutedText")
        layout.addWidget(hint)

        self.preview = QLabel("外观预览  ·  库存清晰可见")
        self.preview.setMinimumHeight(70)
        self.preview.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.preview)
        self.image_preview = QLabel()
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setMinimumHeight(90)
        self.image_preview.setVisible(False)
        layout.addWidget(self.image_preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        reset = buttons.addButton("恢复当前模式默认值", QDialogButtonBox.ResetRole)
        reset.clicked.connect(self._reset_mode)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_controls()

    @property
    def preferences(self) -> ThemePreferences:
        return self._draft.clone()

    def _mode_changed(self):
        self._mode = self.mode_combo.currentData()
        self._draft.mode = self._mode
        self._refresh_controls()

    def _refresh_controls(self):
        accent = self._draft.accent[self._mode]
        background = self._draft.background[self._mode]
        on_accent = "#111827" if _contrast("#111827", accent) >= _contrast("#ffffff", accent) else "#ffffff"
        self.accent_button.setText(accent.upper())
        self.accent_button.setStyleSheet(
            f"background: {accent}; color: {on_accent}; border: 1px solid {accent};"
        )
        self.background_button.setText(background.upper())
        self.background_button.setStyleSheet(
            f"background: {background}; color: {_readable_accent('#111827', background)};"
        )
        self.image_path.setText(self._draft.image[self._mode])
        image = QPixmap(self._draft.image[self._mode])
        if image.isNull():
            self.image_preview.setVisible(False)
        else:
            self.image_preview.setPixmap(image.scaled(
                420, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
            self.image_preview.setVisible(True)
        text = _readable_accent(
            "#edf3fb" if self._mode == "dark" else "#172b4d", background
        )
        self.preview.setStyleSheet(
            f"background: {background}; color: {text}; border: 2px solid {accent};"
            "border-radius: 8px; font-size: 15px; font-weight: 700;"
        )

    def _choose_accent(self):
        color = QColorDialog.getColor(QColor(self._draft.accent[self._mode]), self,
                                      "选择界面强调色")
        if color.isValid():
            self._draft.accent[self._mode] = color.name()
            self._refresh_controls()

    def _choose_background(self):
        color = QColorDialog.getColor(QColor(self._draft.background[self._mode]), self,
                                      "选择背景颜色")
        if color.isValid():
            self._draft.background[self._mode] = color.name()
            self._refresh_controls()

    def _choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", self._draft.image[self._mode] or os.path.expanduser("~"),
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            self._draft.image[self._mode] = path
            self._refresh_controls()

    def _clear_image(self):
        self._draft.image[self._mode] = ""
        self._refresh_controls()

    def _reset_mode(self):
        self._draft.accent[self._mode] = DEFAULTS[self._mode]["accent"]
        self._draft.background[self._mode] = DEFAULTS[self._mode]["background"]
        self._draft.image[self._mode] = ""
        self._refresh_controls()
