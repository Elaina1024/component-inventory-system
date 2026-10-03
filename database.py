"""
数据库初始化与操作模块
=====================
功能：SQLite3 数据库连接管理、建表、CRUD 操作封装。
遵循 PEP8 规范，关键业务逻辑处添加中文注释。
"""

from __future__ import annotations

import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from app_paths import application_directory


# ============================================================
# 数据库路径配置
# ============================================================
DB_DIR = str(application_directory())
DB_PATH = os.path.join(DB_DIR, "inventory.db")


# ============================================================
# 料号自动生成：类别缩写映射表
# ============================================================

CATEGORY_PREFIX_MAP = {
    # 电阻类
    "电阻": "RES", "电阻器": "RES", "热敏电阻": "NTC", "压敏电阻": "VAR",
    "电位器": "POT", "排阻": "RN",
    # 电容类
    "电容": "CAP", "电容器": "CAP", "电解电容": "CAP", "钽电容": "CAP",
    "MLCC": "CAP", "超级电容": "CAP",
    # 半导体 — MCU / MPU / IC
    "MCU": "MCU", "微控制器": "MCU", "单片机": "MCU", "MPU": "MPU",
    "ARM": "MCU", "RISC-V": "MCU",
    "集成电路": "IC", "IC": "IC", "芯片": "IC", "运放": "IC",
    "逻辑IC": "IC", "存储IC": "IC", "Flash": "IC",
    # LED / 光电器件
    "LED": "LED", "发光二极管": "LED", "数码管": "LED",
    "光耦": "OPTO", "光电耦合器": "OPTO", "光电传感器": "OPTO",
    # 连接器
    "连接器": "CON", "接插件": "CON", "端子": "CON",
    "排针": "HEADER", "排母": "HEADER", "插座": "CON",
    "USB": "CON", "FPC": "FPC", "FFC": "FPC",
    # 二极管 / 三极管 / MOS
    "二极管": "DIO", "开关二极管": "DIO", "稳压二极管": "ZEN",
    "TVS": "TVS", "ESD": "TVS",
    "三极管": "TRI", "BJT": "TRI", "晶体管": "TRI",
    "MOS管": "MOS", "MOSFET": "MOS", "IGBT": "IGBT",
    # 电源管理
    "电源IC": "PWR", "电源管理": "PWR", "LDO": "PWR",
    "DC-DC": "PWR", "AC-DC": "PWR", "PMIC": "PWR",
    "基准源": "REF", "电压基准": "REF",
    # 电感 / 磁珠 / 变压器
    "电感": "IND", "电感器": "IND", "磁珠": "FEB",
    "变压器": "TRANS", "互感器": "TRANS",
    # 晶振 / 谐振器
    "晶振": "XTAL", "晶体": "XTAL", "振荡器": "OSC",
    "陶瓷谐振": "XTAL",
    # 传感器
    "传感器": "SENS", "温度传感器": "SENS", "湿度传感器": "SENS",
    "加速度计": "SENS", "陀螺仪": "SENS",
    # 开关 / 保护器件
    "开关": "SW", "按键": "SW", "轻触开关": "SW",
    "保险丝": "FUSE", "PTC": "FUSE", "熔断器": "FUSE",
    # 继电器
    "继电器": "RLY", "固态继电器": "RLY",
    # PCB / 结构件
    "PCB": "PCB", "电路板": "PCB",
    "散热器": "HS", "散热片": "HS",
    "屏蔽罩": "SHIELD",
    # 线材 / 装配辅料
    "线材": "WIRE", "导线": "WIRE", "排线": "WIRE",
    "跳线": "JUMP", "短路帽": "JUMP",
    "测试点": "TP", "测试环": "TP",
    "焊锡": "SLDR", "助焊剂": "FLUX",
    # 模块
    "模块": "MOD", "蓝牙模块": "MOD", "WiFi模块": "MOD",
    "GPS模块": "MOD", "NB-IoT": "MOD",
    # 其他
    "电池": "BAT", "电池座": "BAT",
    # ================================================================
    # 机械零件类别：紧固件、传动件、结构件、气动件
    # ================================================================
    # 标准紧固件
    "螺丝": "SCRW", "螺钉": "SCRW", "机丝螺钉": "SCRW", "自攻螺钉": "SCRW",
    "螺母": "NUT", "六角螺母": "NUT", "锁紧螺母": "NUT",
    "垫圈": "WSHR", "平垫圈": "WSHR", "弹簧垫圈": "WSHR",
    "螺栓": "BOLT", "外六角螺栓": "BOLT", "内六角螺栓": "BOLT",
    "螺柱": "STUD", "双头螺柱": "STUD",
    "挡圈": "RING", "卡簧": "RING", "弹性挡圈": "RING", "轴用挡圈": "RING",
    "键": "KEY", "平键": "KEY", "半圆键": "KEY",
    "销": "PIN", "圆柱销": "PIN", "圆锥销": "PIN", "开口销": "PIN", "定位销": "PIN",
    # 传动件
    "轴承": "BRG", "滚动轴承": "BRG", "深沟球轴承": "BRG", "角接触轴承": "BRG",
    "直线轴承": "BRG", "推力轴承": "BRG",
    "齿轮": "GEAR", "直齿轮": "GEAR", "斜齿轮": "GEAR", "蜗轮": "GEAR", "齿条": "GEAR",
    "同步带": "TBELT",
    "同步带轮": "TPLY", "同步轮": "TPLY",
    "链条": "CHAIN", "滚子链": "CHAIN",
    "链轮": "SPRO",
    "轴": "SHAFT", "光轴": "SHAFT", "阶梯轴": "SHAFT", "传动轴": "SHAFT",
    "联轴器": "COUP", "弹性联轴器": "COUP", "刚性联轴器": "COUP",
    # 导向件
    "导轨": "RAIL", "直线导轨": "RAIL",
    "滑块": "SLIDE", "直线滑块": "SLIDE",
    # 结构型材
    "型材": "PROF", "铝型材": "PROF", "工业铝型材": "PROF",
    "角码": "BRKT", "角件": "BRKT", "连接件": "BRKT", "支架": "BRKT",
    "法兰": "FLG", "法兰盘": "FLG",
    # 板材 / 管材
    "板材": "PLATE", "钢板": "PLATE", "铝板": "PLATE", "亚克力板": "PLATE",
    "管材": "TUBE", "钢管": "TUBE", "铝管": "TUBE",
    "钣金件": "SMTL",
    "机加工件": "MACH", "加工件": "MACH",
    # 弹簧
    "弹簧": "SPRG", "压缩弹簧": "SPRG", "拉伸弹簧": "SPRG", "扭簧": "SPRG",
    # 气动 / 液压
    "气缸": "CYL", "气动气缸": "CYL",
    "阀": "VALVE", "气动阀": "VALVE", "电磁阀": "VALVE", "节流阀": "VALVE",
    "气管接头": "FITT", "气动接头": "FITT", "快插接头": "FITT",
    "密封圈": "SEAL", "O型圈": "SEAL", "油封": "SEAL",
    # 其他
    "3D打印件": "3DP",
    "脚轮": "CASTR", "万向轮": "CASTR",
    "把手": "HANDL", "拉手": "HANDL",
    "合页": "HINGE", "铰链": "HINGE",
}


def generate_part_number(db: DatabaseManager, category: str) -> str:
    """
    根据物料类别自动生成全局唯一的内部料号。

    格式: 类别缩写-年月-六位流水号  (例: RES-202606-000001)
    - 已知类别: 使用 CATEGORY_PREFIX_MAP 映射的缩写
    - 未映射类别: 提取类别名的前3个英文字母; 不足3位则回退为 "GEN"
    - 流水号按"类别缩写 + 年月"分组，从 000001 起递增，自动补零至 6 位

    Args:
        db: DatabaseManager 实例
        category: 物料分类（中文或英文）

    Returns:
        全局唯一的料号字符串
    """
    category = category.strip() if category else ""

    # ---- 1. 确定类别缩写 ----
    prefix = CATEGORY_PREFIX_MAP.get(category)
    if not prefix:
        # 回退策略：仅取大写 ASCII 英文字母，取前 3 位；不足则用 "GEN"
        clean = category.upper()
        alpha = "".join(c for c in clean if c.isascii() and c.isalpha())
        prefix = alpha[:3] if len(alpha) >= 3 else "GEN"

    # ---- 2. 查询当前年月下该前缀的最大流水号 ----
    now = datetime.now()
    ym = now.strftime("%Y%m")
    pattern = f"{prefix}-{ym}-%"

    row = db.fetch_one(
        "SELECT MAX(part_number) AS max_pn FROM parts WHERE part_number LIKE ?",
        (pattern,)
    )

    if row and row["max_pn"]:
        # 从 "RES-202606-0005" 中提取 "0005" → 5 → +1 → 6
        seq = int(row["max_pn"].split("-")[-1]) + 1
    else:
        seq = 1

    return f"{prefix}-{ym}-{seq:06d}"


# ============================================================
# 数据库连接管理
# ============================================================

class DatabaseManager:
    """
    SQLite 数据库管理器
    -------------------
    采用单例模式管理数据库连接，确保全局只有一个连接实例，
    避免多线程/多窗口场景下的锁冲突。
    """

    _instance: Optional["DatabaseManager"] = None
    _connection: Optional[sqlite3.Connection] = None

    def __new__(cls) -> "DatabaseManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> sqlite3.Connection:
        """获取数据库连接。若未建立连接，则自动创建。"""
        if self._connection is None:
            self._connection = sqlite3.connect(DB_PATH)
            self._connection.execute("PRAGMA journal_mode=WAL")  # WAL 模式提升并发性能
            self._connection.execute("PRAGMA foreign_keys=ON")   # 启用外键约束
            self._connection.row_factory = sqlite3.Row            # 支持按列名访问结果
        return self._connection

    def close(self):
        """安全关闭数据库连接。"""
        if self._connection is not None:
            try:
                self._connection.commit()
                self._connection.close()
            except sqlite3.Error:
                pass  # 关闭时若已损坏，忽略异常
            finally:
                self._connection = None

    @property
    def is_connected(self) -> bool:
        """检查数据库是否已连接。"""
        return self._connection is not None

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """执行 SQL 语句并返回游标。"""
        conn = self.connect()
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor

    def executemany(self, sql: str, params_list: List[tuple]):
        """批量执行 SQL 语句。"""
        conn = self.connect()
        conn.executemany(sql, params_list)
        conn.commit()

    def fetch_all(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        """执行查询并返回所有结果行。"""
        conn = self.connect()
        cursor = conn.execute(sql, params)
        return cursor.fetchall()

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """执行查询并返回第一行结果。"""
        conn = self.connect()
        cursor = conn.execute(sql, params)
        return cursor.fetchone()


# ============================================================
# 建表语句
# ============================================================

CREATE_TABLES_SQL = """
-- ============================================================
-- 供应商信息表 (suppliers)
-- 记录常用供应商的名称、联系方式、网址等信息
-- ============================================================
CREATE TABLE IF NOT EXISTS suppliers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,              -- 供应商名称
    contact_person  TEXT,                          -- 联系人
    phone           TEXT,                          -- 联系电话
    email           TEXT,                          -- 联系邮箱
    website         TEXT,                          -- 网址
    address         TEXT,                          -- 地址
    remark          TEXT,                          -- 备注
    created_at      TEXT    DEFAULT (datetime('now', 'localtime'))
);

-- ============================================================
-- 物料主数据表 (parts)
-- 记录所有物料的基本信息与库存数据（电子元件与机械零件）
-- ============================================================
CREATE TABLE IF NOT EXISTS parts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    part_number     TEXT    NOT NULL UNIQUE,      -- 内部料号，全局唯一
    name            TEXT    NOT NULL,              -- 物料名称（如 STM32F103C8T6）
    package         TEXT,                          -- 封装类型（如 LQFP-48, 0805）
    location        TEXT,                          -- 库位信息（如 A-01-03）
    category        TEXT,                          -- 物料分类（MCU / 电阻 / 电容 / 连接器 等）
    stock_qty       INTEGER NOT NULL DEFAULT 0,   -- 物理总库存
    locked_qty      INTEGER NOT NULL DEFAULT 0,   -- 锁定缓存数量（被工单预占）
    min_stock       INTEGER DEFAULT 0,            -- 安全库存下限
    supplier_id     INTEGER,                      -- 默认供应商 ID
    unit_price      REAL    DEFAULT 0,            -- 物料单价（人民币）
    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL
);

-- ============================================================
-- 生产工单表 (work_orders)
-- 记录每次 BOM 导入生成的生产工单信息
-- ============================================================
CREATE TABLE IF NOT EXISTS work_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number    TEXT    NOT NULL UNIQUE,       -- 工单号（WO-YYYYMMDD-NNNN）
    bom_name        TEXT    NOT NULL,              -- BOM 文件名称
    planned_qty     INTEGER NOT NULL,              -- 计划生产份数
    actual_qty      INTEGER,                       -- 实际完工份数（完工时填入）
    status          TEXT    NOT NULL DEFAULT 'LOCKED',  -- LOCKED / COMPLETED / CANCELLED
    remark          TEXT,                          -- 备注信息
    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    completed_at    TEXT                           -- 工单完成时间
);

-- ============================================================
-- 工单物料明细表 (work_order_items)
-- 记录每个工单对应的物料需求与消耗明细
-- ============================================================
CREATE TABLE IF NOT EXISTS work_order_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    work_order_id       INTEGER NOT NULL,          -- 关联工单 ID
    part_id             INTEGER NOT NULL,          -- 关联物料 ID
    required_qty        INTEGER NOT NULL,          -- 需求数量（BOM用量 × 计划份数）
    locked_qty          INTEGER NOT NULL,          -- 锁定数量（= required_qty 快照）
    actual_consumed_qty INTEGER DEFAULT 0,         -- 实际消耗数量（核销时填入）
    returned_qty        INTEGER DEFAULT 0,         -- 退库数量
    FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE CASCADE,
    FOREIGN KEY (part_id) REFERENCES parts(id) ON DELETE RESTRICT
);

-- ============================================================
-- 全局库存流水表 (inventory_transactions)
-- 记录所有库存变动的审计日志
-- ============================================================
CREATE TABLE IF NOT EXISTS inventory_transactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,  -- 流水号
    part_id             INTEGER NOT NULL,                   -- 关联物料 ID
    transaction_type    TEXT    NOT NULL,                   -- 操作类型（枚举）
    quantity            INTEGER NOT NULL,                   -- 变动量（入库+/出库-）
    work_order_id       INTEGER,                            -- 关联工单 ID（可为空）
    remark              TEXT,                               -- 备注信息
    created_at          TEXT    DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (part_id) REFERENCES parts(id) ON DELETE RESTRICT,
    FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE SET NULL
);

-- ============================================================
-- BOM 结构明细表 (bom_items)
-- 记录本地保存的 BOM 物料清单结构，支持增删改查及导出
-- ============================================================
CREATE TABLE IF NOT EXISTS bom_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bom_name        TEXT    NOT NULL,              -- BOM 名称（如 STM32F103C8T6 核心板 V1.2）
    part_number     TEXT    NOT NULL,              -- 物料内部料号
    qty_per_unit    INTEGER NOT NULL DEFAULT 1,    -- 单个产品所需该物料数量
    remark          TEXT,                          -- 备注（替代料说明、批次要求等）
    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (part_number) REFERENCES parts(part_number) ON DELETE CASCADE
);

-- ============================================================
-- 索引：提升常用查询性能
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_parts_part_number ON parts(part_number);
CREATE INDEX IF NOT EXISTS idx_parts_category ON parts(category);
CREATE INDEX IF NOT EXISTS idx_work_orders_status ON work_orders(status);
CREATE INDEX IF NOT EXISTS idx_work_order_items_wo_id ON work_order_items(work_order_id);
CREATE INDEX IF NOT EXISTS idx_transactions_part_id ON inventory_transactions(part_id);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON inventory_transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_transactions_created_at ON inventory_transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_bom_items_name ON bom_items(bom_name);
CREATE INDEX IF NOT EXISTS idx_bom_items_part ON bom_items(part_number);
CREATE INDEX IF NOT EXISTS idx_parts_supplier_id ON parts(supplier_id);
"""


# ============================================================
# Schema 迁移：安全地为已有数据库添加新列
# ============================================================

def migrate_schema(db: DatabaseManager):
    """
    在已有数据库上执行增量 schema 迁移。
    使用 try/except 实现幂等性 —— 列已存在时静默跳过。
    """
    migrations = [
        "ALTER TABLE parts ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id)",
        "ALTER TABLE parts ADD COLUMN unit_price REAL DEFAULT 0",
    ]
    for sql in migrations:
        try:
            db.execute(sql)
            print(f"[迁移] 执行: {sql[:60]}...")
        except sqlite3.OperationalError:
            pass  # 列已存在，跳过


# ============================================================
# 数据库初始化入口
# ============================================================

def init_database(db_path: str = None) -> DatabaseManager:
    """
    初始化数据库：建立或迁移表结构，不插入任何业务记录。

    Args:
        db_path: 数据库文件路径（可选，默认使用模块内的 DB_PATH）

    Returns:
        DatabaseManager 实例
    """
    global DB_PATH
    if db_path:
        DB_PATH = db_path

    db = DatabaseManager()

    # 使用 executescript 一次性执行所有建表语句
    # （比逐条 split 更可靠，能正确处理多行语句和注释）
    try:
        connection = db.connect()
        connection.executescript(CREATE_TABLES_SQL)
        connection.commit()
        print("[建表] 所有表结构已就绪。")
    except sqlite3.Error as e:
        print(f"[建表错误] {e}")

    # 执行增量 schema 迁移（为已有旧数据库添加新字段）
    migrate_schema(db)

    print(f"[数据库] 初始化完成，路径: {DB_PATH}")
    return db


# ============================================================
# 业务层 CRUD 封装
# ============================================================

class PartRepository:
    """物料主数据仓库"""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_all(self) -> List[sqlite3.Row]:
        """获取全部物料（含实时计算的可用库存 + 供应商名称）。"""
        return self.db.fetch_all(
            "SELECT p.*, (p.stock_qty - p.locked_qty) AS available_qty, "
            "s.name AS supplier_name "
            "FROM parts p LEFT JOIN suppliers s ON p.supplier_id = s.id "
            "ORDER BY p.category, p.part_number"
        )

    def get_by_id(self, part_id: int) -> Optional[sqlite3.Row]:
        """按 ID 查询单个物料。"""
        return self.db.fetch_one(
            "SELECT p.*, (p.stock_qty - p.locked_qty) AS available_qty, "
            "s.name AS supplier_name "
            "FROM parts p LEFT JOIN suppliers s ON p.supplier_id = s.id "
            "WHERE p.id = ?",
            (part_id,)
        )

    def search(self, keyword: str) -> List[sqlite3.Row]:
        """按料号或名称模糊搜索。"""
        kw = f"%{keyword}%"
        return self.db.fetch_all(
            "SELECT p.*, (p.stock_qty - p.locked_qty) AS available_qty, "
            "s.name AS supplier_name "
            "FROM parts p LEFT JOIN suppliers s ON p.supplier_id = s.id "
            "WHERE p.part_number LIKE ? OR p.name LIKE ? OR p.category LIKE ? "
            "ORDER BY p.category, p.part_number",
            (kw, kw, kw)
        )

    def insert(self, part_number: str, name: str, package: str = "",
               location: str = "", category: str = "", stock_qty: int = 0,
               min_stock: int = 0, supplier_id: int = None, unit_price: float = 0.0) -> int:
        """新增物料，返回新插入的 ID。"""
        cursor = self.db.execute(
            "INSERT INTO parts (part_number, name, package, location, category, "
            "stock_qty, min_stock, supplier_id, unit_price) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (part_number, name, package, location, category,
             stock_qty, min_stock, supplier_id, unit_price)
        )
        return cursor.lastrowid

    def update(self, part_id: int, **kwargs):
        """更新物料字段。kwargs 只包含需要更新的列名与值。"""
        if not kwargs:
            return
        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [part_id]
        self.db.execute(
            f"UPDATE parts SET {set_clause}, updated_at = datetime('now', 'localtime') WHERE id = ?",
            tuple(values)
        )

    def delete(self, part_id: int) -> bool:
        """删除物料。仅当 locked_qty = 0 时允许删除。
        同时清理关联的流水记录和工单明细（保留审计可追溯性 — 流水中的 part_number 仍可识别）。"""
        part = self.get_by_id(part_id)
        if part is None:
            return False
        if part["locked_qty"] > 0:
            return False  # 有锁定库存，不允许删除

        # 先清理子表记录（FK ON DELETE RESTRICT 要求）
        self.db.execute("DELETE FROM inventory_transactions WHERE part_id = ?", (part_id,))
        self.db.execute("DELETE FROM work_order_items WHERE part_id = ?", (part_id,))
        # bom_items 通过 part_number 引用，已设置 ON DELETE CASCADE，自动级联删除

        # 最后删除物料主记录
        self.db.execute("DELETE FROM parts WHERE id = ?", (part_id,))
        return True

    def lock_stock(self, part_id: int, qty: int):
        """增加物料的锁定库存。"""
        self.db.execute(
            "UPDATE parts SET locked_qty = locked_qty + ?, updated_at = datetime('now', 'localtime') "
            "WHERE id = ?",
            (qty, part_id)
        )

    def consume_stock(self, part_id: int, consume_qty: int, unlock_qty: int):
        """
        核销物料库存：扣减物理库存 + 释放锁定量。
        consume_qty: 实际消耗量（从 stock_qty 扣除）
        unlock_qty:  释放锁定量（从 locked_qty 扣除）
        """
        self.db.execute(
            "UPDATE parts SET stock_qty = stock_qty - ?, locked_qty = locked_qty - ?, "
            "updated_at = datetime('now', 'localtime') WHERE id = ?",
            (consume_qty, unlock_qty, part_id)
        )

    def return_stock(self, part_id: int, return_qty: int):
        """退库：释放锁定量。注意 return_qty 应为正数（从 locked_qty 减），stock_qty 不变。"""
        self.db.execute(
            "UPDATE parts SET locked_qty = locked_qty - ?, updated_at = datetime('now', 'localtime') "
            "WHERE id = ? AND locked_qty >= ?",
            (return_qty, part_id, return_qty)
        )

    def adhoc_issue(self, part_id: int, qty: int):
        """计划外领料：直接扣减物理库存。"""
        cursor = self.db.execute(
            "UPDATE parts SET stock_qty = stock_qty - ?, updated_at = datetime('now', 'localtime') "
            "WHERE id = ? AND stock_qty - locked_qty >= ?",
            (qty, part_id, qty)
        )
        if cursor.rowcount != 1:
            raise ValueError("可用库存不足或物料已不存在，请刷新后重试")

    def adjust_stock(self, part_id: int, delta: int):
        """
        库存手动修复：直接修改物理库存数量。
        delta: 调整量（正数增加，负数减少）。
        约束：调整后的 stock_qty 不能为负数。
        """
        self.db.execute(
            "UPDATE parts SET stock_qty = stock_qty + ?, updated_at = datetime('now', 'localtime') "
            "WHERE id = ? AND stock_qty + ? >= 0",
            (delta, part_id, delta)
        )

    # ---- 批量操作 ----

    def batch_update(self, part_ids: List[int], **kwargs) -> int:
        """批量更新物料字段（同组字段值应用到所有选中的 ID）。
        返回实际更新的行数。"""
        if not part_ids or not kwargs:
            return 0
        # 白名单校验，防止 SQL 注入
        allowed = {"category", "location", "min_stock", "supplier_id", "unit_price"}
        filtered = {k: v for k, v in kwargs.items() if k in allowed}
        if not filtered:
            return 0
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values())
        placeholders = ",".join("?" * len(part_ids))
        values.extend(part_ids)
        cursor = self.db.execute(
            f"UPDATE parts SET {set_clause}, updated_at = datetime('now','localtime') "
            f"WHERE id IN ({placeholders})",
            tuple(values)
        )
        return cursor.rowcount

    def batch_delete(self, part_ids: List[int]):
        """批量删除物料。跳过有锁定库存的物料。
        返回 (成功删除数, 被跳过的料号列表)。"""
        skipped: List[str] = []
        deleted = 0
        for pid in part_ids:
            part = self.get_by_id(pid)
            if part and part["locked_qty"] > 0:
                skipped.append(part["part_number"])
            else:
                if self.delete(pid):
                    deleted += 1
                else:
                    skipped.append(part["part_number"] if part else f"ID={pid}")
        return deleted, skipped

    def get_by_ids(self, part_ids: List[int]) -> List[sqlite3.Row]:
        """按 ID 列表批量获取物料（含可用库存 + 供应商名称）。"""
        if not part_ids:
            return []
        placeholders = ",".join("?" * len(part_ids))
        return self.db.fetch_all(
            f"""SELECT p.*, (p.stock_qty - p.locked_qty) AS available_qty,
                       s.name AS supplier_name
                FROM parts p LEFT JOIN suppliers s ON p.supplier_id = s.id
                WHERE p.id IN ({placeholders})
                ORDER BY p.category, p.part_number""",
            tuple(part_ids)
        )

    def get_distinct_categories(self) -> List[str]:
        """获取所有已使用的物料类别（去重排序）。"""
        rows = self.db.fetch_all(
            "SELECT DISTINCT category FROM parts WHERE category != '' ORDER BY category"
        )
        return [r["category"] for r in rows]

    def search_advanced(self, keyword: str = "", category: str = "") -> List[sqlite3.Row]:
        """支持分类筛选的组合搜索。"""
        conditions = []
        params: List[Any] = []
        if keyword:
            kw = f"%{keyword}%"
            conditions.append("(p.part_number LIKE ? OR p.name LIKE ? OR p.category LIKE ?)")
            params.extend([kw, kw, kw])
        if category:
            conditions.append("p.category = ?")
            params.append(category)
        where = " AND ".join(conditions) if conditions else "1=1"
        return self.db.fetch_all(
            f"""SELECT p.*, (p.stock_qty - p.locked_qty) AS available_qty,
                       s.name AS supplier_name
                FROM parts p LEFT JOIN suppliers s ON p.supplier_id = s.id
                WHERE {where}
                ORDER BY p.category, p.part_number""",
            tuple(params)
        )


class WorkOrderRepository:
    """生产工单仓库"""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_all(self, status_filter: str = "") -> List[sqlite3.Row]:
        """获取所有工单，可按状态筛选。"""
        if status_filter:
            return self.db.fetch_all(
                "SELECT * FROM work_orders WHERE status = ? ORDER BY created_at DESC",
                (status_filter,)
            )
        return self.db.fetch_all("SELECT * FROM work_orders ORDER BY created_at DESC")

    def get_by_id(self, order_id: int) -> Optional[sqlite3.Row]:
        return self.db.fetch_one("SELECT * FROM work_orders WHERE id = ?", (order_id,))

    def insert(self, order_number: str, bom_name: str, planned_qty: int, remark: str = "") -> int:
        cursor = self.db.execute(
            "INSERT INTO work_orders (order_number, bom_name, planned_qty, status, remark) "
            "VALUES (?, ?, ?, 'LOCKED', ?)",
            (order_number, bom_name, planned_qty, remark)
        )
        return cursor.lastrowid

    def complete(self, order_id: int, actual_qty: int):
        """将工单标记为完成。"""
        self.db.execute(
            "UPDATE work_orders SET actual_qty = ?, status = 'COMPLETED', "
            "completed_at = datetime('now', 'localtime') WHERE id = ?",
            (actual_qty, order_id)
        )

    def cancel(self, order_id: int):
        """取消工单（释放所有锁定库存）。"""
        self.db.execute(
            "UPDATE work_orders SET status = 'CANCELLED', "
            "completed_at = datetime('now', 'localtime') WHERE id = ?",
            (order_id,)
        )

    def get_items(self, order_id: int) -> List[sqlite3.Row]:
        """获取工单的物料明细（含 JOIN parts 查询物料名称和料号）。"""
        return self.db.fetch_all(
            "SELECT woi.*, p.part_number, p.name AS part_name, p.package, p.location "
            "FROM work_order_items woi "
            "JOIN parts p ON woi.part_id = p.id "
            "WHERE woi.work_order_id = ?",
            (order_id,)
        )

    def insert_item(self, work_order_id: int, part_id: int,
                    required_qty: int, locked_qty: int):
        """添加工单物料明细。"""
        self.db.execute(
            "INSERT INTO work_order_items (work_order_id, part_id, required_qty, locked_qty) "
            "VALUES (?, ?, ?, ?)",
            (work_order_id, part_id, required_qty, locked_qty)
        )

    def update_item_consumption(self, item_id: int, actual_consumed_qty: int, returned_qty: int):
        """更新物料明细的实际消耗与退库数量。"""
        self.db.execute(
            "UPDATE work_order_items SET actual_consumed_qty = ?, returned_qty = ? WHERE id = ?",
            (actual_consumed_qty, returned_qty, item_id)
        )


class TransactionRepository:
    """库存流水仓库"""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_all(self, part_number: str = "", trans_type: str = "",
                date_from: str = "", date_to: str = "") -> List[sqlite3.Row]:
        """
        查询库存流水，支持多条件筛选。
        """
        sql = """
            SELECT t.*, p.part_number, p.name AS part_name
            FROM inventory_transactions t
            JOIN parts p ON t.part_id = p.id
            WHERE 1=1
        """
        params: List[Any] = []

        if part_number:
            sql += " AND p.part_number LIKE ?"
            params.append(f"%{part_number}%")
        if trans_type:
            sql += " AND t.transaction_type = ?"
            params.append(trans_type)
        if date_from:
            sql += " AND t.created_at >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND t.created_at <= ?"
            params.append(date_to + " 23:59:59")

        sql += " ORDER BY t.created_at DESC, t.id DESC"
        return self.db.fetch_all(sql, tuple(params))

    def insert(self, part_id: int, transaction_type: str, quantity: int,
               work_order_id: int = None, remark: str = "") -> int:
        """
        记录一条库存流水。
        quantity: 入库为正数，出库/消耗为负数。
        """
        cursor = self.db.execute(
            "INSERT INTO inventory_transactions (part_id, transaction_type, quantity, work_order_id, remark) "
            "VALUES (?, ?, ?, ?, ?)",
            (part_id, transaction_type, quantity, work_order_id, remark)
        )
        return cursor.lastrowid

    def get_by_id(self, trans_id: int) -> Optional[sqlite3.Row]:
        """按ID获取单条流水记录（含料号、名称）。"""
        return self.db.fetch_one(
            """SELECT t.*, p.part_number, p.name AS part_name
               FROM inventory_transactions t
               JOIN parts p ON t.part_id = p.id
               WHERE t.id = ?""",
            (trans_id,)
        )

    def batch_insert(self, records: List[tuple]) -> List[int]:
        """批量插入流水记录。
        records: 列表，每项为 (part_id, transaction_type, quantity, work_order_id, remark)。
        返回所有新插入的 ID 列表。"""
        ids: List[int] = []
        for rec in records:
            part_id, trans_type, qty, wo_id, remark = rec
            tid = self.insert(part_id, trans_type, qty, wo_id, remark)
            ids.append(tid)
        return ids


class BomRepository:
    """BOM 结构明细仓库 — 管理本地保存的 BOM 物料清单"""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_all_names(self) -> List[str]:
        """获取所有不重复的 BOM 名称列表。"""
        rows = self.db.fetch_all(
            "SELECT DISTINCT bom_name FROM bom_items ORDER BY bom_name"
        )
        return [r["bom_name"] for r in rows]

    def get_items_by_name(self, bom_name: str) -> List[sqlite3.Row]:
        """获取指定 BOM 的所有明细（JOIN parts 获取物料名称和封装）。"""
        return self.db.fetch_all(
            "SELECT bi.*, p.name AS part_name, p.package, p.location, "
            "p.stock_qty, p.locked_qty "
            "FROM bom_items bi "
            "JOIN parts p ON bi.part_number = p.part_number "
            "WHERE bi.bom_name = ? "
            "ORDER BY bi.id",
            (bom_name,)
        )

    def find_by_name(self, bom_name: str) -> List[sqlite3.Row]:
        """模糊搜索 BOM 名称。"""
        return self.db.fetch_all(
            "SELECT DISTINCT bom_name FROM bom_items WHERE bom_name LIKE ? ORDER BY bom_name",
            (f"%{bom_name}%",)
        )

    def insert_item(self, bom_name: str, part_number: str,
                    qty_per_unit: int, remark: str = "") -> int:
        """向 BOM 中添加一行物料。"""
        cursor = self.db.execute(
            "INSERT INTO bom_items (bom_name, part_number, qty_per_unit, remark) "
            "VALUES (?, ?, ?, ?)",
            (bom_name, part_number, qty_per_unit, remark)
        )
        return cursor.lastrowid

    def update_item(self, item_id: int, qty_per_unit: int, remark: str = ""):
        """更新 BOM 明细中的用量和备注。"""
        self.db.execute(
            "UPDATE bom_items SET qty_per_unit = ?, remark = ?, "
            "updated_at = datetime('now', 'localtime') WHERE id = ?",
            (qty_per_unit, remark, item_id)
        )

    def delete_item(self, item_id: int):
        """删除 BOM 中的一行物料。"""
        self.db.execute("DELETE FROM bom_items WHERE id = ?", (item_id,))

    def delete_bom(self, bom_name: str):
        """删除整个 BOM 及其所有明细。"""
        self.db.execute("DELETE FROM bom_items WHERE bom_name = ?", (bom_name,))

    def rename_bom(self, old_name: str, new_name: str):
        """重命名 BOM。"""
        self.db.execute(
            "UPDATE bom_items SET bom_name = ?, updated_at = datetime('now', 'localtime') "
            "WHERE bom_name = ?",
            (new_name, old_name)
        )

    def count_items(self, bom_name: str) -> int:
        """统计某个 BOM 的物料种类数。"""
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM bom_items WHERE bom_name = ?", (bom_name,)
        )
        return row["cnt"] if row else 0

    def to_dataframe(self, bom_name: str):
        """
        将 BOM 明细导出为 pandas DataFrame（用于导出 Excel）。
        列：内部料号, 名称, 封装, 单份用量, 备注
        """
        import pandas as pd
        items = self.get_items_by_name(bom_name)
        data = []
        for it in items:
            data.append({
                "内部料号": it["part_number"],
                "名称": it["part_name"],
                "封装": it["package"] or "",
                "单份用量": it["qty_per_unit"],
                "备注": it["remark"] or "",
            })
        return pd.DataFrame(data)

    def export_to_excel(self, bom_name: str, file_path: str):
        """将 BOM 导出为 Excel 文件。"""
        df = self.to_dataframe(bom_name)
        df.to_excel(file_path, index=False, engine="openpyxl")
        return len(df)


class SupplierRepository:
    """供应商信息仓库 — 管理供应商的增删改查"""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_all(self) -> List[sqlite3.Row]:
        """获取所有供应商，按名称排序。"""
        return self.db.fetch_all("SELECT * FROM suppliers ORDER BY name")

    def get_by_id(self, supplier_id: int) -> Optional[sqlite3.Row]:
        """按 ID 查询供应商。"""
        return self.db.fetch_one("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))

    def insert(self, name: str, contact_person: str = "", phone: str = "",
               email: str = "", website: str = "", address: str = "",
               remark: str = "") -> int:
        """新增供应商，返回新 ID。"""
        cursor = self.db.execute(
            "INSERT INTO suppliers (name, contact_person, phone, email, website, address, remark) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, contact_person, phone, email, website, address, remark)
        )
        return cursor.lastrowid

    def update(self, supplier_id: int, **kwargs):
        """更新供应商字段。"""
        if not kwargs:
            return
        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [supplier_id]
        self.db.execute(
            f"UPDATE suppliers SET {set_clause} WHERE id = ?",
            tuple(values)
        )

    def delete(self, supplier_id: int) -> bool:
        """删除供应商。若有关联物料则不允许删除。"""
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM parts WHERE supplier_id = ?",
            (supplier_id,)
        )
        if row and row["cnt"] > 0:
            return False  # 有关联物料，禁止删除
        self.db.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
        return True


# ============================================================
# 独立运行入口（用于测试数据库初始化）
# ============================================================

if __name__ == "__main__":
    db = init_database()
    # 验证：打印物料数量
    parts = PartRepository(db).get_all()
    print(f"物料总数: {len(parts)}")
    for p in parts:
        print(f"  {p['part_number']} | {p['name'][:20]:20s} | 库存:{p['stock_qty']:5d} | 可用:{p['available_qty']:5d} | 库位:{p['location']}")
    db.close()
