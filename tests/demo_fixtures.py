"""Synthetic records used only by tests with temporary databases."""

from database import DatabaseManager


def seed_test_data(db: DatabaseManager) -> None:
    parts = [
        ("RES-202405-000001", "10KΩ 0805 1% 贴片电阻", "0805", "B-02-05", "电阻", 2000, 0, 100),
        ("RES-202405-000002", "100Ω 0603 5% 贴片电阻", "0603", "B-02-06", "电阻", 1500, 0, 100),
        ("RES-202405-000003", "4.7KΩ 0805 1% 贴片电阻", "0805", "B-02-05", "电阻", 1800, 0, 100),
        ("CAP-202405-000001", "100nF 0805 50V MLCC", "0805", "C-01-01", "电容", 3000, 0, 200),
        ("CAP-202405-000002", "10µF 1206 25V 钽电容", "1206", "C-01-02", "电容", 500, 0, 50),
        ("CAP-202405-000003", "22pF 0603 50V NP0", "0603", "C-01-03", "电容", 1000, 0, 100),
        ("MCU-202405-000001", "STM32F103C8T6 ARM Cortex-M3", "LQFP-48", "A-01-01", "MCU", 50, 0, 5),
        ("MCU-202405-000002", "ESP32-WROOM-32E WiFi/BLE", "SMD-38", "A-01-02", "MCU", 30, 0, 3),
        ("LED-202405-000001", "红色 LED 0805 20mA", "0805", "D-01-01", "LED", 500, 0, 50),
        ("LED-202405-000002", "绿色 LED 0805 20mA", "0805", "D-01-01", "LED", 500, 0, 50),
        ("CON-202405-000001", "XH2.54-2P 直插插座", "P=2.54mm", "E-01-01", "连接器", 200, 0, 20),
        ("CON-202405-000002", "USB Type-C 16P 母座 SMD", "SMD-16", "E-01-02", "连接器", 100, 0, 10),
        ("DIO-202405-000001", "1N4148 SOD-123 开关二极管", "SOD-123", "D-02-01", "二极管", 800, 0, 100),
        ("DIO-202405-000002", "SS34 SMA 肖特基二极管 3A", "SMA", "D-02-02", "二极管", 300, 0, 50),
        ("PWR-202405-000001", "AMS1117-3.3 SOT-223 LDO", "SOT-223", "A-02-01", "电源IC", 120, 0, 10),
    ]
    db.executemany(
        "INSERT INTO parts (part_number, name, package, location, category, "
        "stock_qty, locked_qty, min_stock, supplier_id, unit_price) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)",
        parts,
    )
    for part_number, _, _, _, _, quantity, _, _ in parts:
        row = db.fetch_one("SELECT id FROM parts WHERE part_number = ?", (part_number,))
        db.execute(
            "INSERT INTO inventory_transactions (part_id, transaction_type, quantity, remark) "
            "VALUES (?, 'INBOUND', ?, '测试初始库存')",
            (row["id"], quantity),
        )

    bom_name = "STM32F103C8T6 核心板 V1.2"
    bom_rows = [
        (bom_name, "MCU-202405-000001", 1, "主控芯片"),
        (bom_name, "RES-202405-000001", 2, "BOOT0/BOOT1 上下拉"),
        (bom_name, "RES-202405-000002", 1, "LED 限流"),
        (bom_name, "CAP-202405-000001", 4, "电源去耦"),
        (bom_name, "CAP-202405-000003", 2, "晶振负载"),
        (bom_name, "LED-202405-000001", 1, "电源指示"),
        (bom_name, "CON-202405-000002", 1, "USB 接口"),
        (bom_name, "PWR-202405-000001", 1, "3.3V LDO 稳压"),
        (bom_name, "DIO-202405-000001", 2, "保护二极管"),
    ]
    db.executemany(
        "INSERT INTO bom_items (bom_name, part_number, qty_per_unit, remark) VALUES (?, ?, ?, ?)",
        bom_rows,
    )
