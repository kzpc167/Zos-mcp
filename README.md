# Zemax MCP 工具链

用自然语言驱动 **Ansys Zemax OpticStudio** 做光学设计：把 **74 个 Zemax 操作**封装成
MCP（Model Context Protocol）工具，另加 1 个服务器重连工具，共向客户端提供 **75 个工具**。
Claude Code / Claude Desktop / VS Code Copilot / WorkBuddy / DSH 等支持 MCP 的客户端都能直接调用。

配套还有 8 个 Zemax 技能（skill），把设计方法论、判据、踩坑记录注入 Agent，
让它在建面表、跑优化、做公差与无热化时按工程规范执行，而不是即兴发挥。

> **怎么读这份文档**：第一次用 → §2 安装；想知道有哪些能力 → §3；
> 看真实交付长什么样 → §4；遇到报错 → §8；写 MATLAB 脚本 → §6。

---

## 1 架构

```
Agent 客户端  ──stdio──▶  mcp_server.py  ──▶  tools.py（74 个工具）  ──▶  ZOS-API（COM）  ──▶  OpticStudio
```

服务器**不启动 Zemax**，它连接到正在运行的 OpticStudio 实例（或由它代为拉起）。

| 模式                  | 说明                                                                                 | 适用                             |
| --------------------- | ------------------------------------------------------------------------------------ | -------------------------------- |
| `extension`（默认） | 连接已打开的 OpticStudio，需先在 Zemax 里点 `Programming → Interactive Extension` | 边看界面边改，推荐               |
| `standalone`        | 由 Python 直接拉起一个新的隐形实例                                                   | 无人值守 / 批处理，多花 15–20 s |

> ⚠️ **同机不要用两个客户端同时接 extension。** 一个 Zemax 实例只服务一个客户端会话；
> 交替连接会破坏 .NET Remoting 注册状态，表现为所有槽位 `RemotingException`——
> 重启 Zemax 无效，只能重启电脑。另一侧请改用 `--zemax-mode standalone`。

---

## 2 安装（Windows）

### 2.1 前置条件

| 项          | 要求                                        | 说明                                                     |
| ----------- | ------------------------------------------- | -------------------------------------------------------- |
| 操作系统    | Windows 10 / 11                             | ZOS-API 依赖 COM，不支持 Linux/macOS                     |
| OpticStudio | Ansys Zemax **2024 R1**               | 需含 **ZOS-API 许可**；其他版本未验证              |
| Python      | **3.13**（本项目验证版本 3.13.14）    | 3.10+ 理论可用，但 `pywin32` 的 ZOS-API 映射未逐一验证 |
| MATLAB      | R2025b（**可选**）                    | 只有需要统计/拟合/出图时才装，见 §3.8                   |
| 网络        | 首次装依赖需要 PyPI；克隆 GitHub 国内需代理 | —                                                       |

OpticStudio 是否带 ZOS-API 许可：打开 Zemax，菜单里有 `Programming → Interactive Extension` 即有。

### 2.2 获取代码

```bat
git clone https://github.com/kzpc167/Zos-mcp.git Zemax-mcp
cd Zemax-mcp
```

下文命令都在仓库根目录执行。仓库不绑定安装路径，但示例配置按 `D:\Zemax-mcp` 写，
装在别处时需同步改 §3.6 的两份 JSON。

### 2.3 Python 环境

```bat
python -m venv .venv
:: 若 python 不在 PATH：py -3.13 -m venv .venv
.venv\Scripts\activate
.venv\Scripts\pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

验证依赖装齐（不报错即可）：

```bat
.venv\Scripts\python.exe -c "import win32com.client, mcp, dotenv, psutil; print('ok')"
```

依赖只有 5 项：`pywin32`（COM 驱动）、`mcp>=1.0,<2`（**必须锁 1.x**，2.x 移除了本项目使用的
`Server.list_tools` API）、`python-dotenv`、`concurrent-log-handler`、`psutil`。

### 2.4 配置连接参数

```bat
copy .env.example .env
```

`.env` 只有两项，默认即推荐值：

```ini
ZEMAX_MODE=extension
ZEMAX_INSTANCE=0
```

也可以不改 `.env`，直接在命令行传 `--zemax-mode` / `--instance`（优先级更高）。

### 2.5 启动 OpticStudio 并激活 Extension

1. 打开 OpticStudio（建议以管理员身份运行，减少 COM 权限问题）。
2. 菜单 `Programming → Interactive Extension`，点击后 Zemax 进入等待连接状态。
3. 保持这个窗口开着，**不要最小化到托盘**（部分版本会因此断开监听）。

### 2.6 注册到 MCP 客户端（三选一）

仓库已内置两份配置，**路径对得上就能直接用**：

| 客户端          | 配置文件                                           | 说明                                                                                     |
| --------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Claude Code     | `.mcp.json`（项目级）                            | 在仓库根启动 `claude`，首次会询问是否信任项目 MCP 服务器，选允许；用 `/mcp` 查看状态 |
| VS Code Copilot | `.vscode/mcp.json`（工作区级）                   | 打开工作区 → MCP 面板 → 启动 `zemax-opticstudio`                                     |
| Claude Desktop  | 复制 `claude_desktop_config_example.json` 的内容 | 合并进 `%APPDATA%\Claude\claude_desktop_config.json`，重启 Claude                      |

Claude Desktop 的通用写法（**把路径换成自己的仓库位置，Windows 路径双反斜杠**）：

```json
{
  "mcpServers": {
    "zemax-opticstudio": {
      "command": "C:\\path\\to\\Zemax-mcp\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\path\\to\\Zemax-mcp\\mcp_server.py",
        "--zemax-mode", "extension",
        "--instance", "0"
      ],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

`PYTHONIOENCODING=utf-8` 建议保留：工具返回大量中文，缺它可能乱码或抛编码异常。

### 2.7 验证安装

1. OpticStudio 已打开，且已点过 `Interactive Extension`；
2. 在客户端里调用 **`get_project_context`** —— 正常会返回当前打开的 `.zos` 路径与工作目录；
3. 若提示未连接：先调用 `reconnect_zemax`（内部重试 3 次）；仍失败按 §8 排查。

第一次工具调用会自动连 Zemax（失败重试 2 次），所以"服务器已连接"≠"Zemax 已挂上"，
**判据是能跑通一次实际的 Zemax 工具**。

### 2.8 可选：MATLAB MCP

MATLAB 侧不是本项目的代码，用的是 MathWorks 官方 `matlab-mcp-server`：

1. 从 [releases](https://github.com/matlab/matlab-mcp-server/releases/latest) 下载
   `matlab-mcp-server-windows-x64.exe`，放到 `matlab-mcp\` 下（该目录不入库）。
2. 在客户端配置里追加（`--matlab-root` 指向自己的 MATLAB 安装目录，不要带 `\bin`）：

```json
"matlab": {
  "type": "stdio",
  "command": "C:\\path\\to\\Zemax-mcp\\matlab-mcp\\matlab-mcp-server-windows-x64.exe",
  "args": [
    "--matlab-root=C:\\Program Files\\MATLAB\\R2025b",
    "--log-folder=C:\\path\\to\\Zemax-mcp\\matlab-mcp\\logs",
    "--matlab-session-mode=auto",
    "--initialize-matlab-on-startup=true"
  ]
}
```

3. 验证：调用 `detect_matlab_toolboxes`，能列出 MATLAB 版本与工具箱即成功。
4. 连不上时见 §8「MATLAB MCP 异常」；`scripts/restart_matlab_mcp.py` 可一键修复。

`matlab-mcp/` 里是上游仓库的源码（单独 git，被 `.gitignore` 排除），升级时按其 README 重新编译或换二进制即可。

### 2.9 可选：技能目录软链

技能只有**一份物理副本**：`.github/skills/`（入库）。其他路径都是指向它的目录链接：

| 路径                   | 谁读                                      | 与真源的关系 | 入库 |
| ---------------------- | ----------------------------------------- | ------------ | ---- |
| `.github/skills/`    | VS Code Copilot、队友；**技能真源** | 物理目录本身 | 是   |
| `.claude/skills/`    | Claude Code 项目级                        | 符号链接     | 否   |
| `.workbuddy/skills/` | WorkBuddy 项目级                          | Junction     | 否   |
| `.dsh/skills/`       | DSH 项目级                                | Junction     | 否   |

**新克隆的仓库里这些链接都不存在**（git 不传输链接，且路径已被忽略），需要手工重建。
`cmd` 里执行，不需要管理员权限：

```bat
cd /d D:\Zemax-mcp
mkdir .claude .workbuddy .dsh 2>nul
mklink /J ".claude\skills"    ".github\skills"
mklink /J ".workbuddy\skills" ".github\skills"
mklink /J ".dsh\skills"       ".github\skills"
```

验证：`dir /AL` 能看到 `<JUNCTION>` 行；再在客户端里确认技能列表非空。

8 个项目技能随仓库分发；另有 2 个外部技能（`lab-book-skill`、`neat-freak`）是独立仓库、
未入库，需要时单独 clone 到 `.github/skills/` 下（例如
`git clone https://github.com/Wavesflow/lab-book-skill.git .github/skills/lab-book-skill`）。

### 2.10 第一次使用

装好并验证通过后，直接用自然语言下指令即可，例如：

- 「打开 `zemax-ADAS/stopfix_v8/长后焦_v8_Z115_SDopt10_R11_20261122.zos`，报一下一阶量、MTF@120 和畸变」
- 「把 S1 的 A4 放开，只做局部优化，完成后复跑原生 MTF 并出 3D 布局图」
- 「按 Q5 等级跑公差，500 次蒙特卡洛，后焦作补偿器，给良率和最敏感项」
- 「做 −40 ~ +125 ℃ 无热化，给调焦行程和全温 MTF」

> 关键约束：**验收只信原生分析**（原生 FFT MTF / Standard Spot / Field Curvature / Relative Illumination），
> 不要拿 `get_image_quality` 的 RSCE 当验收读数。原因见 §8.2。

---

## 3 工具一览（75 个）

| 类别        | 数量 | 工具                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ----------- | ---: | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 会话 / 文件 |    8 | `get_project_context` `get_system_info` `new_file` `open_file` `save_file` `list_backups` `update_ui` `reconnect_zemax`                                                                                                                                                                                                                                                                                    |
| 镜头数据    |   12 | `insert_surface` `remove_surface` `edit_surface` `set_surface_type` `set_asphere_coefficients` `get_asphere_coefficients` `make_variable` `set_model_glass` `set_solve` `set_aperture` `set_fields` `set_wavelengths`                                                                                                                                                                              |
| 评价函数    |   10 | `add_operand` `edit_operand` `remove_operands` `clear_operands` `build_operand_block` `get_operands` `get_merit_function` `get_merit_breakdown` `set_default_merit_function` `set_default_merit_function_after_current_block`                                                                                                                                                                          |
| 优化        |    5 | `run_optimization` `quick_focus` `start_hammer` `get_hammer_status` `stop_hammer`                                                                                                                                                                                                                                                                                                                                |
| 一阶 / 材料 |    5 | `get_first_order_data` `get_glass_catalogs` `set_glass_catalogs` `set_ray_aiming` `get_ray_aiming_settings`                                                                                                                                                                                                                                                                                                      |
| 像质分析    |   16 | `get_mtf` `get_mtf_curve` `get_fft_mtf_vs_field` `get_spot_diagram_data` `get_opd_fan_data` `get_ray_fan_data` `get_wavefront_map_data` `get_image_quality` `get_aberrations` `get_distortion` `get_field_curvature_distortion_data` `get_lateral_color_data` `get_longitudinal_aberration_data` `get_relative_illumination_data` `get_vignetting_diagram_data` `check_field_illumination` |
| 无热化      |    6 | `set_temperature_configs` `build_thermal_model` `add_thermal_pickup_solve` `set_thermal_glass_tce` `optimize_athermal` `get_thermal_defocus`                                                                                                                                                                                                                                                                   |
| 公差分析    |    5 | `set_tolerances` `run_tolerance_sensitivity` `run_tolerance_monte_carlo` `get_tolerance_report` `set_tolerance_compensator`                                                                                                                                                                                                                                                                                      |
| 出图 / 交付 |    8 | `open_layout` `export_layout_image` `export_spot_diagram_image` `export_analysis_data` `export_all_figures` `check_interference` `check_manufacturability` `generate_validation_report`                                                                                                                                                                                                                    |

---

## 4 案例：车载长焦前摄 15 mm F/1.4

`zemax-ADAS/` 下是该项目的完整交付。结构形式为**双高斯演化**：6 元件 / 7 片玻璃
（S6–S8 为胶合双胶合），光阑居中，S1 与 S11 为偶次非球面，7 片玻璃全部为成都光明（CDGM）真实牌号。

| 目录                      | 内容                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------- |
| **`stopfix_v8/`** | **当前交付版**：L7 前表面 R = −7.100，解除半球超限；含设计、无热化、Q5 公差、鬼影全套 |
| `ir_cut/`               | 定心系数版 + IR-CUT 窗口变体（历史交付）                                                     |
| `no_ir_cut/`            | 定心系数版，不加窗口（历史交付）                                                             |

`stopfix_v8/` 关键指标（25 ℃，原生分析读数）：

| 指标                           | 要求                    | 实测                                             |
| ------------------------------ | ----------------------- | ------------------------------------------------ |
| 焦距 / F 数                    | 15 ± 5 % / F1.4        | **15.0372 mm** / F1.40                     |
| 视场                           | 对角 ≥ 34°            | **34.85°**（半角 17.427°）               |
| 总长                           | ≈ 30 mm                | **29.9417 mm**                             |
| MTF@120 lp/mm（最差视场）      | > 0.5                   | **0.5109**（余量 0.011，最紧的一项）       |
| 最大畸变                       | < 1 %                   | 0.312 %                                          |
| 相对照度                       | ≥ 60 %                 | 83.42 %                                          |
| L7 r/R（半球）                 | ≤ 0.714                | **0.704** ✅                               |
| Q5 良率（500 次 MC，MTF 判据） | ≥ 90 %                 | **93.6 %** @名义 −20 %（CPK 0.43）        |
| 无热化（−40 ~ +125 ℃）       | 调焦后 MTF 跌幅 ≤ 20 % | 需要 **46.4 µm** 调焦行程，跌幅 10.7 % ✅ |
| 鬼影 GISET（支配项 15↔14）    | < 1e−3                 | **8.5e−5**（sensor 2 %、AR 0.5 %）        |

> **细节与判据口径以工程报告为准**：
> [`stopfix_v8/车载长焦前摄15mmF1.4_长后焦v8_R11_工程报告_20261122.md`](zemax-ADAS/stopfix_v8/车载长焦前摄15mmF1.4_长后焦v8_R11_工程报告_20261122.md)
> —— 含像质验收、半球专项、非球面面型、净空与 DFM、无热化、Q5 公差、鬼影（几何筛查 + MATLAB 一阶计算）。
> 同目录 `README.md` 是数据/图/脚本的索引。

设计文件职责严格分开，不可互换：

| 文件                                        | 用途                                |
| ------------------------------------------- | ----------------------------------- |
| `长后焦_v8_Z115_SDopt10_R11_20261122.zos` | 设计基准（单组态 25 ℃）            |
| `长后焦_v8_Z115_R11_无热化_20261122.zos`  | 温度组态副本（7 组 −40 ~ +125 ℃） |
| `长后焦_v8_Z115_R11_公差Q5_20261122.zos`  | 公差副本（69 条 TDE + 后焦补偿器）  |

带 MCE 组态的文件上跑公差会被热拾取硬值覆盖，结果全为 0；公差副本也不能拿去做无热化。

---

## 5 目录结构

```
mcp_server.py                    MCP 协议入口（stdio，工具声明与路由）
tools.py                         74 个 Zemax 工具的实现 + JSON Schema
zemax_connection.py              ZOS-API 连接与会话管理
logger.py                        日志（滚动、多进程安全）
requirements.txt                 Python 依赖
.env.example                     连接配置模板
claude_desktop_config_example.json  Claude Desktop 注册示例
.mcp.json                        Claude Code 项目级 MCP 配置
.vscode/mcp.json                 VS Code 工作区 MCP 配置
.github/skills/                  技能真源（唯一物理副本，入库）
scripts/                         重启脚本、探针脚本、技能 lint、原生分析解析
zemax-ADAS/                      设计案例与交付文档

# 以下不入库（.gitignore）
.venv/                           虚拟环境
matlab-mcp/                      MathWorks matlab-mcp-server 源码与二进制
_archive/                        过期设计阶段产物（仅本地可回溯）
zemax-ADAS/backups/              Zemax 自动快照
logs/  tmp/                      运行日志与临时工作区
```

---

## 6 MATLAB 文件存放约定

MATLAB 脚本、数据和图**随所属设计项目存放**，不集中放进独立的 `matlab/` 目录：

```
zemax-ADAS/<版本>/                 例如 stopfix_v8/
  *.m                             可复现脚本，命名 <任务>_<日期>.m
  data/                            交换 CSV（一份数据一份文件）
  figs/                            300 dpi PNG
  analysis/                        脚本生成的文本摘要 / 日志
  legacy_<日期>/                   仅当旧脚本有独有数据、确需留档才建；冗余直接删
```

脚本内**禁止写死绝对路径**，统一自定位：

```matlab
base = fileparts(mfilename('fullpath'));
if isempty(base); base = pwd; end
dat = fullfile(base,'data');   % 取数
out = fullfile(base,'figs');   % 出图
```

这样任何一份交付目录拷走后都能独立重跑，也能从图/CSV 反查是哪支脚本生成。

---

## 7 技能（skills）

| 技能                          | 覆盖范围                                                   |
| ----------------------------- | ---------------------------------------------------------- |
| `zemax-ADAS-skill`          | 设计主体方法论：加载规则、红线、参数速查、分阶段优化、验收 |
| `zemax-asphere-skill`       | 非球面：k 受控优化、A4/A6、反曲/拐点、BFS、面型验收        |
| `zemax-athermal-skill`      | 无热化：热离焦原理、三条路线、MCE 与热拾取、调焦行程       |
| `zemax-tolerance-skill`     | 公差：Q1–Q8 等级、TDE 映射、蒙特卡洛良率与置信区间        |
| `zemax-ghost-skill`         | 鬼影与杂散光：三要素、Ghost Focus Generator、GISET/PST     |
| `zemax-matlab-skill`        | MATLAB 辅助：数据分析、拟合统计、出版级出图                |
| `zemax-zoom-lens-design`    | 变焦镜头设计                                               |
| `spherical-lens-dfm-review` | 球面透镜可制造性评审（DFM）：边厚、定心、胶合、成本        |

外部技能（独立仓库，未入库，按需 clone）：`lab-book-skill`（实验记录）、`neat-freak`（文件整理）。

技能改动后必须自检：

```bat
python scripts\lint_skill.py
```

它会检查跨文件 § 引用、编号连续性、`SKILL.md` 行数上限（300 行）和路由表文件是否存在，返回 0 才算改完。

---

## 8 常见问题与踩过的坑

### 8.1 连接 / 运行

| 现象                                 | 原因                                                       | 处理                                                      |
| ------------------------------------ | ---------------------------------------------------------- | --------------------------------------------------------- |
| 所有工具报 `RemotingException`     | .NET Remoting 注册状态损坏（常见于两个客户端同抢一个实例） | 重启电脑；之后严格一实例一客户端，另一侧用 `standalone` |
| 首次调用超时                         | Zemax 未激活 Interactive Extension，或还在冷启动           | 确认 Zemax 已点 Extension；调 `reconnect_zemax`         |
| 属性读写"不生效"                     | 同会话 COM 写完立即读回拿到陈旧值                          | 新建连接再读；或调工具层封装而不是裸 COM                  |
| `mcp` 导入报 `list_tools` 不存在 | 装成了 mcp 2.x                                             | 按 requirements 锁 `mcp>=1.0,<2`                        |
| 中文乱码 / 编码异常                  | 客户端未设 UTF-8                                           | 配置里加 `PYTHONIOENCODING=utf-8`                       |

### 8.2 工具层

1. **LDE 结构性操作用封装工具** —— `InsertNewSurfaceAt` 后立刻写属性会错乱，优先 `edit_surface`。
2. **`set_wavelengths` 会重置评价函数的波长引用** —— AXCL/LACL 的 `(1,3)` 可能变 `(1,1)`，改完复查操作数。
3. **布局图导出不能用 `Analysis.ToFile`** —— 图形窗口只写 ~148 字节文本；用 `export_layout_image`
   （内部 `Open3DViewerExport` + `RunAndWaitForCompletion`）。
4. **`check_field_illumination` 读数可疑** —— 历史上三个视场报同一个值（同值即 bug）；
   相对照度验收一律用 `get_relative_illumination_data`。
5. **`DIMX` 返回绝对值**，做不出负畸变；改畸变形状只能用像高类操作数，验收读原生
   FieldCurvatureAndDistortion 逐点数据。
6. **RSCE / `get_image_quality` 偏乐观** —— 同一状态曾少报 RMS 约 3 倍；RMS 只认原生 Standard Spot 文本。
7. **`run_optimization` / `set_default_merit_function` 会立即写回 `.zos`** —— "不保存"挡不住；
   回滚靠 `zemax-ADAS/backups/` 的自动快照（按 `文件名 + 操作 + 时间戳` 命名）。

更细的工具层坑（§T）、原理计算（§P）、案例数据（§C）见
`.github/skills/zemax-ADAS-skill/references/`。

### 8.3 MATLAB MCP 异常

**只监视、不修复**（保持 PowerShell 窗口开着）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_matlab_mcp.ps1
```

告警写入 `matlab-mcp/logs/watchdog-alerts.log`，并提示在 VS Code 的
**MCP: List Servers → MATLAB → Restart** 里重启。

**一键修复**（结束挂死的 matlab-mcp-server 与 MATLAB、备份 0 字节的 `toolbox_cache-*.xml`、
用 `matlab.engine.shareEngine` 重建共享引擎）：

```powershell
.venv\Scripts\python.exe scripts\restart_matlab_mcp.py --dry-run   # 先看计划
.venv\Scripts\python.exe scripts\restart_matlab_mcp.py             # 确认后执行
```

跑完仍需在客户端重连一次（Claude Code `/mcp`；VS Code MCP: Restart Server）。
客户端显示 connected 只代表 stdio 握手成功，**不代表 MATLAB 已挂上**——判据是能跑通一次
`detect_matlab_toolboxes`。
