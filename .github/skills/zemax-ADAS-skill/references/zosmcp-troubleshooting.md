# zosmcp 工具踩坑篇（Tool-level pitfalls）

> 适用范围：`mcp__zemax-opticstudio__*` 全部工具 + ZOS-API 底层行为。
> **判据优先级**：工具行为不确定时，先读本篇再看设计结论。
> 通用原则：**改 MCP 代码或改系统状态后必须读回验证，不能只看返回的 `ok`。**

---

## T0. 调用协议：严格串行（崩溃级）

| 项 | 内容 |
|---|---|
| 症状 | 一条消息里并发多个 zemax 调用 → 前几个返回 ok，后续全部 `Connection closed`，随后 `Not connected`，`tasklist` 里 python 进程消失，而 OpticStudio 仍存活 |
| 根因 | ZOS-API COM 是 **STA 单线程**，MCP 服务器在同一线程串行处理；并发直接崩进程 |
| 代价 | 只能重启客户端，**内存里未保存的改动全丢** |
| 处置 | 逐个调用 → 等结果 → 再发下一个。批量改 10 个变量就老实发 10 次 |
| 例外 | 无 |

---

## T1. `make_variable(param="material")` —— 设了不一定生效

| 项 | 内容 |
|---|---|
| 用法 | `make_variable(surface_number=N, param="material", variable=true, catalog="SCHOTT")` |
| 实现要点 | `CreateSolveType(22)` 只**创建** solve 对象，**必须再调 `SetSolveData(solve)` 写回单元格**才生效。漏了这一步，读回 `material_solve` 仍是 1(Fixed) |
| 验证 | `get_system_info` 读回每面 `material_solve`：**22=替代玻璃**，1=固定，2=变量 |
| 判据 | 返回 `ok` 但读回 ≠22 → 视为未生效，重做 |
| 关联 | 替代玻璃的**离散替换只由 Hammer 触发**，DLS/OD 不会换玻璃 |

**常见误判**：替代玻璃没被替换，不是"玻璃已最优"，而是**跑的时间不够 / solve 没生效**。先查 `material_solve`，再查 duration。

---

## T2. Hammer 的正确用法（API 与调度）

### T2.1 官方调用序列

```
HammerOpt = Tools.OpenHammerOptimization()
HammerOpt.RunAndWaitWithTimeout(seconds)   # 持续运行 N 秒（ISystemTool 基类方法）
HammerOpt.Cancel()
HammerOpt.WaitForCompletion()
HammerOpt.Close()
```

### T2.2 两个禁止

| 禁止 | 原因 |
|---|---|
| `AutomaticOptimization=True` | 那是界面上的"自动优化"按钮，**只迭代一轮就停**，不是持续运行 |
| 异步 `start_hammer` + 后续 `stop_hammer` | 状态引用跨调用会丢，`stop_hammer` 失效 → **整段优化成果丢失** |

### T2.3 推荐姿势：分段跑

`run_optimization(algorithm="Hammer", duration_seconds=N)` 内部即 `RunAndWaitWithTimeout + Cancel + WaitForCompletion`，**结果必定 commit 回系统**。每段结束读 MF 判断收敛，再决定是否续跑。

### T2.4 Hammer 异常会影响连接

Hammer 工具异常退出会结束 IPC 管道，连带断掉 extension 连接，甚至闪退。建议在 OpticStudio 里取消勾选「断开连接时自动关闭」。

### T2.5 自动落盘：`<原名>_0000_HAMMER.zos`

- Hammer 运行中/结束时，Zemax 自动把当前最优解另存为 `<原名>_0000_HAMMER.zos`（`0000` 为更优解序号），OpticStudio 重启后自动重新打开它。
- **判据**：`get_project_context` 看 `current_file` 是否带 `_0000_HAMMER` 后缀，再 `get_merit_function` 对 MF。
- **收尾**：`save_file(filename=正式名)` 另存回正式文件名，保持命名统一。
- 结论：**「连接断开 / 重启」≠ 优化结果丢失**。

---

## T3. `check_interference` —— 实体净空（首选判据）

**声明存在 ≠ 工具可用。** 该工具曾只在 `TOOL_DEFINITIONS` 里声明、没有实现，调用返回「未知工具」。新环境首次使用先试一次。

| 项 | 内容 |
|---|---|
| 参数 | `min_clearance=0.1`（元件间，0.2~0.25mm 空气层是正常设计）、`stop_clearance=2.0`（光阑座） |
| 算法 | 按 `z_edge = z_vertex + sag(R, h)` 算所有相邻实体（透镜↔透镜、透镜↔光阑）的真实最小净空；球面 sag 对 r 单调，极值只在 r=0 或口径边界 |
| 返回 | `clearance_mm` / `clearance_at`（`axis`、`edge_common`、`edge_own_sd`）/ `clearance_common_mm` / `clearance_own_sd_mm` |
| 语义 | `<0` = fail（实体相交）；`< 阈值` = warn；否则 pass |
| 附带 | 生成 `layouts/_clearance_check.png`：**按 LDE 数据画**，不看 Zemax 位图，确定性可复现 |
| 边界 | 超半球（SD > \|R\|）时 sag 无解，在该对 `notes` 里注明，不静默给错数 |

### T3.1 禁止的验证方式

**不要用「导出布局图 + PIL 标定像素」量净空。** 需要手工取 x0 与 px/mm，历史连错三次（光轴行取错、光阑累计距离算错两次、口径取错），还把标注画到画布外裁掉过。
仅在必须给"看图证据"时使用，且**必须自检**：用首尾两点标定后，要求所有面位与理论 z 逐一吻合（≤1~2px），不吻合即标定作废。

### T3.2 与 `MNEG` 读数不一致是正常的

`MNEG(1,11;0) ≥ 1` 与 `check_manufacturability` 报的 ET（如 1.03 vs 0.98）会不一致：后者取**最大半口径（含倒角区）**算 ET，`MNEG` 按通光口径算。**不是约束失效**，别盲目加权重。

---

## T4. 读数类工具的静默错误（最危险的一类）

### T4.1 判据汇总

| 现象 | 结论 |
|---|---|
| 多视场报出**一模一样**的值 | 工具坏了，不是"设计对称" |
| 报出的数**恰好等于**另一处已知值 | 复制 bug（参数没写对） |
| `settings_report.applied` 为空 | 参数一个都没进去，数据不是你要的那一份 |

### T4.2 `get_image_quality` 归一化基准取错（已修）

曾用「最后一个视场」当基准。视场降序排列（16/14/12/8/4/0°）时最后一个是 0° → 基准为 0 → 所有视场 Hy 都被算成 0 → **全部读成轴上值**。已修为遍历全部视场取 `max|y|`。

### T4.3 `get_distortion` 三处错（已修）

1. `num_points=5` 的 `round()` 抽样在 6 视场时得到 1,2,4,5,6，**漏掉 12°**。
2. 用 DISC 逐视场时**实算值不随视场变化**（16° 实为 2.16% 却报 0.35%，写 col3 读回 OK 也没用）。
3. "最大畸变"那行把**波长写进 Int1（视场位）**，等价于只算 14°。

修正后：视场数 ≤12 时遍历全部；逐视场用 `DIMX(Int1=视场号, Int2=主波长, Int3=0)`；最大值行用 `DIMX(Int1=0, Int2=主波长)`。与原生分析逐位吻合。

**权威交叉验证**：`get_field_curvature_distortion_data`（原生 FieldCurvatureAndDistortion），其 `text_preview` 直接给出「最大畸变 = x.xxxx%」，比任何操作数读数可信。

### T4.4 `get_mtf` 参数布局写错（已修）

MTFT/MTFS 临时操作数法的场参数从未生效：5 个视场报**完全相同**的 0.4181，且该值恰等于 **100 lp/mm 的轴上值** → 把轴上值复制给全部视场。
根因：旧代码把 `Int1` 当波长、`Int2` 当视场。修复后逐视场不同、子午/弧矢分开，并与 `get_fft_mtf_vs_field` 逐位对齐。

**MTF 验收的权威工具仍是 `get_fft_mtf_vs_field`**（原生，逐视场 T/S 互不相同）。返回体大时会落盘，用 jq 取 `mtf_vs_field_summary.frequencies[].fields[].min_TS`。

### T4.5 `check_field_illumination` 是坏的（未修，禁止使用）

用 RELI 临时操作数法，三个视场报**同一个值** 0.641172（未区分视场）→ 同值即 bug。

**替代**：相对照度一律用 `get_relative_illumination_data`（原生，逐视场不同、单调下降）。判断"边缘视场 RMS 好得反常是不是被口径挡掉大部分光瞳"时，也只能用这份原生数据交叉验证。

---

## T5. 参数被**静默丢弃**（`Analysis.GetSettings()` 泛型接口）

| 项 | 内容 |
|---|---|
| 症状 | `get_spot_diagram_data(wave=1)` 传 g 线，返回 4 个波长 RMS **完全相同**，且与 `wave=0`（合并值）不同 → 设置"部分生效" |
| 根因 | `Analysis.GetSettings()` 返回泛型 `IAS_` 接口，**没有 `Field`/`Wavelength` 属性**。代码写成 `if wave_value is not None and hasattr(settings, "Wavelength")` → 条件恒 False，整块跳过 |
| 更坑的点 | `settings_report` 的 `applied` 和 `failed` **都是空数组**：既没成功也没报错 |
| 代价 | 把 g 线真实代价藏了两天：只能看到 4 波长合并值 3.52，看不到 g 线单独 4.98 |

**修复要求**：
1. `_ANALYSIS_SETTING_INTERFACES` 必须为每个要用 Field/Wavelength 的分析配 CastTo：
   `standard_spot → IAS_Spot`、`ray_fan → IAS_RayFan`、`opd_fan → IAS_OpticalPathFan`、`fft_mtf_vs_field → IAS_FftMtfvsField`、`huygens_mtf → IAS_HuygensMtf`。
2. `hasattr` 失败时**记入 `failed`**，不许静默。

**判据**：调任何分析类工具后先看 `settings_report`。`applied` 为空 = 参数没进去。**门槛不在算得准不准，而在有没有把参数真正送进去。**

**残留**：解析层仍把单波长结果复制成 4 份（`waves` 数组恒为 4 个相同值）。取第 1 个值正确，但展示误导。

---

## T6. `DIMX` 返回绝对值 —— 做不出负畸变

| 项 | 内容 |
|---|---|
| 实证 | d 线原生 32° = **−0.68442436%**，同位置 `DIMX` 读 **+0.68442436%**（逐位相同、符号相反）。`get_distortion` 直接读 `Operand.Value` 未做 abs，正号来自 Zemax 本身 |
| 直接 `target=−1` 的后果 | 罚项 `(−1 − \|D\|)²` 恒 ≥1 永不归零 → MF 暴涨 **478 倍**（0.000415→0.198），畸变反被压向 **0**（实测 0.197/0.187%） |
| 本质 | `DIMX` 是单侧 `≤` 约束：负畸变同样满足"≤2%"，优化器会把"边缘变负"当**免费自由度**换像质 → 畸变曲线边缘过零变号（中段枕形 + 边缘桶形） |

**正确姿势**：
1. **接受幅值等价**：教材 `−1%` 的可达成等价物是「幅值 ≤1%」（`DIMX(0,2)=1`），再用原生分析确认符号。实测 32° = −1.0000% 精确命中，靠的是"约束幅值 + 让优化器自选符号"。
2. **`REAY` 视场号禁止塞进 `hx`**：`REAY(hx=1)` 被当 Hx，追 y 像高恒 0 的点 → 畸变全 0、MF=0（追迹失败）。正确写法 **`hx=0`(Field=0) + `hy`(归一化视场) + `py=0`(主光线)**。
3. **绝对像高法改不了绝对水平**：Zemax 畸变参考焦距 `f_dist` 随优化漂移（0.972→0.951→0.929），像高与参考同步下移、比值不变。把 y(22.4°) 压 −4% 只换来畸变 2.09→1.95%。验收一律读原生逐点数据。

---

## T7. `set_wavelengths` 会重置 MFE 里的波长引用

| 项 | 内容 |
|---|---|
| 症状 | 优化中 AXCL/LACL 值突然 = 0；`get_operands` 显示波长参数从 (1,3) 变成 (1,1) |
| 根因 | `set_wavelengths` **删除并重建波长列表**，Zemax 把 MFE 里引用波长号的行重置为 1 |
| 处置 | `set_wavelengths` 之后**必须用 `edit_operand` 逐条核对/修正所有含波长号的操作数**（AXCL/LACL/EFFL/DIMX 等） |
| 预防 | 波长尽量在加操作数之前设好；必须中途改时，改完立即全查一遍 MFE |

---

## T8. `EFFL` 的波长号存储位置异常（2024 R1）

写入 Int1 读回 0，实际生效在 **Int2**。`add_operand(int1=2)` 的值会落到 Int2 → 直接用 `edit_operand(row, int2=波长号)` 修正，并以 `get_operands` 读回的 `value` 是否合理判断是否生效。

**配套**：本工具链**没有曲率 solve 工具**。教材"给最后一面加曲率 solve 保焦距"的做法不可用，等价标准做法是——最后一面半径也设变量 + 加 `EFFL(target, weight=5, 波长=d光)`。

---

## T9. 主波长控制

三条波长等权重时，主波长默认取第 1 条（F 线）。要主波长 = d 光，把权重设为 `0.5 / 1.0 / 0.5`。

---

## T10. 向导参数是枚举值，`start_at` 是覆盖

| 参数 | 映射 |
|---|---|
| `rings` | `0=1环 1=2环 2=3环 3=4环 4=5环 5=6环` |
| `arms` | `0=6 1=8 2=10 3=12` |

- Zemax 标准默认（3 环 × 6 臂）= `rings=2, arms=0`；6 环 × 12 臂 = `rings=5, arms=3`。
- 误读后果：以为"2 环 0 臂"在跑，实际一直是 3 环 6 臂。
- `start_at` 是**从该行开始覆盖**，不是"追加到末尾"。换采样密度只需再调一次并指定同一 `start_at`，**不必清空重建**（曾把 167 行一次扩到 581 行）。
- 要"追加不覆盖"用 `set_default_merit_function_after_current_block`。
- **换采样后 MF 可比性**：数值同量级跳变（0.0007569 → 0.0007568）说明标度未变、可直接比较；跳一个数量级说明采样权重变了，不能直接比。

---

## T11. 光阑与镜片共面：结构缺陷修复四步

**判据（抄表时就要看）**：**STO 行带材料 + 带厚度 = 该面既是光阑又是某元件首面。** 此时 `check_interference` 报该对净空恒 0.000，而 `check_manufacturability` 一切正常、点列图也好看，优化多少轮都不变。

```
1  insert_surface(position=光阑面)                    插入一段空气
2  edit_surface(新面, radius="Infinity", thickness=0.5~0.85, is_stop=True)
3  edit_surface(原前一面, thickness -= 新面厚度)        保住 TOTR
4  clear_operands(confirm=True) → 重建 MFE             ★必须重建，见 T12
```

**重建清单模板**：

```
EFFL(2)=f w1 / TOTR=目标 w3
MNCA(每个空气面, 同)  — 常规 0.1、光阑两侧 0.4~0.85、BFL ≥2
MNEG(1, 末玻璃面) ≥0.5
MNEA(光阑面, 下一镜面) ≥净空   ★
+ 向导（use_air_thickness=false，空气约束全部手工给，避免与手工条重复夹逼）
```

**只约束中心距会立刻 fail**：加 `MNCA(7,7)=0.4` 后 `check_interference` 报光阑→元件④ **−0.117mm**、元件⑥→⑦ **−0.143mm**，因为该面前表面 R=−12.64 强凹，边缘比中心**前凸 0.51mm**。改 `MNCA=0.85` + `MNEA(7,8)=0.3` 后全部转正（+0.34 / +0.28）。

**结论**：光阑独立化**没有像质代价，反而略好**（MF 6.442e-4 → 6.406e-4）。光阑面厚度成为新变量，多出的自由度抵消了光阑离开镜面的像差变化。**别怕改结构，但改完必须重建 MFE 并重跑全套几何体检。**

---

## T12. 插/删面后 MFE 面号全错位 —— 必须重建，不能修补

**判据（重建后立即数）**：`MNCA` 条数 = **元件数 + 1（光阑）**。
6 片 + 独立光阑 → 必须 7 条，覆盖 `L1→L2, L2→L3, L3→STO, STO→L4, L4→L5, L5→L6, L6→BFL`，每条再配一条 `MNEA(前, 后)` 管边缘。数不够就是漏了。

**为什么必然漏**：**光阑不是"一个空气面"，而是"一对空气面"**（镜后→STO、STO→镜前）。按空气面顺序数，STO 前面那个间隔夹在两个光学面之间，形状上像"元件内"而不像"元件间"，于是被漏掉。

**实测教训**：7 片版删 L2 后按面号 2/5/8/10/12/14 写了 6 条 `MNCA`，自以为"全覆盖"，优化收敛到 MF 3.82e-4 很漂亮，但 `check_interference` 报元件②→光阑 **−0.774mm 实体相交**（该面被压到 0.128mm，而其前表面在该高度鼓出 0.902mm）。补 `MNCA(4,4)=1.2`（≥ sag 0.902 + 0.3）+ `MNEA(4,5)=0.3` 后转 +0.300。

**普适结论**：`run_optimization` 收敛得好**不代表结构合法**。MF 只惩罚评价函数里的东西，漏掉的约束不在里面，优化器会心安理得地穿模。**每次删/插面后，`check_interference` 与优化同等重要。**

---

## T13. `check_manufacturability` 把平行平板当透镜 → 假 fail

| 项 | 内容 |
|---|---|
| 症状 | 补入 cover glass 与 IR-cut 后 `overall` 从 warn 变 **fail**：报「ET=0.210 < 0.3 极薄」「CT=0.210 < 1.0 过薄」「半口径/CT=19.2 变形」「B=999 极端弯月」 |
| 原因 1 | 平板没有"边厚/中心厚"概念。0.21mm 是**蓝玻璃标准规格**（行业只 0.21 / 0.30 / 0.50 三档） |
| 原因 2 | `B = (R2+R1)/(R2−R1)`，`R1=R2=∞` 时分母为 0 → 输出 999 |
| 原因 3 | 工具不区分「透镜元件」与「平板/窗口」 |
| 判据 | `overall: fail` 若只来自平面-平面那一对（先看 fail 挂在哪两个面，再查这两面半径是否都是 Infinity）→ **忽略** |
| 待改进 | `R1`、`R2` 均为 ∞ 时跳过 CT/ET/B 校验，或单列"平板/窗口"类只查口径与厚度公差 |

---

## T14. 自己渲染的点列图：光点是 Zemax 的，艾里圈是脚本的

**事实**：ZOS-API 的 Analysis 类没有位图导出接口（`Analysis.ToFile` 只写 148 字节文本），所以 `export_spot_diagram_image` 是**自绘**的。各元素来源不同：

| 元素 | 来源 | 可信 |
|---|---|---|
| 光点坐标 | `spot_ray_points`（真实追迹） | ✅ |
| RMS / GEO | 点列图分析的 `spot_data` | ✅ |
| **艾里圈** | **脚本按公式另算** | ❌ 曾错 6.4 倍 |

**两个叠加 bug（`_airy_radius_um`）**：
1. **把 F 数当 EPD**：`ApertureType=ImageSpaceFNumber` 时 `ApertureValue` 返回的是 **F 数（1.4）**而非 EPD（应 EFFL/F# = 10.84）→ NA 小 7.7 倍。
2. **永远取第 1 个波长**：按 `weight > best_weight` 选主波长，权重全为 1.0 时只有第 1 个满足 `1.0 > -1.0`，之后恒 False → 停在 0.486 而非 0.588。**必须用 `IsPrimary`。**

合成 `0.61×0.486/0.0461 = 6.4358 µm`（真值 1.004）——**大 6.41 倍**。

**正确公式**：`r = 1.22·λ·F#`，`F# = EFFL/EPD`。**不要**用 `0.61·λ/sin(atan(EPD/2/EFFL))`（用真实 NA 反推会再偏大 ~6%）。

**按孔径类型换算 EPD**：`0=EPD`；`1,4=像方/近轴工作F#` → `EPD=EFFL/F#`；`3=FloatByStopSize` → 物面半口径×2；`5=物方NA` → `EPD≈2f·NA`。

**★ 判据（最重要）**：**图上的圈必须能追溯到一次 ZOS-API 读数，不能只靠公式自证。** 用"RMS/艾里 = 2.42，图上直径比也是 2.42"来验证圈是**循环论证**（比值本身来自被检验的公式），两个数一起错也能对上。唯一有效验证是拿 Zemax 界面数值或 RAID 实测 NA 交叉。

**影响范围**：报告里的 RMS / GEO / ×艾里倍数是对的（另一条代码路径），错的只有"看图得到的印象"。历史点列图 PNG 都带同样的错圈，需重新导出。

---

## T15. 无热化 / 公差工具（跨 skill：本文件只列能力边界）

| 类别 | 工具 |
|---|---|
| 无热化 | `set_temperature_configs`、`add_thermal_pickup_solve`、`set_thermal_glass_tce`、`optimize_athermal`、`get_thermal_defocus` |
| 公差 | `set_tolerances`、`run_tolerance_sensitivity`、`run_tolerance_monte_carlo`、`get_tolerance_report`、`set_tolerance_compensator` |

⚠️ 这批工具的**字段映射（SolveType ID / wizard 字段名）需在连接状态实测微调**，代码为容错式模糊匹配 + 回退。
**API 真相与实测状态不在本 skill** —— 见 `zemax-athermal-skill/references/mcp-tool-status.md`。

**正确顺序**：设计达标 ✅ → 无热化（需温度范围 + 镜筒材料）→ 公差分析（需公差等级）→ 装调验证。**不是继续调像质。**

---

## T16. 存档与备份行为

| 工具 | 副作用 |
|---|---|
| `save_file()` 空参 | **覆盖当前文档路径**（可能写脏备份）→ 只用 `save_file(filename=正式路径)` |
| `run_optimization` | 自动落盘到**当前路径**；分段跑前先「另存阶段名 → 再另存工作名」两次切回，否则覆盖存档 |
| `clear_operands` / `edit_operand` / `remove_surface` | 在 `<文件目录>/backups/` 生成 .zos/.ZDA 备份；用户不要时完工后删除 |

**文件格式**：`.zos`（Zemax 2024）是**二进制**，`grep`/`head` 读不出内容。判面数/结构一律走 `get_system_info`；判版本可粗看大小（车载 52KB ≈ 18 面旧版、131KB ≈ 20 面场镜版）。
