# Zemax MCP 工具链

用自然语言驱动 Ansys Zemax OpticStudio 做光学设计 —— 把 **74 个 Zemax 操作**封装为 MCP 工具，另加 1 个服务器重连工具，共向客户端提供 **75 个工具**。任何支持 MCP 的 Agent 客户端（WorkBuddy / VS Code Copilot / Claude Desktop）都能直接调用。

## 一句话架构

```
Agent 客户端  ──stdio──▶  mcp_server.py  ──▶  tools.py（74 个工具）  ──▶  ZOS-API（COM）  ──▶  OpticStudio
```

服务器本身**不启动 Zemax**，它连接到正在运行的 OpticStudio 实例。

## 两种连接模式

| 模式                  | 说明                                                                                 | 适用                            |
| --------------------- | ------------------------------------------------------------------------------------ | ------------------------------- |
| `extension`（默认） | 连接已打开的 OpticStudio，需先在 Zemax 里点 `Programming → Interactive Extension` | 边看界面边改，推荐              |
| `standalone`        | 由 Python 直接拉起一个新的隐形实例                                                   | 无人值守 / 批处理，多花 15–20s |

> **同机不要用两个客户端同时接 extension**。一个 Zemax 实例只服务一个客户端会话，交替连接会把 .NET Remoting 注册状态搞烂，表现为所有槽位 `RemotingException`——重启 Zemax 无效，只能重启电脑。另一侧请改用 `--zemax-mode standalone`。

## 快速开始

大喊一声：deepseek救我，让AI帮你安装并配置环境。

```bash
# 1. 依赖（Python 3.13）
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 2. 配置
copy .env.example .env        # ZEMAX_MODE=extension, ZEMAX_INSTANCE=0

# 3. 客户端注册（示例见 claude_desktop_config_example.json）
#    command: .venv/Scripts/python.exe
#    args:    mcp_server.py --zemax-mode extension --instance 0
#    env:     PYTHONIOENCODING=utf-8
```

启动后第一次工具调用会自动连 Zemax（失败重试 2 次），也可手动调 `reconnect_zemax`（重试 3 次）。

## 工具分类

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

## 已完成案例：车载长焦前摄 15 mm F/1.4

`zemax-ADAS/` 下是该项目从设计到量产的完整交付。结构形式为**双高斯演化**，6 元件 / 7 片玻璃（S6–S8 为胶合双胶合），光阑居中，S1 与 S13 为偶次非球面，7 片玻璃全部为成都光明（CDGM）真实牌号。

| 指标                          | 要求             | 实测                                                                                |
| ----------------------------- | ---------------- | ----------------------------------------------------------------------------------- |
| 焦距 / F 数                   | 15 ± 5 % / F1.4 | **15.118 mm**（+0.79 %）/ **F/1.400**                                   |
| 视场                          | 2ω 35°         | **2ω 34.85°**，水平 30.2°                                                  |
| 总长                          | 30.5 ± 2 %     | **30.499 mm**                                                                 |
| 畸变                          | ≈ 1 %           | **0.394 %**                                                                   |
| 像圈                          | > 9.25 mm        | **9.46 mm**                                                                   |
| MTF@120 lp/mm                 | > 0.5            | 轴上 0.597 / 全视场 **0.447**（唯一未达标，Petzval 场曲固有弱项，已判定接受） |
| 良率（MTF > 0.35，500 次 MC） | —               | **99.0 %**，95 % CI [97.7, 99.6]                                              |
| 无热化（−40~125 ℃）         | —               | 调焦 +35.8~−56.9 µm 可完全补偿，调焦后边缘 MTF 0.446 ≈ 常温 0.442                |

| 文件                                  | 内容                                                          |
| ------------------------------------- | ------------------------------------------------------------- |
| `车载长焦前摄15mmF1.4_最终设计.zos` | **设计基准**：10 温度组态 + 热模型 + 全 CDGM 玻璃       |
| `车载长焦前摄15mmF1.4_公差定稿.zos` | **公差基准**：单组态 25 ℃、69 条 TDE、胶合组 ±0.01875 |
| `车载长焦前摄15mmF1.4_工程总结.md`  | 交付总结（光学指标 / 像质 / 热差与公差 / 杂散光鬼影）         |
| `车载长焦前摄15mmF1.4_设计报告.md`  | 完整设计推导与逐项验收数据                                    |
| `鬼影分析_一阶_20261104.md`         | 鬼影三要素分析（0 个锐利鬼影，最小弥散 571 µm）              |
| `公差报告_*.md`                     | 4 份蒙特卡洛原始报告（MTF 定稿 / MTF Q4 对比 / RMS / 灵敏度） |
| `layouts/`                          | 三维布局图、点列图、净空检查图                                |

**两个 .zos 职责严格分开，不可互换**：设计基准带 10 个温度组态，在它上面跑公差会被 MCE 硬值覆盖，结果全为 0；公差基准是剥掉组态的副本，也不能拿去做无热化。

## 踩过的坑（值得先读）

1. **同会话 COM 写完立即读回是陈旧值** —— 看起来像没生效，其实已生效。要验证请新建连接读。
2. **`mcp` 包必须锁 1.x** —— 项目用的是 `@server.list_tools()`，2.x 已移除该 API。
3. **LDE 结构性操作有 COM 时序问题** —— `InsertNewSurfaceAt` 后立刻写属性会错乱，优先用 `edit_surface` 而不是裸 COM。
4. **extension 槽位全废时别改代码** —— 那是 .NET Remoting 注册状态烂了，重启电脑即可恢复（重启 Zemax 无效）。
5. **`set_wavelengths` 会重置评价函数的波长引用** —— AXCL/LACL 的 (1,3) 会变 (1,1)，改完要复查操作数。
6. **布局图导出不能用 `Analysis.ToFile`** —— 图形窗口只写 148 字节文本；要用 `export_layout_image`（内部 `Open3DViewerExport` + `RunAndWaitForCompletion()`）。
7. **`check_field_illumination` 当前是坏的** —— 三个视场报同一个值（同值即 bug）。相对照度一律用 `get_relative_illumination_data`。
8. **`DIMX` 返回绝对值**，做不出负畸变；要改畸变形状只能用像高类操作数，且验收必须读原生 FieldCurvatureAndDistortion 逐点数据。

> 更细的工具层坑（§T）、原理计算（§P）、案例数据（§C）见 `.github/skills/zemax-ADAS-skill/references/`。

## 目录

```
mcp_server.py        MCP 协议入口（stdio，工具声明与路由）
tools.py             74 个 Zemax 工具的实现 + JSON Schema
zemax_connection.py  ZOS-API 连接与会话管理
logger.py            日志（滚动、多进程安全）
.github/skills/      Zemax 技能真源（唯一物理副本，入库；Copilot 与队友读取）
.workbuddy/skills/   软链(Junction) → .github/skills，供 WorkBuddy 读取（不入库）
.dsh/skills/         软链(Junction) → .github/skills，供 DSH 读取（不入库）
scripts/             重启脚本、探针脚本、技能 lint
zemax-ADAS/          设计案例与交付文档
```

## 技能（skills）

技能只有**一份物理副本**：`.github/skills/`（入库）。另外两个路径是指向它的 Windows 目录软链，从任一路径读写都会立刻体现在其他路径，所以多 agent 共同编写时不会出现内容漂移。

| 路径                   | 谁读                                                 | 与真源的关系         | 入库 |
| ---------------------- | ---------------------------------------------------- | -------------------- | ---- |
| `.github/skills/`    | VS Code Copilot、队友；项目 Zemax 技能**真源** | 物理目录本身         | 是   |
| `.workbuddy/skills/` | WorkBuddy 项目级                                     | Junction（目录软链） | 否   |
| `.dsh/skills/`       | DSH 项目级（rank 100，优先于全局）                   | Junction（目录软链） | 否   |
| `~/.dsh/skills/`     | DSH 全局（通用技能）                                 | 独立目录             | 否   |

> **软链不会被 git 克隆出来。** 新克隆仓库或换机器后 `.workbuddy/skills`、`.dsh/skills` 都不存在，对应 agent 就看不到项目级技能。此时手工重建两条 Junction（`cmd` 里执行，无需管理员权限）：
>
> ```bat
> mklink /J "D:\Zemax-mcp\.workbuddy\skills" "D:\Zemax-mcp\.github\skills"
> mklink /J "D:\Zemax-mcp\.dsh\skills"      "D:\Zemax-mcp\.github\skills"
> ```
>
> 重建后验证：`dir /AL` 应能看到两行 `<JUNCTION>`；再确认任一 agent 里各项目技能都能列出。

当前 10 个项目技能：

| 技能                       | 覆盖范围                                                   |
| -------------------------- | ---------------------------------------------------------- |
| `zemax-ADAS-skill`       | 镜头设计主体方法论：路由表、铁律、参数表、工作流、验收清单 |
| `zemax-optical-design`   | 通用光学设计与优化经验                                     |
| `zemax-asphere-skill`    | 非球面全流程：k 受控优化、A4/A6 交替固定、反曲与斜率校核   |
| `zemax-athermal-skill`   | 无热化：热离焦原理、三条路线、MCE 步骤                     |
| `zemax-tolerance-skill`  | 公差分析：Q1–Q8 加工等级、蒙特卡洛良率、置信区间判读      |
| `zemax-ghost-skill`      | 鬼影与杂散光：三要素、深度追迹、镀膜阈值                   |
| `zemax-zoom-lens-design` | 变焦镜头设计                                               |
| `system-setup-by-type`   | 按系统类型确定孔径/视场/波长设置                           |
| `lab-book-skill`         | 实验记录整理                                               |
| `neat-freak`             | 文件与目录整洁                                             |

技能改动后跑 `python scripts/lint_skill.py` 自检（检查行数上限与锚点）。

## 环境要求

- Windows（ZOS-API 依赖 COM）
- Ansys Zemax OpticStudio 2024 R1（含 ZOS-API 许可），运行中并已激活 Interactive Extension
- Python 3.13
