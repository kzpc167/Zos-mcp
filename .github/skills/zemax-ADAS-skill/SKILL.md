---
name: zemax-ADAS-skill
description: 'ADAS / 相机镜头光学设计执行规程（双高斯 + 广角物镜主线）。用 zosmcp MCP 工具做 Zemax 镜头设计：两条起步路线（平面起步法 / 专利·教材起步法）、教材四步法分阶段优化、评价函数与护栏配置、孔径渐进、光阑净空、畸变与 CRA 控制、非球面、窗口等效平板、验收与异常排查。Use when: 设计 ADAS 或相机镜头、双高斯物镜、广角物镜、按教材/专利数据建模、分阶段优化、评价函数优化、EFFL 保焦距、替代玻璃替换、Hammer 全局优化、渐晕拦光、负畸变控制、CRA 远心化、优化后出现玻璃砖/负空气间隔/光阑与透镜重叠/多视场读数完全相同等异常排查。'
---

# ADAS 镜头设计执行规程

> 全部操作经 `mcp__zemax-opticstudio__*` 完成。**不新建 Python 脚本、不手写 .zmx**。
> 本文件只写「怎么做、不许怎么做、做完查什么」。原理与数据在 references，按 §1 路由表按需加载。

**本文件结构**

| § | 内容 | 何时用 |
|---|---|---|
| 1 | 文献路由表 | 开工第一步，决定读哪篇 reference |
| 2 | 绝对红线 R1–R25 | 动手前通读；**违反即回退** |
| 3 | 核心参数表（枚举/阈值/公式） | 填参数时照抄 |
| 4 | 工作流模板（路线 A / B / 渐进孔径 / 变量分阶段） | 直接照抄执行 |
| 5 | 验收清单（9 项） | 每轮优化后逐项打勾 |
| 6 | 异常决策树 | 出症状时按行索骥 |
| 7 | 存档与协作约定 | 保存、备份、多 agent 并发 |

## 1. 文献路由表（先读这条再往下）

| 你要做的事 | 读哪篇 |
|---|---|
| 选结构、定起步、判断收敛/发散、像差怎么平衡 | `references/design-thinking.md` |
| 配评价函数、选操作数、定 target/权重、边界型 vs 目标型 | `references/operands.md` |
| 按教材/专利做多步优化，决定这一步放什么变量 | `references/staged-optimization.md` |
| 设渐晕、VCX/VCY 取值、像质⇄照度权衡 | `references/vignetting.md` |
| 广角 / 大视场 / 毫米级镜头 / 非球面校正板 | `references/wide-angle.md` |
| 15 mm F/1.4 + 1/1.73" 8MP 车载长焦前摄整案（已验证流程/参数/处方） | `references/15mm-f14-1-1.73.md` |
| 手上没有面表，要挑一个专利起点 | `references/patent-library.md`（平时别读） |
| 工具报错、读数同值、参数没生效、枚举值、API 用法 | `references/zosmcp-troubleshooting.md` |
| 净空判据推导、Petzval 和、等效光程、艾里斑、工程取值阈值、**弯曲因子 \|B\| 的评价函数链** | `references/design-principles.md` |
| 「这个结果算好还是坏」、历史版本对比、事故复盘 | `references/cases-and-history.md` |
| 非球面 k 受控优化、A4/A6 交替固定、反曲判定与消除、非球面度、通光口径、边缘厚 vs MTF 冲突 | 独立 skill `zemax-asphere-skill` |
| 鬼影、强光源重影、杂散光、GISET/PST、镀膜反射率、非序列建模 | 独立 skill `zemax-ghost-skill` |
| 具体项目的面表/半口径/玻璃链快照 | `zemax-ADAS/*_设计报告.md`（不进 skill） |

## 2. 绝对红线（违反即本轮作废，必须回退重跑）

**R1 严格串行调用。** 严禁在同一条消息里并发多个 `zemax-*` 调用。ZOS-API COM 是 STA 单线程，并发会让 MCP 进程崩溃（前几个 ok、后续全部 `Connection closed`），恢复只能重启客户端且**内存改动全丢**。批量改 10 个变量就发 10 次。

**R2 开工先抄规格表，逐条标注「硬指标 / 软目标 / 参考」。** 没要求的指标可以当优化目标，**绝不能当判定成败的硬指标**。像质（MTF/RMS）默认软目标。把软目标当硬指标 → 否定合格设计、白烧算力。

**R3 深相对孔径必须渐进。** 目标 F/1.4 时孔径序列固定 `起始 F/2.2（或原结构值）→ 1.8 → 1.6 → 1.4`。每级必须真跑 DLS 收敛（连续两次 MF 相对变化 <1%），并复跑 `check_manufacturability` + `check_interference`。禁止一步跳到目标 F 数。

**R4 跑 Hammer / 任何全局算法前，四类护栏必须齐备**：玻璃中心厚 `MNCG/MXCG`、空气间隔 `MNCA/MXCA`、边缘厚 `MNEG`、边缘空气净空 `MNEA`，权重 5。宁可让向导生成，也不要两边都没有。

**R5 同一面禁止两条不同 target 的同类约束**；`TTHI(i,i)` 与 `MNCG(i,i)` 不得并存（互相夹逼，永不达标）。

**R6 上限按「工程合理」取值，不按「还能追迹」。** 优化器永远顶天花板：`MXCG` 设 20 必得 20.0000 的玻璃砖，设 10 才合理。

**R7 中心够 ≠ 边缘够。** 任何光阑 / 平面 / 薄空气层相邻处，开跑前先算 sag：**要求中心间隔 ≥ sag(边缘高) + 净空**。只给 `MNCA` 必被强凸面顶穿；必须配 `MNEA`。

**R8 `MNCA` 条数 = 元件数 + 1（光阑算一对空气面）。** 删/插片后按面号随口写必漏；数不够就是漏了。

**R9 抄专利面表先查 STO 行是否带玻璃材料。** STO 带材料 + 带厚度 = 光阑与镜片共面，属**结构缺陷**，`MNCA/MNEA` 加多大都无解（中心距恒为 0），必须插独立光阑面。

**R10 自定义操作数必须置顶。** `add_operand(insert_at=1..K)` 规格在前、护栏紧随，再 `set_default_merit_function(start_at=K+1)`。追加到 70 行之后等于藏起来。

**R11 符号类操作数不可乱用。** `DIMX` 返回**绝对值**（原生 −0.684% → DIMX 读 +0.684%），`target` 设负 → 罚项恒 ≥1、MF 暴涨、畸变反被压向 0。`REAY` 的视场号**禁止塞进 `hx`**（会被当 Hx，追一个 y 恒 0 的点 → 畸变全 0、MF=0）。`MNCT(i,i)` 单面退化返回 target，中心厚一律用 `MNCG(i,i)`。

**R12 `RAID` 是目标型不是边界型。** 场镜已把 CRA 压达标后**不要再加 RAID target**（会把达标值顶回 target、白牺牲像质）；但也不能彻底放开（CRA 会反弹）。保留一条温和约束，target 比要求留 ~2° 裕量。

**R13 多视场报完全相同的数 = 工具坏了。** 同值即 bug，先查工具参数布局，别解释成"设计对称"。报出的数若恰好等于另一处已知值，是复制 bug。

**R14 插面 / 删面 / 改光阑后：必须 `clear_operands` 重建 MFE，并复跑 `check_interference`。** 面号全错位，修补必然漏；MF 收敛得好 ≠ 结构合法。

**R15 验收必须看图，且必须看 3D（隐藏透镜边）+ 2D。** 3D 用 `layout_type="3D"`、`view="current"`、`angle_x/y/z=0`、`hide_lens_edges=true`，看真实面形/边缘/元件是否臃肿或畸变；2D 看光阑与透镜是否重叠、空气间隔是否被顶穿。历史两次最严重缺陷都是看图发现的，数值全绿也照样穿模。

**R16 数值可疑先怀疑工具，结构可疑先怀疑拓扑。** `FCUR/ASTI` 主导且 >5 waves → 是 Petzval 天花板，继续优化/换评价函数/放宽 TOTR 全部无效，只能换玻璃重配 Σ(φ/n) 或加平场片。

**R17 窗口（cover glass + IR-cut）一律用单片等效平板建模。** 两片拆开是过度建模：界面翻倍、中间薄空气层成强反射腔（`check_interference` 查不到、必出鬼影）、还多报假阳性。

**R18 默认 MF 采样必须够密。** 至少 4 环 × 8 臂（`rings=3, arms=1`）+ `overall_weight≥10`；3 环 × 6 臂会让 MF 下降而原生 MTF 崩坏，优化器在钻稀疏采样的空子。

**R19 验收只信原生分析。** MTF 一律读 `export_analysis_data("fft_mtf")` 的逐视场值；MTF 操作数只用于诊断，不能单独作为达标依据。

**R20 对角视场异常先验对称性。** 旋转对称系统同半径性能应相同；把第 5 视场临时改成 `(0,17.29)` / `(17.29,0)` 对比，T/S 应互换。不要据此改设计。

**R21 RELI 可能退化。** 本工具链里 RELI 可能对全部视场恒返回 1.0；相对照度用原生分析，主光线角用 `RAID` 控制。

**R22 像圈必须显式验算。** `2 × image_semi_diameter ≥ 9.25 mm`；畸变/视场微调是最后手段，先收紧 `DIMX`。

**R23 工作 F/# ≠ 像方 F/#。** 像方 1.40 可能对应实光线工作 F/# 1.46；若验收写“实际 F/1.4”，入瞳需收到约 1.35 并接受 MTF 代价。

**R24 非球面一次只放 A4/A6。** 先 `Fixed_5` 核对原生 MTF，再加下一面；A8/A10 很容易把 SPHA 拉到 −30λ。

**R25 `MNEA(i,i)` 可能返回 target。** 它不反映真实边缘净空；用 `MNCA` 下限约束 + `check_interference` 复核。

**R26 优化 k 时 A4/A6+ 必须显式固定。** "没改它" ≠ "不是变量"；先 `make_variable(param="A4"/"A6", variable=false)`。A4 只在 k 收敛且落在边界内之后才允许释放，且不得在 k 优化阶段同时放 A4 及以上。

**R27 k 边界用 `COVA` + `OPGT/OPLT` 夹住，且权重必须足够。** 小越界（<0.001）时权重 100 会被 MTF/OPDM 压穿，需加大到 10000；边界目标向内留余量（要求 [−2,1] 时用 [−1.95,0.95]）。优化后必须 `get_operands` 读回 k，不能只看返回值 ok。

**R28 每轮优化后必须做面型检查。** 输出边缘矢高、边缘斜率、斜率是否变号、曲率是否变号：**斜率变号 = 反曲，不合格**；`z''` 变号 = 拐点，必须显式报告；边缘斜率 >约 30° 视为偏陡。反曲还必须给出「反曲点 − 通光半径」的余量（<5% 算贴线）。**面斜率在 MFE 里读不到**（`SDRV`/`SSAG` 参数写不进），只能解析计算 + `CVGT` 卡顶点曲率。公式与判定见 `zemax-asphere-skill` §3。

**R29 `DIFF`/`SUMM` 复合操作数不参与 DLS 求导。** 它们会计入评价函数值（breakdown 里贡献很大），但优化器不会沿其梯度移动；不要用它们驱动优化，用原生 `CVGT/CVLT` 或手动扫描。

**R30 `get_image_quality` 对离轴视场固定 `Hx=0`。** field 4/5 读到的是子午点而不是对角点；对角视场一律用 `get_mtf(frequency=…)` 或 `get_fft_mtf_vs_field`。

**R31 默认 MF 重建后要逐行读回 MTF 行。** `set_default_merit_function(start_at=…)` 可能把前面的 `MTFT/MTFS` 行 `Hx` 重置为 1（视场 1），导致高视场实际无约束；重建后核对每条 MTF 的 `Hx`。

**R32 打开当前已激活路径的备份可能不重新加载，且可能把内存状态写回该文件。** 恢复快照前先把备份复制成**新文件名**，再 `open_file` 副本；不要直接打开原备份路径。

**R33 极端弯月用「曲率链」约束，别只盯着看。** Zemax 无弯曲因子操作数，`check_manufacturability` 的 `bend_factor_B` 只是读数。`B > −5` 化成 **`c2 > 1.5c1`**（线性）；`\|B\| < 5` 化成 **`5\|c2−c1\| − \|c1+c2\| > 0`**（配 `ABSO`，正负弯月与 R 变号全域有效）。**禁用 `DIVB`**（Param2 写不进，值恒 0）。卡在 −5.01 贴线时把 target 抬 3e−4 给裕量，一次即过；达标后 target 改回真实阈值。链见 `design-principles.md` §P6.6，坑见 `zosmcp-troubleshooting.md` §T17。

## 3. 核心参数表（照抄，不要凭记忆）

### 3.1 枚举与语义

| 参数 | 真值映射 |
|---|---|
| 向导 `rings` | `0=1环 1=2环 2=3环 3=4环 4=5环 5=6环`（Zemax 默认 3 环 = `rings=2`） |
| 向导 `arms` | `0=6 1=8 2=10 3=12`（6 环 12 臂 = `rings=5, arms=3`） |
| `start_at` | **覆盖**语义，非追加；换采样用同 `start_at` 再调一次即可，不必清空重建 |
| `VCX/VCY` | **被拦掉的比例**。`0=无渐晕`，`1=全拦`。禁止 `1−x` 换算 |
| `SolveType` | `Fixed=1, Variable=2, MaterialSubstitute=22` |
| `DIMX` | `Int1=视场号(0=全视场最大), Int2=波长号, Int3=0(相对)`，返回 \|畸变\| |
| `MTFT/MTFS` | `Int1=采样密度, Int2=波长(0=多色), Hx=视场号(1-based), Hy=频率lp/mm` |
| `GMTT/GMTS` | Field / Freq 在 **Hx / Hy** 列，不在 Int3/Int4 |
| 平面 | 传 `"Infinity"`（`1e15`/`Infinity`/`平面` 均可），**不要写 1e18** |

### 3.2 工程阈值（15 mm 级车载；大镜头另议）

| 项 | 取值 | 备注 |
|---|---|---|
| 光阑片厚 | 0.05~0.1 mm | 金属蚀刻片，按零厚度面建模 |
| 光阑↔镜片 边缘净空 | **0.25~0.4 mm** | 合格线，不是"偏紧" |
| 光阑座安装净空 ≥2 mm | 仅大镜头 | 15 mm 级紧凑镜头给不出，别当验收线 |
| 片间中心间隔 | **≥0.2~0.3 mm** | 隔圈壁厚 0.3~0.5，`MNCA` 默认 0.1 只是"不打架" |
| 加工四项 | CT≥1.0、ET≥0.5、SD/CT≤3.5、min\|R\|≥3 | 比 \|B\|>5 更可信；**毫米级镜头按比例缩**（见 `wide-angle.md` §5） |
| 收敛判据 | 连续两轮 MF 相对降幅 <1% | 孔径级用罚项变化 <1e-8 |
| 失效起点底线 | 能追迹 + 焦距对 + 拓扑对 | 像质差不是问题 |

### 3.3 起步三判据 & 光焦度公式

```
平面起步：最后折射面 R = -(n_d - 1) × f′   （一次到位，无需迭代）
口径换算：EPD = EFFL / F#；F/2 + f′=50 → EPD 25
单片贡献：φ = (n-1)(1/R1 - 1/R2)；P = φ/n（Petzval）；C = φ/ν（色差）
```

## 4. 工作流模板

### 4.1 路线 A：平面起步法（无现成面表）

```
1  get_system_info              核对范例玻璃/厚度/胶合面
2  edit_surface ×7              非胶合折射面 → "Infinity"
3  edit_surface                 最后折射面 R = -(nd-1)×f′
4  get_first_order_data         验证 EFFL
5  make_variable ×N             半径 + 离焦 + 空气间隔（严格串行，一次一个）
6  clear_operands(confirm=True)
7  add_operand(insert_at=1..K)  规格 + 护栏【置顶】
8  set_default_merit_function(start_at=K+1)
9  run_optimization(DLS) ×N     连续两轮 <1% 停
10 run_optimization(OD)         换算法确认收敛
11 make_variable(param="material") ×N → Hammer 分段跑（先补护栏，R4）
12-17 一阶量 → 操作数/材料读回 → 几何体检 → 导出 2D/3D → save_file(正式路径)
```

### 4.2 路线 B：专利 / 教材四步法

```
【建结构】
B1  get_project_context / get_system_info
B2  insert_surface(position=2) ×N       原面全部后移
B3  edit_surface(radius, thickness, material) 逐面填（平面传 "Infinity"）
B4  edit_surface(is_stop=True)          自动取消原光阑
B5  set_aperture / set_fields / set_wavelengths
B6  get_first_order_data + get_image_quality   核对 EFFL/TOTR/BFL

【步 1｜DLS：10 半径 + 4 正透镜厚 + 光阑前后空气，玻璃固定，3 视场】
B7-B9   make_variable(radius ×10 / thickness ×4正 / thickness ×2空气)
B10 clear_operands(confirm=True)
B11 add_operand(insert_at=1..4)   EFFL / MNEG / MNCT / DIMX
B12 add_operand(insert_at=5..)    护栏全集（R4）
B13 set_default_merit_function(start_at=K+1, rings=2, arms=0)
B14 get_merit_breakdown(top_n=10) 确认罚项前列不是恒定厚度偏置
B15 run_optimization(DLS) ×2

【步 2｜Hammer：换替代玻璃】
B16 make_variable(param="material", 6 面)
B17 get_system_info             必须读回 material_solve=22，不能只看返回 ok
B18 ⚠️ 复查四类护栏齐备（R4），否则必出退化解
B19 run_optimization(Hammer, duration_seconds=150) 分段，每段查 TOTR
B20 get_system_info 逐面查厚度（几十上百 mm / 负值）+ check_manufacturability

【修几何｜用 DLS，不用 Hammer】
B21 check_interference(min_clearance=0.1, stop_clearance=2.0)  看 clearance_at
B22 add_operand(MNEA(透镜面,光阑面) ≥ 净空, w=5) + MNCA 抬到 sag+净空
B23 run_optimization(DLS) ×2
B24 check_interference 复跑 → 出 _clearance_check.png 给用户核对

【步 3｜加密视场 + 渐晕，DLS，不加新自由度】
B25 set_fields(6 视场带 vcx/vcy)    核 readback；轴上视场保持 0/0
B26 clear_operands → 重建
B27 run_optimization(DLS) ×2
B28 多视场同值 → 立刻怀疑工具（R13）

【步 4｜工程约束 + 两阶段 Hammer】
B29 加 MXCG(1,末玻璃面)≤合理值，删掉重复的同类上限
B30 Hammer 阶段 1（3 环 6 臂）分段到单轮 <1%
B31 set_default_merit_function(start_at=同一行, rings=5, arms=3)  覆盖不重建
B32 Hammer 阶段 2 分段到单轮 <1%
B33 save_file(filename=正式路径)   立即保存，Hammer 结果只在进程内存

【验收】B34-B36 见 §5
```

**三条顺序铁律**：拓扑从不由优化器决定（改片数人工换结构）；玻璃一定放在形状之后（形状还差时换玻璃必得畸形补偿组合）；约束只能逐步加严，不能中途放松。

### 4.3 渐进孔径子流程

```
C1 set_aperture(ImageSpaceFNumber, 起始值)   比目标宽 1~2 档
C2 run_optimization(DLS) ×2~3               罚项变化 <1e-8 才算收敛
C3 get_spot_diagram_data + get_fft_mtf_vs_field   留本级基线
C4 save_file(阶段名) → save_file(工作名)     双保存，防下一级写脏存档
C5 set_aperture(收紧一档) → 回 C2
```

**每级自检**：孔径收紧 ~11% 时 RMS 应涨 ~1.5 倍。涨超 2.5 倍 = 上级没收敛或跳解，回退半档；涨不到 1.1 倍 = 约束在替它扛，像质没吃到孔径。
**汇报必须逐级列表**：孔径 / MF / 各视场 RMS / 最大 \|B\|，缺表算未执行。
**自由度榨干判据**（≥2 条成立就上非球面/加片，别再磨球面）：多个元件 \|B\|>5；加片改善 <10%；子午/弧矢 MTF 分离 >2 倍。
**非球面性价比**：末片后表面 > 首片 > 光阑附近；只上 A4/A6。

### 4.4 变量分阶段放开（顺序比数量重要）

```
阶段 0 恢复结构：半径 + 厚度全放，只跑到"能追迹 + EFFL 对"
阶段 1 定形状：固定全部厚度，只放半径        ← 形状（含 B 值）在此钉死
阶段 2 调分配：放玻璃中心厚（负透镜优先）
阶段 3 调间隔：放空气间隔（光阑前后优先）
阶段 4 收尾：全放开跑一轮，只接受 MF 降幅 >1% 的改动
```

每阶段判据：放开后 MF 降幅 <1% → 固定回去，它们只给公差添乱。**形状在阶段 1 定型，事后收回变量救不回来。**

## 5. 验收清单（每轮必跑，缺一不可）

| # | 检查 | 命令 | 抓什么 |
|---|---|---|---|
| **0** | **视场/波长覆盖** | `get_system_info` | 有无**对角视场**；波长是否含 g 线。缺任一项则所有指标都是乐观值 |
| 1 | 一阶量 | `get_first_order_data` | EFFL 达标、TOTR 无暴涨 |
| 2 | 逐面厚度/半口径 | `get_system_info` | 玻璃砖、**负空气间隔**、是否顶到上限 |
| 3 | 可加工性 | `check_manufacturability` | ET、SD/CT、\|B\|（平板假阳性按 R17 忽略） |
| 4 | **实体净空** | `check_interference` | 光阑/镜片穿透、元件互插、最紧在轴上还是边缘 |
| 5 | 像质 | `get_image_quality` + 点列图 | RMS/GEO；同值即工具坏 |
| 6 | 畸变 | `get_distortion` + `get_field_curvature_distortion_data` 交叉 | 逐视场单调性、是否 <阈值 |
| 7 | **看 3D 布局图（隐藏透镜边）** | `export_layout_image(3D, hide_lens_edges=true)` + 看图 | 真实面形/边缘/元件是否臃肿、弯月过深、面形鼓包、边缘相交、玻璃砖、光阑与透镜重叠、间隔顶穿（**3D 一张看全部，2D 已废弃**） |
| 8 | 罚项构成 | `get_merit_breakdown(top_n=10)` | 恒定厚度偏置（锁死厚度造成） |

**第 0 项为什么排第一**：矩形 sensor 的对角视场 ≠ 子午边缘视场，必须显式加 `(H_half, V_half)` 那个点；只看子午视场会得出"全绿"的错误结论。波长同理，只给 F/d/C 的"可见光 ✅"是三条谱线。

**出图规范**：`export_layout_image` **只导 3D 一张**（用户 2026-11-03 明确要求：取消二维布局图）——
- **3D**：`layout_type="3D"`、`view="current"`、`angle_x=0`、`angle_y=0`、`angle_z=0`、`hide_lens_edges=true` → `layouts/layout_3D.png`。**隐藏透镜边后才能看清真实面形与边缘，是自查“透镜是否合理”的必看项**（弯月过深、面形鼓包、边缘相交、玻璃砖）。
- ~~2D：`layout_type="2D"` → `layouts/layout_2D.png`~~ —— **不再导出、不再打开、`present_files` 里也不放**。光阑/透镜重叠与空气间隔一律用 `check_interference` 的数值判定，不靠 2D 图目视。

点列图 `export_spot_diagram_image(show_airy=True)` → `layouts/spot_diagram.png`。固定文件名、覆盖式，不带日期后缀。导出失败必须明确报告，不得拿另一种视图冒充。

## 6. 异常决策树

| 症状 | 首查动作 | 然后读 |
|---|---|---|
| MF 降得很好但结构废了（厚度几十上百 mm / 负空气间隔） | `get_system_info` 看逐面厚度，`get_merit_breakdown` 找恒定偏置 | `cases-and-history.md` §C2.3（根因 = 护栏缺失，见 R4） |
| 光阑插进透镜 / 两片边缘互穿 | `check_interference` 看 `clearance_at` | `design-principles.md` §P1 |
| `check_interference` 报某对净空恒为 0 | 查该面是否 `is_stop` 且带材料 | `zosmcp-troubleshooting.md` §T11 |
| 优化收敛漂亮但 `check_interference` 报相交 | 数 `MNCA` 条数是否 = 元件数+1 | `zosmcp-troubleshooting.md` §T12 |
| 多个视场读数完全一样 | 查工具参数布局（`settings_report.applied` 是否为空） | `zosmcp-troubleshooting.md` §T4 |
| 畸变压不下去 / 压出负畸变反而 MF 暴涨 | 读原生 FieldCurvatureAndDistortion，DIMX 只当幅值护栏 | `design-principles.md` §P8 |
| MF 很低但边缘 MTF 差 | `get_aberrations` 看 FCUR/ASTI | `design-principles.md` §P2 |
| 想加非球面救场曲 | 停。非球面不进 Petzval 和 | `design-principles.md` §P2 |
| 元件 \|B\| 极大 / SD/CT 看着像砖 | 拆单片算 f 与相对孔径 | `design-principles.md` §P6 |
| 要把 \|B\| 压回 5 以内（评价函数怎么做） | 用曲率链，禁用 `DIVB` | `design-principles.md` §P6.6 + `zosmcp-troubleshooting.md` §T17 |
| 删/插面后新增的操作数在 MFE 里翻不到 | 是否用默认 append 追加到末尾（违 R10） | 重建成 `insert_at=1`，见 `zosmcp-troubleshooting.md` §T17 末 |
| CRA 超标 | 场镜靠像面 + 温和 RAID（R12） | `cases-and-history.md` §C4.8 + `design-principles.md` §P11 |
| 相对照度偏低 | `get_relative_illumination_data`（原生），**不要**用 `check_field_illumination` | `design-principles.md` §P9 |
| 点列图艾里圈包住全部光点，但界面圈很小 | 圈是脚本算的，非 Zemax 原生 | `zosmcp-troubleshooting.md` §T14 |
| 换采样后 MF 跳一个数量级 | 说明前面的解只在稀疏采样上好看，重跑 | `cases-and-history.md` §C2.2 + `zosmcp-troubleshooting.md` §T10 |
| 改了参数但结果没变 | 看 `settings_report`/`readback`，静默丢弃 | `zosmcp-troubleshooting.md` §T5 |
| Hammer 结果丢了 | 查 `_0000_HAMMER.zos` | `zosmcp-troubleshooting.md` §T2.5 |

## 7. 存档与协作约定

- `save_file()` **空参**会覆盖当前文档路径（可能写脏备份）→ 只用 `save_file(filename=正式路径)`。
- `run_optimization` 自动落盘到**当前路径**，所以阶段存档靠「另存阶段名 → 再另存工作名」两次切回。
- `clear_operands` / `run_optimization` / `edit_operand` / `remove_surface` 都会在 `<文件目录>/backups/` 生成备份；用户不要时完工后删除。
- **部署方式：把 skill 目录放进所用 agent 认的 skills 路径即可**（`.github/skills/`、`.workbuddy/skills/`、`.claude/skills/`、`.dsh/skills/` 中任意一个），复制或克隆都行，无额外步骤。
- **本机把上述路径做成了 Windows 目录 Junction 指向 `.github/skills/`**，这只是「一份文件给多个 agent 共用、避免多份副本各自漂移」的**本机便利做法，不是部署前提**。换机器/新克隆**不需要复刻 junction**，直接放文件即可；若确实想让多个 agent 共用一份，才用 `mklink /J <agent路径> <本仓库.github/skills>` 建，并用 `dir /AL` 确认。
- git 只跟踪 `.github/skills/`（`.workbuddy/`、`.dsh/`、`.claude/` 均在 `.gitignore`）。多 agent 并发写入**无文件锁**，以最后写入为准 → 改完立刻 commit，把窗口压到最短。
- **改完本 skill 必须跑结构自检**：`python scripts/lint_skill.py`（校验跨文件 § 引用、编号连续性、SKILL.md ≤300 行、路由表文件存在）。返回 0 才算改完。
