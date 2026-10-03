"""
二维码标签生成模块
==================
功能：使用 qrcode + Pillow 生成元件二维码标签图片。
标签布局：顶部为高清二维码，底部为元件参数信息区。
"""

import json
import io
from typing import Dict, Optional

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
from PIL import Image, ImageDraw, ImageFont


# ============================================================
# 标签布局常量（单位：像素）
# ============================================================
LABEL_WIDTH = 400        # 标签总宽度
LABEL_HEIGHT = 280       # 标签总高度
QR_SIZE = 200            # 二维码区域边长
QR_MARGIN_TOP = 20       # 二维码距顶部距离
INFO_MARGIN_TOP = 230    # 文字信息区距顶部起始位置
PADDING_H = 20           # 左右内边距
LINE_HEIGHT = 22         # 文字行高

# 颜色常量（RGB）
BG_COLOR = (255, 255, 255)   # 白色背景
TEXT_COLOR = (30, 30, 30)     # 深灰文字
ACCENT_COLOR = (0, 102, 204)  # 蓝色强调（可用于料号高亮）

# 标签尺寸（兼容旧 API）
LABEL_W = LABEL_WIDTH
LABEL_H = LABEL_HEIGHT


# ============================================================
# 字体加载
# ============================================================

def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """
    获取字体对象。
    优先使用系统自带的中文字体，若找不到则回退到 Pillow 默认字体。
    """
    # Windows 常见中文字体路径
    font_candidates = [
        "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
        "C:/Windows/Fonts/simsun.ttc",     # 宋体
        "C:/Windows/Fonts/simhei.ttf",     # 黑体
        "/System/Library/Fonts/PingFang.ttc",  # macOS
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",  # Linux
    ]
    for font_path in font_candidates:
        try:
            return ImageFont.truetype(font_path, size)
        except (OSError, IOError):
            continue

    # 回退：使用 Pillow 默认字体（可能不支持中文）
    try:
        return ImageFont.truetype("arial.ttf", size)
    except (OSError, IOError):
        return ImageFont.load_default()


# ============================================================
# 二维码生成
# ============================================================

def generate_qr_image(data: str, size: int = QR_SIZE) -> Image.Image:
    """
    生成高清二维码图片。

    Args:
        data: 二维码内容（JSON 字符串或料号）
        size: 输出图片边长（像素）

    Returns:
        PIL Image 对象
    """
    qr = qrcode.QRCode(
        version=None,              # 自动确定版本
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # 高容错率（~30%）
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    # 生成带圆角模块的二维码图片
    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        fill_color="black",
        back_color="white",
    )
    img = img.resize((size, size), Image.LANCZOS)
    return img


def build_part_info_json(part: Dict) -> str:
    """
    将物料信息构建为 JSON 字符串（用于二维码内容）。

    Args:
        part: 物料信息字典，至少包含 part_number, name, package, stock_qty, location

    Returns:
        格式化的 JSON 字符串
    """
    info = {
        "pn": part.get("part_number", ""),
        "n":  part.get("name", ""),
        "pkg": part.get("package", ""),
        "qty": part.get("stock_qty", 0),
        "loc": part.get("location", ""),
    }
    return json.dumps(info, ensure_ascii=False)


# ============================================================
# 标签图片生成
# ============================================================

def generate_label(part: Dict) -> Image.Image:
    """
    生成完整元件标签图片。

    布局：
    ┌──────────────────────────────┐
    │        ┌──────────┐         │
    │        │ QR Code   │         │  ← 顶部居中
    │        └──────────┘         │
    │                              │
    │  内部料号: RES-000001        │  ← 底部信息区
    │  名称: 10KΩ 0805 1%         │
    │  封装: 0805                  │
    │  库存: 1500                  │
    │  库位: B-02-05               │
    └──────────────────────────────┘

    Args:
        part: 物料信息字典（含 part_number, name, package, stock_qty, location）

    Returns:
        PIL Image 对象（RGB 模式）
    """
    # 创建白色背景画布
    img = Image.new("RGB", (LABEL_WIDTH, LABEL_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # ---- 1. 生成二维码并粘贴到顶部居中位置 ----
    qr_data = json.dumps({
        "pn": part.get("part_number", ""),
        "n":  part.get("name", ""),
        "pkg": part.get("package", ""),
        "qty": part.get("stock_qty", 0),
        "loc": part.get("location", ""),
    }, ensure_ascii=False)
    qr_img = generate_qr_image(qr_data)
    qr_x = (LABEL_WIDTH - QR_SIZE) // 2
    img.paste(qr_img, (qr_x, QR_MARGIN_TOP))

    # ---- 2. 绘制底部信息区 ----
    font_bold = _get_font(13, bold=True)
    font_normal = _get_font(12, bold=False)
    font_small = _get_font(10, bold=False)

    y = INFO_MARGIN_TOP
    x_label = PADDING_H
    x_value = 110  # 值区域起始 X 坐标

    # 分隔线
    draw.line([(PADDING_H, y - 5), (LABEL_WIDTH - PADDING_H, y - 5)],
              fill=(200, 200, 200), width=1)

    lines = [
        ("内部料号:", part.get("part_number", ""), font_bold, ACCENT_COLOR),
        ("名称:",     part.get("name", ""),       font_normal, TEXT_COLOR),
        ("封装:",     part.get("package", ""),    font_normal, TEXT_COLOR),
        ("库存数量:", str(part.get("stock_qty", 0)), font_normal, TEXT_COLOR),
        ("库位:",     part.get("location", ""),   font_normal, TEXT_COLOR),
    ]

    for label_text, value_text, font, color in lines:
        # 标签（灰色）
        draw.text((x_label, y), label_text, fill=(120, 120, 120), font=font_small)
        # 值
        draw.text((x_value, y), value_text, fill=color, font=font)
        y += LINE_HEIGHT

    return img


def label_to_pixmap(label_img: Image.Image):
    """
    将 PIL Image 转换为 QPixmap（供 PyQt 界面显示）。

    Args:
        label_img: PIL Image 对象

    Returns:
        QPixmap 对象
    """
    from PySide6.QtGui import QPixmap
    # PIL Image → bytes → QPixmap
    buffer = io.BytesIO()
    label_img.save(buffer, format="PNG")
    buffer.seek(0)

    pixmap = QPixmap()
    pixmap.loadFromData(buffer.read(), "PNG")
    return pixmap


# ============================================================
# 独立测试入口
# ============================================================

if __name__ == "__main__":
    # 测试：用示例数据生成标签并保存
    test_part = {
        "part_number": "RES-000001",
        "name": "10KΩ 0805 1% 贴片电阻",
        "package": "0805",
        "stock_qty": 2000,
        "location": "B-02-05",
    }
    label = generate_label(test_part)
    output_path = "test_label.png"
    label.save(output_path)
    print(f"标签已保存至: {output_path}")
    print(f"标签尺寸: {label.size}")
