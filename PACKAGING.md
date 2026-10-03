# 可执行文件打包与首次运行

## Windows `.exe` 打包

建议在干净的 Python 虚拟环境中构建，以缩小 exe 体积。在项目目录中安装运行依赖和打包工具：

```powershell
python -m venv .build-venv
.build-venv\Scripts\python -m pip install -r requirements.txt
.build-venv\Scripts\python -m pip install -r build-requirements.txt
.build-venv\Scripts\python build_executable.py
```

默认生成 `dist/ComponentInventory.exe`。脚本只将源码依赖和 `theme_assets/` 打包，不会将 `inventory.db`、`Backups/`、Excel 导出文件或 `config.ini` 装入可执行文件。macOS/Linux 运行同一脚本会生成对应平台的可执行文件；构建应在目标操作系统上进行。

## 首次运行的数据目录

第一次启动会弹出文件夹选择窗口：

- 选择某个现有文件夹：数据库 `inventory.db`、自动备份 `Backups/`，以及默认的标签/Excel 导出位置会使用该文件夹。
- 取消选择：使用可执行文件所在文件夹。

程序把选择保存到**可执行文件同目录**的 `config.ini`，下次启动直接使用。取消选择时配置存储相对路径 `.`，因此一起移动 exe 与配置文件后，仍以新 exe 目录作为数据目录。亮色、暗色和自定义颜色设置也保存在这个配置文件中。

请将 exe 放在可写入配置文件的位置。如果旧配置指向的数据文件夹不再存在，程序会要求重新选择；取消这次重新选择会中止启动，以免误建一个空数据库。

## 分发

可只分发 `ComponentInventory.exe`。首次运行会生成配置与只有空表的数据库，不会自动插入物料、BOM 或流水；如需迁移已有真实数据，应先备份，再把 `inventory.db` 放到用户选择的数据文件夹。程序不会自动清空既有数据库。不要把真实库存数据库或备份上传到公开仓库。
