---
name: zemax-ADAS-skill
description: 'ADAS / 相机镜头光学设计执行规程（双高斯 + 广角物镜主线）。用 zosmcp MCP 工具做 Zemax 镜头设计：两条起步路线（平面起步法 / 专利·教材起步法）、教材四步法分阶段优化、评价函数与护栏配置、孔径渐进、光阑净空、畸变与 CRA 控制、非球面、窗口等效平板、验收与异常排查。Use when: 设计 ADAS 或相机镜头、双高斯物镜、广角物镜、按教材/专利数据建模、分阶段优化、评价函数优化、EFFL 保焦距、替代玻璃替换、Hammer 全局优化、渐晕拦光、负畸变控制、CRA 远心化、极端弯月替换（机械定心系数 Z）、单组态化、交付四图（3D 布局/净空/点列图/MTF）、写工程总结（光学/无热化/公差/鬼影/DFM 五件套）、优化后出现玻璃砖/负空气间隔/光阑与透镜重叠/多视场读数完全相同等异常排查。优化变量必须按 references/staged-optimization.md 分阶段放开，禁止一次全放；references 按动作强制加载。'
---

# ADAS 镜头设计执行规程

> 全部操作经 `mcp__zemax-opticstudio__*` 完成。**不新建 Python 脚本、不手写 .zmx**。
> 本文件只写「触发规则、红线、参数速查、验收与路由」；具体步骤序列在 `references/workflows.md`，原理与数据在其余 references，按 §1 触发规则**强制加载**（不是按需）。

## 1. 文献加载规则（按动作触发，不是"按需查阅"）

**references 不是背景资料，是执行前的必读前置条件。** 三条规则：

1. 下表每行是一个**触发动作**。做该动作**之前**先读对应文件；只读列出的节也算读。同时触发多行 → 全部读完再动，顺序：设计思路 → 操作数 → 分阶段。
2. 读完在回复里写一行 `已加载：<文件名> §<节>`，再执行动作。**没写这行 = 没读，动作无效。**
3. **禁止开工前一次性读完整个 references**（费上下文且记不住）；只按当前动作加载。同一设计任务内已读即算，换阶段不必重读。

| 触发动作（准备调用…） | 必读（先读再动） | 不读就禁止做 |
|---|---|---|
| 开工 / 规格澄清 / 选结构 / 定起步 / 判收敛发散 / 像差平衡 / 决定推倒重来 | `references/design-thinking.md` | 改拓扑、换结构、下"没救了"结论 |
| **任何 `make_variable`（含 `param="material"`）或 `run_optimization`** | **`references/staged-optimization.md` 全文** + `references/operands.md` §三/§四 | **一次放开全部变量；没贴阶段表就开跑** |
| 按路线执行优化、确认下一步顺序、抄步骤序列 | `references/workflows.md`（W1~W3） | 凭记忆拼步骤、漏掉验收 |
| 建/改 MF、加操作数、定 target/权重 | `references/operands.md`（§二选型 / §四权重 / §五实操） | `add_operand` / `set_default_merit_function` / 改权重 |
| 广角 / 大视场 / 毫米级 / 非球面校正板 | `references/wide-angle.md` | 把双高斯套路套到广角 |
| 15 mm F/1.4 车载长焦同类项目 | `references/15mm-f14-1-1.73.md` | 不读就自行重跑已验证流程 |
| 没有面表，要挑专利起点 | `references/patent-library.md` | 凭记忆写专利面表 |
| 工具报错 / 读数同值 / 参数没生效 / 枚举 / API | `references/zosmcp-troubleshooting.md`（对应 T 节） | 原样重试同一失败调用 |
| 净空判据 / Petzval / 等效光程 / 艾里斑 / 工程阈值 / 渐晕 P10 / **\|B\| 评价函数链** | `references/design-principles.md`（对应 P 节） | 凭感觉定净空、上限、权重、渐晕 |
| **弯月替换 / 定心系数 Z / 极端弯月判定 / 单组态化（删温度组态）** | `references/meniscus-centering.md` | 拿 B 当 Z 用、指望 MFE 链把 Z 拉到位、删组态不验证 |
| 判"结果好坏" / 历史对比 / 事故复盘 / 异常现场排障 | `references/cases-and-history.md`（先查 C5） | 凭直觉改设计、连续试错、不查 C5 |
| 可制造性/DFM 评审、出图、询价、降本、供应商能力 | 独立 skill `spherical-lens-dfm-review` | 把 `check_manufacturability` 的 pass 当"可投产" |
| 非球面 k / A4·A6 / 反曲 / 面型验收 | 独立 skill `zemax-asphere-skill` | — |
| 鬼影 / 杂散光 / GISET·PST / 镀膜 | 独立 skill `zemax-ghost-skill` | — |
| 报告级出图 / 统计（良率·CPK·CI）/ 拟合（热离焦）/ 面型导数与反曲 | 独立 skill `zemax-matlab-skill`（**必须实际调用 MATLAB**） | 用 Python / 手算冒充 MATLAB 交付结果 |
| 项目面表 / 半口径 / 玻璃链快照 | `zemax-ADAS/*_设计报告.md`（不进 skill） | — |

**优化前置门 M1–M3（违反即本轮作废）**

- **M1 先表后跑**：`make_variable` / `run_optimization` 之前，回复里必须先贴「阶段表」——`阶段 | 放开变量 | 固定变量 | 算法 | 停止判据`，依据 `staged-optimization.md` 的「四步法骨架」+ `workflows.md` W4。**没有阶段表就调用 = 违规，立即回退。**
- **M2 按阶段表放，不按"全部"放**：新增变量必须与阶段表逐条对应；禁止把「全部半径 + 全部厚度 + 全部间隔 + 玻璃」一次性设为变量。第 1 步只放 10 半径 + 正透镜厚 + 光阑前后空气，负透镜厚与其余空气间隔保持固定（理由见 `staged-optimization.md` 第 2.2 节）；批内顺序按第 3 节状态机 A1→A3、B1→B4 逐批加入。"先全放再收"是禁止路线。
- **M3 每阶段物理验收**：`get_system_info` + `get_merit_breakdown` + `check_interference`；MF 降幅 <1% 的变量固定回去，再进下一阶段。

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

**R15 验收必须看 3D 布局图（隐藏透镜边）。** 用 `layout_type="3D"`、`view="current"`、`angle_x/y/z=0`、`hide_lens_edges=true`，看真实面形/边缘/元件是否臃肿或畸变。光阑/透镜重叠与间隔顶穿用 `check_interference` 数值判定，不靠 2D 目视。历史两次最严重缺陷都是看图发现的，数值全绿也照样穿模。

**R16 数值可疑先怀疑工具，结构可疑先怀疑拓扑。** `FCUR/ASTI` 主导且 >5 waves → 是 Petzval 天花板，继续优化/换评价函数/放宽 TOTR 全部无效，只能换玻璃重配 Σ(φ/n) 或加平场片。

**R17 窗口（cover glass + IR-cut）一律用单片等效平板建模。** 两片拆开是过度建模：界面翻倍、中间薄空气层成强反射腔（`check_interference` 查不到、必出鬼影）、还多报假阳性。

**R18 默认 MF 采样必须够密。** 至少 4 环 × 8 臂（`rings=3, arms=1`）+ `overall_weight≥10`；3 环 × 6 臂会让 MF 下降而原生 MTF 崩坏，优化器在钻稀疏采样的空子。

**R19 验收只信原生分析。** MTF 一律读 `export_analysis_data("fft_mtf")` 的逐视场值；MTF 操作数只用于诊断，不能单独作为达标依据。

**R20 对角视场异常先验对称性。** 旋转对称系统同半径性能应相同；把第 5 视场临时改成 `(0,17.29)` / `(17.29,0)` 对比，T/S 应互换。不要据此改设计。

**R21 RELI 可能退化。** 本工具链里 RELI 可能对全部视场恒返回 1.0；相对照度用原生分析，主光线角用 `RAID` 控制。

**R22 像圈必须显式验算。** `2 × image_semi_diameter ≥ 9.25 mm`；畸变/视场微调是最后手段，先收紧 `DIMX`。

**R23 工作 F/# ≠ 像方 F/#。** 像方 1.40 可能对应实光线工作 F/# 1.46；若验收写“实际 F/1.4”，入瞳需收到约 1.35 并接受 MTF 代价。

**R24 非球面一次只放 A4/A6。** 先 `Fixed_5` 核对原生 MTF，再加下一面；A8/A10 很容易把 SPHA 拉到 −30λ。

**R25 `MNEA` 必须写相邻面一对 `MNEA(i,i+1)`；写成 `MNEA(i,i)` 是空操作。** Surf1=Surf2 时 Zemax 恒返回 target，读回值永远"达标"，边缘净空实际从未被约束。实测：`MNEA(8,8)` 读回 0.35（=target，真值 0.126），改 `MNEA(8,9)` 后读回 0.12618，与 `check_interference` 逐位一致。**注意 `MNCA(i,i)` 反而是有效的**（指"面 i 之后的间隔"，`MNCA(14,14)` 读回真实 BFL 可证），只有 MNEA 有 i==i 退化。改完必须拉 `check_interference` 复核。

**R26 优化 k 时 A4/A6+ 必须显式固定。** "没改它" ≠ "不是变量"；先 `make_variable(param="A4"/"A6", variable=false)`。A4 只在 k 收敛且落在边界内之后才允许释放，且不得在 k 优化阶段同时放 A4 及以上。

**R27 k 边界用 `COVA` + `OPGT/OPLT` 夹住，且权重必须足够。** 小越界（<0.001）时权重 100 会被 MTF/OPDM 压穿，需加大到 10000；边界目标向内留余量（要求 [−2,1] 时用 [−1.95,0.95]）。优化后必须 `get_operands` 读回 k，不能只看返回值 ok。

**R28 每轮优化后必须做面型检查。** 输出边缘矢高、边缘斜率、斜率是否变号、曲率是否变号：**斜率变号 = 反曲，不合格**；`z''` 变号 = 拐点，必须显式报告；边缘斜率 >约 30° 视为偏陡。反曲还必须给出「反曲点 − 通光半径」的余量（<5% 算贴线）。**面斜率在 MFE 里读不到**（`SDRV`/`SSAG` 参数写不进），只能解析计算 + `CVGT` 卡顶点曲率。公式与判定见 `zemax-asphere-skill` §3。

**R29 `DIFF`/`SUMM` 复合操作数不参与 DLS 求导。** 它们会计入评价函数值（breakdown 里贡献很大），但优化器不会沿其梯度移动；不要用它们驱动优化，用原生 `CVGT/CVLT` 或手动扫描。

**R30 `get_image_quality` 对离轴视场固定 `Hx=0`。** field 4/5 读到的是子午点而不是对角点；对角视场一律用 `get_mtf(frequency=…)` 或 `get_fft_mtf_vs_field`。

**R31 默认 MF 重建后要逐行读回 MTF 行。** `set_default_merit_function(start_at=…)` 可能把前面的 `MTFT/MTFS` 行 `Hx` 重置为 1（视场 1），导致高视场实际无约束；重建后核对每条 MTF 的 `Hx`。

**R32 打开当前已激活路径的备份可能不重新加载，且可能把内存状态写回该文件。** 恢复快照前先把备份复制成**新文件名**，再 `open_file` 副本；不要直接打开原备份路径。

**R33 极端弯月用「曲率链」约束，别只盯着看。** Zemax 无弯曲因子操作数，`check_manufacturability` 的 `bend_factor_B` 只是读数。`B > −5` 化成 **`c2 > 1.5c1`**（线性）；`\|B\| < 5` 化成 **`5\|c2−c1\| − \|c1+c2\| > 0`**（配 `ABSO`，正负弯月与 R 变号全域有效）。**禁用 `DIVB`**（Param2 写不进，值恒 0）。卡在 −5.01 贴线时把 target 抬 3e−4 给裕量，一次即过；达标后 target 改回真实阈值。链见 `design-principles.md` §P6.6，坑见 `zosmcp-troubleshooting.md` §T17。
**但 \|B\| 判据只对弯月片（两半径同号）生效**，双凸/双凹不判；且该曲率链若写成 `CONS/ABSO/DIFF` 复合形式，末端 `OPGT`（权重 10000）**罚得动、推不动**——能判出超限并主导 MF，但复合链无 DLS 梯度，优化器挪不动它（R29）——可靠做法是 `edit_surface` 手改半径 + `set_solve(fixed)`，再用 `check_manufacturability` 的逐片 `bend_factor_B` 复核。同理 **Z（定心系数）在 MFE 里也没有梯度**：`Z = D/(4(n−1)\|f\|)` 与弯曲无关，只能锁半径。做法见 `staged-optimization.md` 的「带硬几何指标（定心系数 Z）的分阶段放开」一节。

**R34 优化必须先过 §1 的 M1–M3 前置门。** 未加载 `staged-optimization.md`、未在回复里贴阶段表就 `make_variable` / `run_optimization` = 违规；**严禁一次放开全部半径 + 厚度 + 玻璃**（"先全放再收"是禁止路线，必出退化解）。

**R35 极端弯月必须用定心系数 Z 判，不能用 \|B\| 代替。** `B` 只反映形状，`Z = ¼\|D₁/R₁ ± D₂/R₂\|` 才反映可定心性（由口径与光焦度决定，形状改不动）。Z<0.05 不可交付；0.05~0.15 常规；>0.15 易加工但本类拓扑往往做不到——此时要如实说明"需改拓扑"，不要反复重跑优化。**Z 不能靠 MFE 复合链追**（DLS 无梯度），必须把半径固定到目标 Z 对应的值。详见 `references/meniscus-centering.md`。

**R36 权重按"评价函数总量级"配，不按直觉配。** 默认 `OPDM` 4 环 × 8 臂 = 204 行、每行权重 10，合计约 2000，是评价函数的主体；**任何权重 <20 的约束在其中基本等于不存在**。实测：`MTFT` 15° 视场权重只有 2 时，优化器直接把它从 0.57 换到 0.23 去满足 EFFL/DIMX；提到 20 才守得住。硬指标（TOTR / EFFL / 边缘净空）权重应上到 **100~2000** 量级。反过来，TOTR 权重设到 2000 后优化只剩半径可动，交付前按需要回调。

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

### 3.2 工程阈值（只记最常用的，完整分级见 `design-principles.md` §P14）

15 mm 级车载：光阑↔镜片边缘净空 **0.25~0.4 mm**；片间中心间隔 **≥0.2~0.3 mm**；加工四项 CT≥1.0 / ET≥0.5 / SD/CT≤3.5 / min\|R\|≥3（毫米级按比例缩）。
收敛：连续两轮 MF 相对降幅 <1%；孔径级用罚项变化 <1e-8。起步公式：`R = -(n_d-1)f′`、`EPD = EFFL/F#`，φ/P/C 见 §P7。

## 4. 工作流（步骤序列在 `references/workflows.md`）

| 场景 | 路线 | 模板 |
|---|---|---|
| 没有面表 / 要极简骨架 | A 平面起步 | `workflows.md` W1 |
| 有专利 / 教材结构 | B 四步法 | `workflows.md` W2 |
| 目标相对孔径深 | 渐进孔径 | `workflows.md` W3 |
| 放变量 | 批次状态机 | `staged-optimization.md` 第 3 节 |

**三条铁律**：拓扑从不由优化器决定（改片数人工换结构）；玻璃一定放在形状之后；约束只能逐步加严，不能中途放松。
**执行前置**：任何 `make_variable` / `run_optimization` 先过 §1 M1–M3，贴阶段表。

## 5. 验收清单（每轮必跑，缺一不可）

| # | 检查 | 命令 | 抓什么 |
|---|---|---|---|
| **0** | **视场/波长覆盖** | `get_system_info` | 有无**对角视场**；波长是否含 g 线。缺任一项则所有指标都是乐观值 |
| 1 | 一阶量 | `get_first_order_data` | EFFL 达标、TOTR 无暴涨 |
| 2 | 逐面厚度/半口径 | `get_system_info` | 玻璃砖、**负空气间隔**、是否顶到上限 |
| 3 | 可加工性 | `check_manufacturability` | ET、SD/CT、\|B\|（平板假阳性按 R17 忽略） |
| 4 | **实体净空** | `check_interference` | 光阑/镜片穿透、元件互插、最紧在轴上还是边缘。**非球面的 sag 必须含 k 与 A4/A6**：只用 `R−√(R²−h²)` 的球面近似会高估矢高（本项目 S13 差 0.93 mm，把 1.07 mm 的净空误报成 0.13，图上还会画成相插）。2026-11-18 已修工具，在此之前的历史数字要重跑 |
| 5 | 像质 | `get_image_quality` + 点列图 | RMS/GEO；同值即工具坏 |
| 6 | 畸变 | `get_distortion` + `get_field_curvature_distortion_data` 交叉 | 逐视场单调性、是否 <阈值 |
| 7 | **看 3D 布局图（隐藏透镜边）** | `export_layout_image(3D, hide_lens_edges=true)` + 看图 | 真实面形/边缘/元件是否臃肿、弯月过深、面形鼓包、边缘相交、玻璃砖、光阑与透镜重叠、间隔顶穿（**3D 一张看全部，2D 已废弃**） |
| 8 | 罚项构成 | `get_merit_breakdown(top_n=10)` | 恒定厚度偏置（锁死厚度造成） |
| **9** | **交付四图** | 见下方「交付四图」 | 缺一张即未完成交付；图必须来自最终定稿状态 |

**第 0 项为什么排第一**：矩形 sensor 的对角视场 ≠ 子午边缘视场，必须显式加 `(H_half, V_half)` 那个点；只看子午视场会得出"全绿"的错误结论。波长同理，只给 F/d/C 的"可见光 ✅"是三条谱线。

**交付四图（每次设计完成必出，缺一即未完成）**——用户 2026-11-18 明确要求：
每轮验收收尾必须导出并在回复里呈现这四张图，全部落在 `zemax-ADAS/layouts/`，固定文件名、覆盖式、不带日期后缀。

| # | 图 | 命令 | 文件名 |
|---|---|---|---|
| 1 | **3D 布局** | `export_layout_image(layout_type="3D", view="current", angle_x/y/z=0, hide_lens_edges=true)` | `layout_3D.png` |
| 2 | **净空剖面** | `check_interference(save_image=true, image_path=…/layouts/_clearance_check.png)` | `_clearance_check.png` |
| 3 | **点列图** | `export_spot_diagram_image(show_airy=true, wave=0)` | `spot_diagram.png` |
| 4 | **MTF 曲线** | `get_mtf_curve(max_frequency=240, num_points=10)` 取数 → MATLAB 出图（见下） | `MTF.png` |

**四图规则**：
- **一种设计只留一个**：四个文件名固定（`layout_3D.png` / `_clearance_check.png` / `spot_diagram.png` / `MTF.png`），每次覆盖。**禁止加日期/版本/结构后缀**（如 `layout_3D_定心版.png`），否则目录里会堆出一堆看着像"没更新"的旧图，也分不清哪张对应定稿。换设计就换目录（或换项目子目录），不换文件名。
- 四张图必须来自**最终定稿的同一状态**。最后一轮 DLS 之后、`save_file` 之后重出，不能拿中间过程的图凑数。
- 图导出后**必须真的打开看**（`Read` 图片），用眼睛确认面形/穿模/曲线形状；不能只凭工具返回 `ok:true` 就宣布交付。
- 3D 只导一张，**2D 布局已废弃**：不导出、不打开、不放回复里。光阑/透镜重叠与空气间隔一律用 `check_interference` 数值判定。
- 隐藏透镜边（`hide_lens_edges=true`）才能看清真实面形与边缘，是自查"透镜是否合理"的必看项（弯月过深、面形鼓包、边缘相交、玻璃砖）。
- 导出失败必须明确报告，**不得拿另一种视图冒充**（点列图不能顶替 MTF，2D 不能顶替 3D）。
- 报告"图已更新"前先核 `md5sum` / `date -r`：同名覆盖后哈希或时间戳必须变。**同名文件哈希相同 = 内容确实没变**，此时别跟用户争"我更新了"——先查是不是另一个目录（`tmp/layouts/` 之类的默认落盘处）里还留着一份旧副本。

**MTF 图为什么不能直接用 `export_analysis_data("fft_mtf")` 的图**：ZOS-API 的分析类没有可靠的位图导出，
MCP 的 `rendered_fallback` 会把 y 轴压成 0.33~1.05、丢掉视场标注，**不能作为凭证图**（2026-11-18 实测）。
正确路径：

```
① get_mtf_curve(max_frequency=240, num_points=10, wave=0)  → 逐视场 T/S + 衍射极限数据
② 落 CSV：matlab/data/mtf_curve_<项目>.csv（首列 freq_lpmm，其余 f1T,f1S,…,dl；f=0 时全为 1）
③ MATLAB 出图：matlab/mtf_plot_<项目>.m，实线=T、虚线=S、灰点划=衍射极限、竖虚线标 120 lp/mm
④ exportgraphics(fig, '…/layouts/MTF.png', 'Resolution', 300)
```

MATLAB MCP（`mcp__matlab__*`）worker 起不来时（`timeout waiting for worker to start`），
用本机 `matlab -batch "run('…/mtf_plot_<项目>.m')"` 跑同一脚本 —— 这仍是真 MATLAB 渲染；
**禁止**改用 Python/matplotlib 冒充（见 `zemax-matlab-skill` 的「什么时候必须切到 MATLAB」强制触发条款）。交叉校验：脚本里用 `interp1`
算出的 MTF@120 应与 `get_mtf(frequency=120)` 的原生读数一致（本例 0.582 vs 0.581）。

点列图 `export_spot_diagram_image` 的 RMS 用的是**全波混合 + 不同采样**，与 `get_image_quality`
的逐视场 RMS（主波长口径）不完全等值，报告里以 `get_image_quality` 为准、点列图看形状。

**分析窗口（场曲/畸变、FFT MTF vs 视场、相对照度）的位图拿不到**：`export_analysis_data` 的图片导出
对本类分析只写**文本**（实测 png/bmp/jpg/wmf 四个后缀全是 1511 B 文本、`valid_image=false`），
结构化 `DataSeries` 也常不规范（场曲 `y_data` 大量空行、条目是 `"(0.98, 1.48)"` 字符串）。
处理：**数字**从 `export_text` 的 UTF-16 文本解析（仍是 Zemax 原生值）；**原生版式**由 GUI 分析窗口
「保存为 BMP」→ MATLAB `imread`→`imwrite` 转 PNG 入库（不改像素）。报告里两套并存：
**数字以文本导出为准，版式以原生窗口为证，重绘图只作阅读辅助**。

## 6. 异常决策树

出症状先读 `references/cases-and-history.md` C5.1（症状 → 首查动作 → 对应 P/T/C 节），不要凭直觉改设计。
两条总则：**数值可疑先怀疑工具，结构可疑先怀疑拓扑**；同一症状修两次不好，回 §1 加载对应 reference，停止试错。

## 7. 存档与协作

- 保存/备份行为（空参覆盖、自动落盘、`backups/`）→ `zosmcp-troubleshooting.md` §T16；只用 `save_file(filename=正式路径)`。
- 部署路径、Junction、git 跟踪范围、多 agent 并发约定 → 仓库 `README.md`「技能部署」一节。
- 改完本 skill 必须跑 `python scripts/lint_skill.py`（跨文件 § 引用、编号连续性、SKILL.md ≤300 行、references 行数预算、路由表文件存在），返回 0 才算改完。

**references 维护规则（防臃肿 / 防过拟合）**

三种角色不许混用：

| 文件类型 | 写什么 | 增长方式 |
|---|---|---|
| 本文件 `SKILL.md` | 规程、红线、阈值、路由 | 只在规则变化时改，**不追加案例** |
| `references/<规格>-*.md`（如 `15mm-f14-1-1.73.md`） | 该类**当前最优做法快照**：指标基线、流程、参数速查、本类坑 | **换代时整段重写**，旧代压成附录一条，不按轮次追加 |
| `cases-and-history.md` | 叙事与症状索引：出过什么事、怎么发现的 | 只追加"教训"，**不追加数据表**（数据放项目报告） |

**准入三问**——任何经验写进 references 之前逐条过，三问全过才写：

1. 换个规格（焦距 / 片数 / F 数 / 视场）还成立吗？
2. 这句话描述的是**机制**，还是**这一个设计里的数**？
3. 下个项目得出相反结论时，这条会不会误导？

数值答案写进项目报告；只有"机制 + 适用边界"配一个实测证据，才进 skill。**行数预算由 lint 强制**（类基线 ≤120 行、其余 ≤500 行，超 90 % 告警）：接近上限时压缩或迁移，不追加。
