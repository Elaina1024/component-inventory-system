# 物料库存与 BOM 核销管理系统

本项目是本地运行的 PySide6 桌面应用，提供物料管理、BOM 导入与工单核销、计划外领料、供应商管理、库存流水、二维码标签、数据看板以及亮色/暗色外观设置。数据保存在用户选择目录中的 SQLite 数据库，不需要服务器。

## 安装与运行

在本目录打开终端，使用 Python 创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

上述依赖组合已在 Python 3.13.9 上验证。macOS/Linux 可将命令中的 `.venv\Scripts\python` 换成 `.venv/bin/python`。

首次启动会选择数据库及备份的存放文件夹；取消选择则使用程序所在目录。程序会在启动文件同目录生成 `config.ini` 记录该位置和界面设置，并在数据目录生成**没有业务记录的** `inventory.db`。数据库包含程序运行必需的空表，例如 `bom_items`；不会自动插入物料、BOM 或流水。退出应用时会在数据目录的 `Backups/` 下生成本地 JSON 备份。

Windows 可运行 `python build_executable.py` 生成 `dist/ComponentInventory.exe`。打包步骤与首次运行说明见 [可执行文件打包](PACKAGING.md)。

可运行 `python generate_example_bom.py` 重新生成匿名的 `example_bom.xlsx`。这是单独的示例文件，不会被打进 exe，也不会自动导入数据库。使用它体验 BOM 功能前，请先自行添加对应料号和库存。
