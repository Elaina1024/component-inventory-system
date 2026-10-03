"""
BOM 解析模块
===========
功能：读取 Excel BOM 表，解析物料清单，校验数据完整性，
     计算物料总需求（BOM用量 × 生产份数），并与库存比对。
"""

import os
from typing import List, Dict, Optional, Tuple

import pandas as pd


# ============================================================
# BOM 表列名映射
# ============================================================
# BOM 表可能使用不同的列名，此处定义别名映射以增强兼容性。
# 标准列名：part_number / name / quantity / package（可选）/ location（可选）
COLUMN_ALIASES = {
    "part_number": ["part_number", "料号", "物料编号", "Part Number", "PN", "物料编码", "内部料号"],
    "name":        ["name", "名称", "物料名称", "Description", "描述", "规格", "品名"],
    "quantity":    ["quantity", "用量", "数量", "Qty", "QTY", "单份用量", "每份用量", "单机用量"],
    "package":     ["package", "封装", "Package", "封装类型", "封装形式"],
    "location":    ["location", "库位", "Location", "存放位置", "仓位"],
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    将 BOM 表的列名标准化。
    遍历 COLUMN_ALIASES，将可能的别名统一映射为标准列名。
    """
    rename_map = {}
    for standard, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in df.columns and alias != standard:
                rename_map[alias] = standard
                break
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def validate_bom(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    校验 BOM 数据的完整性。

    Returns:
        (是否有效, 错误信息列表)
    """
    errors = []

    # 必填列检查
    required_cols = ["part_number", "name", "quantity"]
    for col in required_cols:
        if col not in df.columns:
            errors.append(f"缺少必填列: {col}（或列名无法识别）")
            return False, errors

    # 数据有效性检查
    for idx, row in df.iterrows():
        row_num = idx + 2  # Excel 行号（跳过表头，从 2 开始）

        # 料号不能为空
        if pd.isna(row["part_number"]) or str(row["part_number"]).strip() == "":
            errors.append(f"第 {row_num} 行：物料料号为空")

        # 名称不能为空
        if pd.isna(row["name"]) or str(row["name"]).strip() == "":
            errors.append(f"第 {row_num} 行：物料名称为空")

        # 用量必须是正整数
        qty = row["quantity"]
        if pd.isna(qty):
            errors.append(f"第 {row_num} 行：用量为空")
        else:
            try:
                qty_int = int(qty)
                if qty_int <= 0 or float(qty) != qty_int:
                    errors.append(f"第 {row_num} 行：用量必须为正整数（当前: {qty}）")
            except (ValueError, TypeError, OverflowError):
                errors.append(f"第 {row_num} 行：用量格式无效（当前: {qty}）")

    return len(errors) == 0, errors


def parse_bom(file_path: str) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """
    解析 BOM Excel 文件。

    Args:
        file_path: BOM 文件路径（.xlsx 或 .xls）

    Returns:
        (DataFrame 或 None, 错误信息列表)
        DataFrame 包含标准化列: part_number, name, quantity, package, location
    """
    errors = []

    if not os.path.exists(file_path):
        return None, [f"文件不存在: {file_path}"]

    # 读取 Excel
    try:
        if file_path.endswith(".xlsx"):
            df = pd.read_excel(file_path, engine="openpyxl")
        elif file_path.endswith(".xls"):
            df = pd.read_excel(file_path, engine="xlrd")
        else:
            return None, ["不支持的文件格式，请使用 .xlsx 或 .xls 文件"]
    except Exception as e:
        return None, [f"读取 BOM 文件失败: {str(e)}"]

    # 去除全空行和全空列
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.empty:
        return None, ["BOM 表无有效数据"]

    # 标准化列名
    df = normalize_columns(df)

    # 全空列会在上一步被移除，先给出可理解的缺列提示。
    required_cols = ("part_number", "name", "quantity")
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        return None, [f"缺少必填列: {col}（或该列内容全为空）" for col in missing]

    # 为可选列补充默认值
    if "package" not in df.columns:
        df["package"] = ""
    if "location" not in df.columns:
        df["location"] = ""

    # 数据清洗：去除首尾空格
    df["part_number"] = df["part_number"].fillna("").astype(str).str.strip()
    df["name"] = df["name"].fillna("").astype(str).str.strip()

    # 校验
    valid, validation_errors = validate_bom(df)
    errors.extend(validation_errors)
    if not valid:
        return None, errors

    # 用量转为整数
    df["quantity"] = df["quantity"].apply(lambda x: int(x))

    return df, errors


def calculate_demand(bom_df: pd.DataFrame, planned_qty: int) -> pd.DataFrame:
    """
    计算物料总需求 = BOM单份用量 × 计划生产份数。

    Args:
        bom_df: 已解析的 BOM DataFrame
        planned_qty: 计划生产份数

    Returns:
        添加了 total_demand 列的 DataFrame
    """
    df = bom_df.copy()
    # 同一料号可能在 BOM 的多个位置使用，库存必须按合计用量判断。
    if not df.empty:
        columns = {col: "first" for col in df.columns if col != "part_number"}
        columns["quantity"] = "sum"
        df = df.groupby("part_number", as_index=False, sort=False).agg(columns)
    df["total_demand"] = df["quantity"] * planned_qty
    return df


def check_shortage(bom_df: pd.DataFrame, planned_qty: int,
                   parts_map: Dict[str, Dict]) -> List[Dict]:
    """
    比对 BOM 需求与库存，返回缺料清单。

    Args:
        bom_df: 已解析的 BOM DataFrame
        planned_qty: 计划生产份数
        parts_map: 以 part_number 为 key 的物料信息字典，
                   value 包含 stock_qty / locked_qty

    Returns:
        缺料列表，每项包含 part_number, name, demand, available, shortage
    """
    shortages = []

    for _, row in calculate_demand(bom_df, planned_qty).iterrows():
        pn = str(row["part_number"]).strip()
        demand = int(row["total_demand"])

        part_info = parts_map.get(pn)
        if part_info is None:
            # 料号在系统中不存在
            shortages.append({
                "part_number": pn,
                "name": row["name"],
                "demand": demand,
                "available": 0,
                "shortage": demand,
                "reason": "物料未录入系统"
            })
        else:
            available = part_info["stock_qty"] - part_info["locked_qty"]
            if available < demand:
                shortages.append({
                    "part_number": pn,
                    "name": row["name"],
                    "demand": demand,
                    "available": available,
                    "shortage": demand - available,
                    "reason": "可用库存不足"
                })

    return shortages


# ============================================================
# 独立测试入口
# ============================================================

if __name__ == "__main__":
    # 使用示例 BOM 文件测试
    test_file = os.path.join(os.path.dirname(__file__), "example_bom.xlsx")
    if os.path.exists(test_file):
        df, errors = parse_bom(test_file)
        if df is not None:
            print("BOM 解析成功：")
            print(df.to_string())
            demand_df = calculate_demand(df, 10)
            print(f"\n计划生产 10 份的需求：")
            print(demand_df.to_string())
        else:
            print("解析错误：", errors)
    else:
        print(f"测试文件不存在: {test_file}")
