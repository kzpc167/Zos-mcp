---
name: zemax-matlab-skill
description: '在 Zemax 光学设计流程中调用 MATLAB MCP 做辅助计算与出图：像质数据后处理（点列图/MTF/相对照度/畸变）、非球面矢高·斜率·反曲·BFS 校核、公差蒙特卡洛统计（良率/CPK/置信区间）、热离焦拟合与补偿行程、鬼影一阶筛查、出版级图表批量生成。Use when: 需要把 Zemax 数据交给 MATLAB 分析或画图、跑 MATLAB 脚本/命令、做统计与曲线拟合、算面型导数与反曲点、算良率直方图和 CPK、拟合热离焦曲线、生成报告插图、MATLAB MCP 报错或连不上。关键词：MATLAB、MCP、matlab-mcp、evaluate_matlab_code、run_matlab_file、数据后处理、拟合、polyfit、fminsearch、蒙特卡洛、良率、CPK、直方图、置信区间、矢高、斜率、反曲、BFS、非球面度、热离焦、补偿行程、GISET、鬼影、出图、exportgraphics。报告级出图/统计/拟合必须实际调用 MATLAB，禁止 Python 静默替代。'
---

# MATLAB 辅助 Zemax 光学设计

> **定位**：MATLAB 不是设计引擎。序列/优化/追迹仍然全在 OpticStudio 里做（走 `mcp__zemax-opticstudio__*`）。
> MATLAB 只负责 Zemax 做不了或做不漂亮的部分：**数据分析、拟合、统计、出版级出图**。
> MATLAB 算出来的东西**不能替代 Zemax 追迹**，凡是"结论"必须回 Zemax 复核一次。

## 0. 什么时候必须切到 MATLAB

> **强制触发（交付级）**：出现以下任一交付物时，**必须实际调用 `mcp__matlab__*`**，不得用 Python / 内联计算 / `matplotlib` 静默替代：
> ① 写进报告或给用户看的图；② 批量曲线（MTF/RI/畸变/RMS vs 视场）；③ 统计（良率/CPK/置信区间/蒙特卡洛后处理）；④ 拟合（热离焦/多项式/补偿行程）；⑤ 面型导数、反曲点、BFS 校核。
>
> 只有临时 debug 图、一次性算术、<10 个数比较、日志整理可以用 Python —— 且**不得作为交付结果**。
> 若 MATLAB MCP 不可用：按 §6 排查并明确报告"MATLAB 未调用"，**禁止悄悄改用 Python 冒充 MATLAB 结果**。

**每次调用前**：在 Claude Code 等把 MCP 工具延迟加载的客户端里，先 `ToolSearch("select:mcp__matlab__detect_matlab_toolboxes,mcp__matlab__evaluate_matlab_code,mcp__matlab__run_matlab_file,mcp__matlab__check_matlab_code")` 加载 schema，再调用；全程串行。首次先跑 `detect_matlab_toolboxes`。

| 你要做的事 | MATLAB 负责 | 配套 skill |
|---|---|---|
| 面型校核：矢高、斜率、二阶导、反曲点、BFS 偏离、非球面度 | 解析计算 + 曲线 | `zemax-asphere-skill`（判据在那里） |
| 公差蒙特卡洛：良率、直方图、P95/P99、CPK、bootstrap 置信区间 | 统计与作图 | `zemax-tolerance-skill` |
| 无热化：BFL 漂移 vs 温度拟合、补偿行程、残差 | `polyfit` + 端点校核 | `zemax-athermal-skill` |
| 像质曲线：MTF/RI/畸变/RMS vs 视场，统一风格出图 | 绘图 | — |
| 鬼影一阶筛查：反射像位置、强度量级 | 矩阵光学 | `zemax-ghost-skill`（GISET 判据用 Zemax 实测） |
| 报告插图批量重绘、拼图、标注 | 绘图 | — |
| 外部优化（fmincon/ga/patternsearch） | 见 §4.6，**需明确授权** | `zemax-ADAS-skill` |

**不要切 MATLAB 的情况**：一次加减乘除、<10 个数的比较、Zemax 已经能直接出的标准图、日志/文件整理（用 Python 更快）。

## 1. 两个 MCP 的边界与数据流

```
mcp__zemax-opticstudio__*  →  JSON / export 文本  →  CSV (matlab/data/)  →  mcp__matlab__*  →  图/数值
                                                                                          ↓
                                                                              写回报告 .md / .png
```

| 事实 | 说明 |
|---|---|
| 两个 MCP 是**两个独立进程** | 不共享内存/变量；唯一通道是磁盘文件和工具返回的 JSON |
| MATLAB **不要**自己连 ZOS-API | 会和 MCP 抢同一个 COM 实例，导致 `Connection closed`（本项目未验证，不值得试） |
| 每个 MCP 内部**严格串行** | MATLAB 会话是单线程的；同一条消息里发两个 MATLAB 调用必出问题 |
| 跨 MCP 也要串行 | 先把 Zemax 数据全部取完，再一次性交给 MATLAB，不要来回横跳 |
| 大数组不进对话 | 工具返回的 JSON 由 agent 落成 CSV，或直接读 `layouts/analysis/*.txt` |

**Zemax 侧取数**（本项目实测可用）：

- `get_spot_diagram_data` / `get_mtf` / `get_fft_mtf_vs_field` / `get_mtf_curve`
- `get_relative_illumination_data` / `get_distortion` / `get_field_curvature_distortion_data`
- `get_thermal_defocus` / `get_asphere_coefficients` / `get_first_order_data`
- `run_tolerance_monte_carlo` → `get_tolerance_report`
- `export_analysis_data(analysis=..., export_text=True)`：导出文本落在 **`<当前 .zmx 所在目录>/layouts/analysis/`**，文件名固定、每次覆盖

## 2. MATLAB MCP 的五个工具：用法与坑

服务器就是 MathWorks 官方 `matlab-mcp-server`，本项目配置在 `.vscode/mcp.json`（MATLAB R2025b，`--matlab-session-mode=auto`，启动即初始化）。

| 工具 | 参数 | 注意 |
|---|---|---|
| `mcp__matlab__detect_matlab_toolboxes` | — | **开工先调**。确认 Optimization / Statistics / Image Processing 是否装了，否则后面代码要改写。本项目 2026-11-15 实测：R2025b 已装 Optimization / Statistics / Curve Fitting / Global Optimization / Image Processing / Symbolic Math |
| `mcp__matlab__evaluate_matlab_code` | `code`, `project_path`(必填) | `project_path` 会成为 MATLAB 的 cwd；只返回命令行输出，**必须 `disp`/`fprintf` 才能看到值** |
| `mcp__matlab__run_matlab_file` | `script_path`(绝对路径) | `.m`/`.p`；长代码一律先落盘再跑，省 token 且可复现 |
| `mcp__matlab__check_matlab_code` | `script_path` | 只读静态检查；跑 >50 行的脚本前先过一遍 |
| `mcp__matlab__run_matlab_test_file` | `script_path` | 只有写正式工具箱时才用 |

**硬性禁忌**

1. **绝不执行 `restoredefaultpath` / `rmpath` 掉 MCP 自己的路径** —— 会永久断开会话，只能重启 MCP。
2. **绝不并发调用** MATLAB 工具。单线程，同一时刻只跑一个。
3. 首次调用会等 MATLAB 冷启动（约 30–60 s），不是卡死，别重复发。
4. 不要在 `evaluate_matlab_code` 里写 `input`、`keyboard`、`uiwait` —— 会挂死整个会话。
5. `matlab-display-mode=nodesktop` 时 `figure` 不弹窗，必须 `'Visible','off'` + `exportgraphics`。

## 3. 数据交换规范

目录（用到再建，脚本入库，数据不入库）：

```
matlab/            可复现脚本（.m），命名 <任务>_<日期>.m
matlab/data/       交换用 CSV（临时）
matlab/figs/       输出图（.png，300 dpi）
```

CSV 约定：

- 首行表头，**纯 ASCII + 单位**：`field_deg,wave_idx,rms_radius_um`
- UTF-8、逗号分隔；数值 6 位有效数字足够
- 缺失值写空，不要写 `NaN` 字符串
- 一列一个物理量，不要在表头里塞多单位

JSON 只在必要时用；`jsondecode` 出来是嵌套 struct，转 CSV 反而更省事。

## 4. 典型任务的标准做法

### 4.1 面型校核（矢高 / 斜率 / 反曲 / BFS）

输入 `get_asphere_coefficients` 的 R、k、A4/A6/…，用解析式算矢高与导数（代码见 `references/matlab-code-recipes.md`）：

- 一阶导 `dz/dr` **在通光口径内变号 = 反曲，直接不合格**；
- 二阶导 `d²z/dr²` 变号 = 拐点，报告位置；
- 反曲点与通光半径的余量 <5% 按不合格处理；
- BFS 用**过顶点的单参数球**拟合，非球面度 = `max|z_asphere − z_sphere|`；
- 边缘厚度、边缘斜率角一并输出表格。

判据与处置方式以 `zemax-asphere-skill` 为准；MATLAB 只负责把数和图算出来。

### 4.2 公差蒙特卡洛统计

1. `run_tolerance_monte_carlo(trials=200)` → `get_tolerance_report`
2. 把每次 trial 的判据值抽成一列 CSV（字段名以实际返回为准，**先打印一次结构再写解析**）
3. MATLAB 算：良率 `mean(x<=spec)`、`mean/std`、P95/P99、`CPK = min(USL−μ, μ−LSL)/(3σ)`、bootstrap 95% CI、直方图

**只用均值判断良率会骗人**：必须同时给 N、良率、置信区间、最差 trial 值。

### 4.3 无热化拟合

`get_thermal_defocus` 给的是各温度组态下的 BFL 漂移，MATLAB 做：

- 2 阶多项式拟合 `drift(T)`，输出端点漂移、温度跨度、拟合残差；
- 补偿行程 = 全温漂移的峰峰值（留 20% 余量）；
- **残差判据**：残差 < 1/4 焦深；最终仍要回 Zemax 看全温 MTF。

### 4.4 像质曲线出图

MTF vs 频率、RI vs 视场、畸变 vs 视场、RMS vs 视场，统一：轴标签带单位、线宽 1.2、字号 9–10、淡网格、图例带视场角。用 `exportgraphics(...,'Resolution',300)`，不要 `saveas`。

### 4.5 鬼影一阶筛查

把系统按反射面**展开**成等效序列（反射 = 曲率反号 + 传播方向反向），MATLAB 算鬼影像的轴向位置与弥散，给出"会不会落到像面上"的初判。
**一阶估算只用于筛查，不能代替 GISET**；判据与整改见 `zemax-ghost-skill`。

### 4.6 外部优化（默认不做）

MATLAB 的 `fmincon`/`ga` 想调 Zemax，只能靠"写参数 → 跑 Zemax → 读评价函数"的磁盘往返。每次评估都是一轮 MCP 调用，慢且容易把会话搞死。**只在以下条件全部满足时做**：用户明确授权、变量 ≤3 个、粗搜索（网格/单形）、先用 DLS/Hammer 收敛过。否则一律回 Zemax 做局部优化。

## 5. 出图规范

```matlab
set(findall(gcf,'-property','FontName'),'FontName','Microsoft YaHei');  % 中文不出方块
set(gca,'FontSize',9,'LineWidth',0.8,'GridAlpha',0.15);
exportgraphics(gcf,'matlab/figs/xxx.png','Resolution',300);
close all;
```

- 图里不写"见上文"这类指代，标题自带条件（波长、视场、温度）；
- 中文注释在 R2020a+ 是 UTF-8，可直接写；**图内中文必须显式设字体**；
- 一次调用里把图全部出完、`close all` 收尾，不留悬空 figure。

## 6. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 工具报找不到 MATLAB | `--matlab-root` 路径错或 R2025b 未装 | 查 `.vscode/mcp.json`，重启 MCP 服务器 |
| 首次调用长时间无响应 | MATLAB 冷启动 | 等 60 s；仍无响应看 `matlab-mcp/logs/server-*.log` |
| **每次调用都 `timeout waiting for worker to start`，但客户端仍显示 connected** | ① 启动时的 eager 初始化失败后，server 握着死会话不再重试；② 日志里 21:22 之类的时间点通常伴随**两个 MATLAB 进程同时被拉起**、且 **`toolbox_cache-*.xml` 被写成 0 字节**（桌面模式启动即卡住） | ① `Stop-Process` 结束挂死的 MATLAB；② 把 `%LOCALAPPDATA%\MathWorks\MATLAB\R20xx\toolbox_cache-*.xml` 改名备份让它重建；③ 手动 `matlab -r matlab.engine.shareEngine` 起一个共享引擎，让 `--matlab-session-mode=auto` 走 attach；④ 仍不行再重启 MCP server。**"connected" 只代表 stdio 握手成功，不代表 MATLAB 挂上了**，判据是能否跑通一次 `detect_matlab_toolboxes` |
| 两个 `matlab-mcp-server` 进程同时存在，偶发结果错乱/超时 | 两个客户端（如 Claude Code 扩展 + VS Code MCP）各拉了一个 server，`UseSingleMATLABSession=true` 时它们共享同一个 MATLAB 会话，单线程被互相插队 | **同一个 MATLAB MCP 只由一个客户端持有**；两个都开着时禁止同时调用 |
| `Connection closed` / 会话失联 | 并发调用、`restoredefaultpath`、脚本崩溃 | 重启 VS Code 的 MCP 服务器（MATLAB → Restart） |
| **MCP 一直超时，但 `MATLAB.exe` 在跑（`-r matlab.engine.shareEngine`）** | server 的会话已死且不会自愈，客户端也无法中途重连 | **COM 直连**：`.venv\Scripts\python.exe` 里 `win32com.client.Dispatch("Matlab.Application")` → `h.Execute("cd('...'); script_name")`。仍是真 MATLAB 计算与出图，不是 Python 替代。**注意 `Execute` 只回错误文本、不回 `fprintf` 输出** —— 关键中间量写进日志文件再读 |
| 中文变方块/乱码 | 图内字体没设 | §5 的字体设置 |
| `evaluate` 没有输出 | 只执行没打印 | 显式 `disp`/`fprintf` |
| 路径含空格或中文报错 | 拼接字符串未加引号 | 用绝对路径 + `fullfile`，脚本内避免 `cd` 到中文目录 |
| 缺 `prctile`/`polyfit` 等 | 工具箱未装 | 先 `detect_matlab_toolboxes`；缺失时用排序法算分位数（见 recipes） |
| 输出图没生成 | `figs/` 目录不存在或 figure 不可见 | 先 `mkdir`，再 `Visible','off'` |
| 循环变量莫名变成小数 / 数组索引报"必须为正整数" | **嵌套函数与父函数共享同名变量**（MATLAB 语义，不报错） | 父作用域的循环变量、结果数组全部改名（如 `pp/qq/Yl/Ul`）；nested function 里绝不复用父层名字 |
| 矩阵幂报 `mpower` 维度错误 | 向量用了 `^` 而不是 `.^` | 局部函数里遇到向量参数一律 `.^`、`./` |

MATLAB MCP 连接异常的长期监控：`powershell -File .\scripts\watch_matlab_mcp.ps1`（见仓库 README）。

## 7. 交付检查清单

- [ ] 每个数都能说清来源：哪个 Zemax 工具 / 哪个 CSV / 哪次 trial
- [ ] 单位写在列名和轴标签上
- [ ] 统计结论带样本量 N 与置信区间
- [ ] 面型/热/统计的结论**已回 Zemax 复核**
- [ ] 图 300 dpi、中文正常、文件名在 `matlab/figs/`
- [ ] 脚本落在 `matlab/`，别人能一键重跑
- [ ] 没有把大数组贴进对话，也没有并发调用 MATLAB

## 8. 代码模板

矢高/斜率/反曲/BFS、蒙特卡洛统计、热离焦拟合、MTF 出图的可直接复制代码：见 `references/matlab-code-recipes.md`。
