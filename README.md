# Zemax MCP 工具链

用自然语言驱动 Ansys Zemax OpticStudio 做光学设计 —— 将 73 个 Zemax 工具封装为 MCP 工具，另提供 1 个服务器重连工具，共向客户端提供 74 个工具。任何支持 MCP 的 Agent 客户端（WorkBuddy / VS Code Copilot / Claude Desktop）都能直接调用。

## 一句话架构

```
Agent 客户端  ──stdio──▶  mcp_server.py  ──▶  tools.py (73 个 Zemax 工具)  ──▶  ZOS-API (COM)  ──▶  OpticStudio
```

服务器本身**不启动 Zemax**，它连接到正在运行的 OpticStudio 实例。

## 两种连接模式

| 模式                  | 说明                                                                                 | 适用                            |
| --------------------- | ------------------------------------------------------------------------------------ | ------------------------------- |
| `extension`（默认） | 连接已打开的 OpticStudio，需先在 Zemax 里点 `Programming → Interactive Extension` | 边看界面边改，推荐              |
| `standalone`        | 由 Python 直接拉起一个新的隐形实例                                                   | 无人值守 / 批处理，多花 15–20s |

## 快速开始

```bash
# 1. 依赖（Python 3.13）
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 2. 配置
copy .env.example .env        # ZEMAX_MODE=extension, ZEMAX_INSTANCE=0

# 3. 客户端注册（示例见 claude_desktop_config_example.json）
#    command: .venv/Scripts/python.exe
#    args:    mcp_server.py --zemax-mode extension --instance 0
```

启动后第一次工具调用会自动连 Zemax（失败重试 2 次），也可手动调 `reconnect_zemax`。

## 工具分类

| 类别      | 工具                                                                                                                                                                                                                                                                                                                                                                                                                       |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 会话      | `get_project_context` `get_system_info` `new_file` `open_file` `save_file` `list_backups` `reconnect_zemax` `update_ui`                                                                                                                                                                                                                                                                                    |
| 镜头数据  | `insert_surface` `remove_surface` `edit_surface` `set_surface_type` `set_asphere_coefficients` `get_asphere_coefficients` `make_variable` `set_aperture` `set_fields` `set_wavelengths`                                                                                                                                                                                                                    |
| 评价函数  | `add_operand` `edit_operand` `remove_operands` `clear_operands` `build_operand_block` `get_operands` `get_merit_function` `get_merit_breakdown` `set_default_merit_function` `set_default_merit_function_after_current_block`                                                                                                                                                                          |
| 优化      | `run_optimization` `quick_focus`                                                                                                                                                                                                                                                                                                                                                                                       |
| 像质分析  | `get_mtf` `get_mtf_curve` `get_fft_mtf_vs_field` `get_spot_diagram_data` `get_opd_fan_data` `get_ray_fan_data` `get_wavefront_map_data` `get_image_quality` `get_aberrations` `get_distortion` `get_field_curvature_distortion_data` `get_lateral_color_data` `get_longitudinal_aberration_data` `get_relative_illumination_data` `get_vignetting_diagram_data` `check_field_illumination` |
| 一阶/材料 | `get_first_order_data` `get_glass_catalogs` `set_glass_catalogs` `set_ray_aiming` `get_ray_aiming_settings`                                                                                                                                                                                                                                                                                                      |
| 无热化    | `set_temperature_configs` `add_thermal_pickup_solve` `set_thermal_glass_tce` `optimize_athermal` `get_thermal_defocus`                                                                                                                                                                                                                                                                                                  |
| 公差分析  | `set_tolerances` `run_tolerance_sensitivity` `run_tolerance_monte_carlo` `get_tolerance_report` `set_tolerance_compensator`                                                                                                                                                                                                                                                                                              |
| 交付      | `open_layout` `export_analysis_data` `generate_validation_report` `check_manufacturability`                                                                                                                                                                                                                                                                                                                        |

## 已完成的案例

`zemax-ADAS/` 下是双高斯物镜的设计文件（f′=100 mm，F/3，2ω=28°）：

| 文件                       | 内容                                                              |
| -------------------------- | ----------------------------------------------------------------- |
| `双高斯.zos` / `.ZDA`  | 首版：7 半径 + 离焦量，MF=0.181，RSCE≈0.13 mm                    |
| `双高斯2.zos` / `.ZDA` | 改进版：自定义约束 + 点列图向导，MF=0.00177，AXCL 0.138→0.002 mm |

## 踩过的坑（值得先读）

1. **同会话 COM 写完立即读回是陈旧值** —— 看起来像没生效，其实已生效。要验证请新建连接读。
2. **`mcp` 包必须锁 1.x** —— 项目用的是 `@server.list_tools()`，2.x 已移除该 API。
3. **LDE 结构性操作有 COM 时序问题** —— `InsertNewSurfaceAt` 后立刻写属性会错乱，优先用 `edit_surface` 而不是裸 COM。
4. **extension 槽位全废时别改代码** —— 那是 .NET Remoting 注册状态烂了，重启电脑即可恢复（重启 Zemax 无效）。
5. **`set_wavelengths` 会重置评价函数的波长引用** —— AXCL/LACL 的 (1,3) 会变 (1,1)，改完要复查操作数。

## 目录

```
mcp_server.py        MCP 协议入口（stdio，工具声明与路由）
tools.py             73 个 Zemax 工具的实现 + JSON Schema
zemax_connection.py  ZOS-API 连接与会话管理
logger.py            日志（滚动、多进程安全）
.github/skills/      Zemax 技能真源（唯一物理副本，入库；Copilot 与队友读取）
.workbuddy/skills/   软链(Junction) → .github/skills，供 WorkBuddy 读取（不入库）
.dsh/skills/         软链(Junction) → .github/skills，供 DSH 读取（不入库）
scripts/             WorkBuddy 重启脚本与探针脚本
zemax-ADAS/          设计案例文件
```

## 技能（skills）

技能只有**一份物理副本**：`.github/skills/`（入库）。另外两个路径是指向它的 Windows 目录软链，
从任一路径读写都会立刻体现在其他路径，所以多 agent 共同编写时不会出现内容漂移。

| 路径                  | 谁读                                             | 与真源的关系        | 入库 |
| --------------------- | ------------------------------------------------ | ------------------- | ---- |
| `.github/skills/`     | VS Code Copilot、队友；项目 Zemax 技能**真源**   | 物理目录本身        | 是   |
| `.workbuddy/skills/`  | WorkBuddy 项目级                                 | Junction（目录软链）| 否   |
| `.dsh/skills/`        | DSH 项目级（rank 100，优先于全局）               | Junction（目录软链）| 否   |
| `~/.dsh/skills/`      | DSH 全局（通用技能）                             | 独立目录            | 否   |

> **软链不会被 git 克隆出来。** 新克隆仓库或换机器后 `.workbuddy/skills`、`.dsh/skills` 都不存在，
> 对应 agent 就看不到项目级技能。此时手工重建两条 Junction（`cmd` 里执行，无需管理员权限）：
>
> ```bat
> mklink /J "D:\Zemax-mcp\.workbuddy\skills" "D:\Zemax-mcp\.github\skills"
> mklink /J "D:\Zemax-mcp\.dsh\skills"      "D:\Zemax-mcp\.github\skills"
> ```
>
> 重建后验证：`dir /AL` 应能看到两行 `<JUNCTION>`；再确认任一 agent 里四个项目技能都能列出。
> （原先的自动检查脚本 `scripts/sync_skills.py` 已于 2026-10-27 按用户要求删除，软链长期存在、无需常驻校验。）

- 项目级四个：`system-setup-by-type`、`zemax-ADAS-skill`、`zemax-optical-design`、`zemax-zoom-lens-design`

## 环境要求

- Windows（ZOS-API 依赖 COM）
- Ansys Zemax OpticStudio 2024 R1（含 ZOS-API 许可）
- Python 3.13
