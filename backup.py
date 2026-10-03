"""
JSON 备份模块
=============
功能：在程序退出时，自动将 SQLite 四张核心表数据导出为 JSON 文件。
触发时机：closeEvent 中，断开数据库连接之前。
存储位置：数据库同级目录 Backups/ 文件夹。
"""

import json
import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional, Callable


# ============================================================
# 系统版本常量
# ============================================================
SYSTEM_VERSION = "1.0.0"
BACKUP_FORMAT_VERSION = "1.0"


# ============================================================
# 备份执行
# ============================================================

def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """将 sqlite3.Row 转换为普通字典。"""
    return dict(row)


def execute_backup(
    db_path: str,
    backup_dir: str = None,
    log_callback: Optional[Callable[[str], None]] = None
) -> bool:
    """
    执行数据库 JSON 备份。

    Args:
        db_path: SQLite 数据库文件路径
        backup_dir: 备份目录路径（默认为 db_path 所在目录下的 Backups/）
        log_callback: 日志回调函数，用于向 UI 日志区输出信息

    Returns:
        是否备份成功
    """

    def log(msg: str):
        """内部日志辅助函数。"""
        if log_callback:
            log_callback(msg)

    # ---- 1. 确定备份目录 ----
    if backup_dir is None:
        base_dir = os.path.dirname(os.path.abspath(db_path))
        backup_dir = os.path.join(base_dir, "Backups")

    try:
        os.makedirs(backup_dir, exist_ok=True)
    except OSError as e:
        log(f"[备份错误] 无法创建备份目录 {backup_dir}: {e}")
        return False

    # ---- 2. 生成备份文件名 ----
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"backup_{timestamp}.json"
    backup_path = os.path.join(backup_dir, backup_filename)

    log(f"[备份] 正在导出数据至 {backup_filename} ...")

    # ---- 3. 连接数据库并读取所有表数据 ----
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        tables = ["parts", "work_orders", "work_order_items", "inventory_transactions", "bom_items", "suppliers"]
        data: Dict[str, list] = {}

        for table in tables:
            cursor = conn.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            data[table] = [_row_to_dict(r) for r in rows]
            log(f"  - {table}: {len(rows)} 条记录")

        # ---- 4. 构建备份 JSON 结构 ----
        backup_obj = {
            "backup_metadata": {
                "backup_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "system_version": SYSTEM_VERSION,
                "backup_format_version": BACKUP_FORMAT_VERSION,
                "record_counts": {t: len(data[t]) for t in tables},
            },
            "data": data,
        }

        # ---- 5. 写入 JSON 文件 ----
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup_obj, f, ensure_ascii=False, indent=2)

        log(f"[备份成功] 数据已保存至 {backup_path}")
        return True

    except sqlite3.Error as e:
        log(f"[备份错误] 数据库读取失败: {e}")
        return False
    except IOError as e:
        log(f"[备份错误] 文件写入失败: {e}")
        return False
    except Exception as e:
        log(f"[备份错误] 未知异常: {e}")
        return False
    finally:
        if conn:
            conn.close()


def cleanup_old_backups(backup_dir: str, keep_count: int = 30):
    """
    清理过期备份，仅保留最近 N 个文件。

    Args:
        backup_dir: 备份目录路径
        keep_count: 保留的备份文件数量上限
    """
    if not os.path.isdir(backup_dir):
        return

    try:
        files = [
            os.path.join(backup_dir, f)
            for f in os.listdir(backup_dir)
            if f.startswith("backup_") and f.endswith(".json")
        ]
        # 按修改时间排序（旧 → 新）
        files.sort(key=lambda p: os.path.getmtime(p))

        # 删除超出保留数量的旧文件
        while len(files) > keep_count:
            old_file = files.pop(0)
            os.remove(old_file)
            print(f"[备份清理] 已删除旧备份: {os.path.basename(old_file)}")
    except OSError:
        pass  # 清理失败不阻断流程


# ============================================================
# 独立测试入口
# ============================================================

if __name__ == "__main__":
    # 测试：使用当前目录下的测试数据库
    test_db = os.path.join(os.path.dirname(__file__), "inventory.db")

    if os.path.exists(test_db):
        success = execute_backup(test_db, log_callback=print)
        print(f"备份结果: {'成功' if success else '失败'}")
    else:
        print(f"测试数据库不存在: {test_db}")
        print("请先运行 database.py 初始化数据库")
