# Zemax 公差分析工作流（本工具链实务）

> 2026-11-04 全链路打通并实测通过。**老结论「公差工具是坏的」已作废**：
> 以前跑不出结果，是因为缺了下面 §2 的三个前置动作，不是 API 不可用。

## 1. 工具能力

| 工具 | 能力 | 关键参数 |
|---|---|---|
| `set_tolerances(grade)` | 写向导设置 + 重建 TDE | `grade` 支持 `loose/medium/tight` 和 **`q1`…`q8`** |
| `run_tolerance_sensitivity(criterion)` | 灵敏度：每项单独扰动 | 运行前自动清 MCE + 清求解（`strip_solves` 默认 True） |
| `run_tolerance_monte_carlo(trials)` | 蒙特卡洛良率 | 默认 200；建议 ≥200 |
| `get_tolerance_report()` | 读最近报告 + TDE 逐行回读 | 报告文件 UTF-16，需自动识别 |
| `set_tolerance_compensator(surf, param, min, max)` | 写/改 COMP 补偿器 | `min=max=0` 可用来做对照 |

## 2. 三个前置动作（缺一个就跑出假结果）

**① 清 MCE 操作数 —— 这是最隐蔽的坑。**
无热化模型在 MCE 里写的是 CRVT/THIC **硬值**，优先级高于 LDE 单元格。参考组态
（25 ℃）下硬值正好等于名义值，模型看着完全正常，但公差对 LDE 的扰动会被
MCE 硬值覆盖 → **TFRN/TTHI 灵敏度全表恒为 0.00000000**。实测：清掉 28 条 MCE
操作数后，立刻出现正常的 1e−5 ~ 1.4e−3 量级变化。
做法：`MCE.SetCurrentConfiguration(1)` → `MCE.RemoveOperandsAt(1, n)`。

**② 清求解（Thermal Pickup / Material Substitute / 半口径自动）。**
对每个面的 `RadiusCell / ThicknessCell / ConicCell / MaterialCell / SemiDiameterCell`
调 `MakeSolveFixed()`。别忘了回读校验 `hasattr(cell, "_S_ThermalPickup")`——
只统计调用次数会漏掉"调了但没生效"。

**③ 公差在「单组态 + 25 ℃」下做。** 多组态会按组态逐个跑，温度混入公差预算没有意义。

> 三件事都做，`_strip_solves()` 已合并实现，`run_tolerance_*` 默认自动调用。

## 3. TDE 直写接口（实测）

```
IToleranceDataEditor : NumberOfOperands / InsertNewOperandAt(r) / GetOperandAt(r) /
                       RemoveOperandAt(r) / RemoveOperandsAt(a,b) / AddOperand
                       SEQToleranceWizard / LoadToleranceFile / SaveToleranceFile
IToleranceOperand    : ChangeType(int) / type / typeName / Param1..3 / Min / Max /
                       Comment / IsMinUsed / IsMaxUsed
```

`ChangeType` **只吃 int**，传字符串报 `invalid literal for int()`。
`typeName` 返回 `"<行号>: TFRN"`，取冒号后那段做类型名。

枚举值（`AvailableOperandTypes()` 全量扫描得到的真值）：
`TFRN 3 · TTHI 4 · TIRC 14(TIRR) · TEDX 17 · TEDY 18 · TETX 20 · TETY 21 ·
TIND 28 · TABB 29 · TSTX 10 · TSTY 11 · TSDX 7 · TSDY 8 · COMP 32`

**`TEDX/TEDY` 吃的是「表面范围」不是单面**：`Param1=首面`、`Param2=末面`。
只写首面会报「非法表面范围」；写成 `s..s`（单面）会变成**表面偏心**，
像差大两个量级（实测 TEDX 1 1 → RMS 从 2.1 µm 炸到 130 µm）。

**胶合双胶合的元件范围必须合并**：范围不能重叠，否则蒙特卡洛报
「违反嵌套规则: 外部一对必须先于内部一对; 所有对必须嵌套」并中止。
元件 = 首面 `s` 到「后面是空气」的面 `e`：
`e = s+1; while e<=n_last and mat_of[e] != "": e += 1`。
例：S6–S7 之间无空气 → 元件是 6..8，不是 6..7 与 7..8 两个。

## 4. ITolerancing 的执行与读数（容易卡住的地方）

- **`Tools.OpenTolerancing()` 在已有工具未关闭时静默返回 `None`**，不抛异常。
  先 `Tools.CurrentTool` → `CastTo(..., "ISystemTool")` → `Cancel/WaitForCompletion/Close`。
- **派生接口包装器不含基类成员**：`Run / WaitForCompletion / Close` 在 `ISystemTool` 上，
  必须 `_cast_to_system_tool(tol)` 转型后调用。直接 `tol.Run()` 报没有该方法。
- **`ITolerancing` 没有 `GetTextFile`**。报告靠 `tol.OutputFile = <路径>`，
  且**必须在 Run 之前设置**，否则不落盘。
- 报告文件是 **UTF-16LE**，按 UTF-8 读会得到满屏 `\u0000` 乱码。
- `SetupMode`（`SetupModes` 枚举）：`Sensitivity=0` / `InverseLimit=1` /
  `InverseIncrement=2` / **`SkipSensitivity=3`**。**蒙特卡洛要用 3**——
  用 1/2 会先算反敏感度，MTF 判据下必然报「名义MTF比最大 MTF要小，不能计算反敏感度」并中止。
  模式 0 也会附带输出 MC 段，但白跑一遍灵敏度。

## 4.5 判据换成 MTF（`Criterions` 枚举，实测）

```
Criterion = 0  RMSSpotRadius    1 RMSSpotX   2 RMSSpotY   3 RMSWavefront
            4  MeritFunction    5 GeometricMTFAverage  6/7 Geometric Tan/Sag
            8  DiffMTFAverage   9/10 DiffMTF Tan/Sag   11 BoresightError
            12 RMSAngularRadius 13/14 Angular X/Y      15 UserScript
```
`8` = 衍射 MTF 的（子午+弧矢）平均，最贴近「MTF 复色 > x」这类验收口径。
频率用 **`tol.MTFFrequency = 120.0`**（此属性不在成员枚举里，但可写、可回读）。

**关于「复色光」**：报告头固定打印 `测试波长 : 0.5880`（主波长），**这不代表单色**。
判别方法：把名义值与该系统 FFT MTF vs Field 的加权平均对照——
本例复色平均 0.5754、单色 0.588 平均 0.6306，公差名义 0.5705 → **取的是复色**。
不要因为那行 0.588 就去改波长设置（`IToleranceWizard.TestWavelength` 写了也不影响工具）。

## 5. 标准流程

```
T1  设计已收敛 + 无热化方案已定（温度会吃公差余量，顺序不能反）
T2  save_file 另存 <名>_公差Q5.zos     ← 公差副本，保住无热化原文件
T3  set_tolerances(grade="q5")          向导设置 + 重建 TDE
T4  核对 TDE 行（get_tolerance_report 的 tde.rows）
T5  run_tolerance_sensitivity            自动清 MCE/求解 → 看最敏感项
T6  run_tolerance_monte_carlo(trials=200)
T7  get_tolerance_report                 报告 + 逐行 TDE
T8  不达标 → 收紧关键项 / 加补偿器 / 回光学改设计
```

## 6. 判据

| 判据 | 阈值 | 适用 |
|---|---|---|
| 90% 良率 | 90% 样本满足像质规格 | 最常用（车载/消费电子） |
| 97.7%（±3σ） | 高可靠 | 车规安全件 |
| CPK | ≥1.33 | <1.0 说明公差给不住 |

像质规格用常温设计值留 20~30% 余量，别直接拿设计值当规格。

**补偿器会吸收半径/厚度类公差的离焦分量**，这是正常的：清 MCE 之前若看到
TFRN/TTHI 全 0，先查 MCE（§2①）；清完之后仍有吸收，属于近轴调焦的真实作用，
不要误判成"公差没加上"。

## 6.5 实测案例：车载长焦前摄 15mm F/1.4（Q5，6 元件 69 条 TDE，**500 次 MC**；结构为双高斯演化）

| 规格 | 判据 | 名义 | 均值 | σ | P10 | 良率 | 95% CI |
|---|---|---|---:|---:|---:|---:|---:|---|
| 纯 Q5 | MTF>0.35 | 0.5705 | 0.436 | 0.0686 | 0.338 | 86.5% | — |
| 纯 Q5 | RMS≤5 µm | 2.13 µm | 3.43 µm | 0.86 | — | 93.4% | — |
| **胶合 ±0.01875** | MTF>0.35 | 0.5705 | **0.481** | 0.055 | 0.409 | **99.0%** | [97.7, 99.6] |
| **胶合 ±0.01875** | RMS≤5 µm | 2.13 µm | **3.03 µm** | 0.60 | — | **99.6%** | — |
| 胶合 ±0.025（Q4） | MTF>0.35 | 0.5705 | 0.464 | 0.060 | 0.382 | 96.2% | [94.1, 97.6] |

**只收紧一处就翻盘**：胶合组两片中心厚从 ±0.0375 收到 ±0.01875（双胶合常规做法），
MTF 良率 86.5%→99.0%，RMS 良率 93.4%→99.6%。

**放宽一档要看 CI 下界**：放宽到 Q4 ±0.025 后良率 96.2%，点估计仍过 95%，
但 95% CI 下界 94.1% 跌破 95%，无法承诺 ≥97%；加工上 ±0.019 与 ±0.025 同属一档，
成本差远小于 2.8 pp 报废 → **不放宽**。

**结论性经验**：MTF 判据比 RMS 判据严格得多（同一组公差，86.5% vs 93.4%）。
客户规格写的是 MTF 时，绝不能用 RMS 良率交差。

## 7. 常见坑
1. **MCE 硬值覆盖 LDE** → TFRN/TTHI 恒为 0（§2①，最隐蔽）。
2. **求解没清** → 同样是 TFRN/TTHI 归零，且 `MakeSolveFixed` 要回读校验。
3. **TEDX 写成单面** → 变成表面偏心，像差大两个量级。
4. **元件范围重叠**（胶合组）→ 蒙特卡洛「违反嵌套规则」直接中止。
5. **补偿器 Min/Max 被忽略**：报告固定输出「警告:将会忽略补偿器上的边界约束」，
   设 0 也不等于关闭，行程不参与真假判断。
6. 偏心与倾斜同时给 → 同一误差算两遍，二者等效（θ≈d/f），留一个。
7. 折射率按"每片独立"抽样 → 良率虚低；同熔炼批 nd 一致，应按批。
8. 蒙特卡洛次数 <200 → 良率抖动，90% 与 88% 分不清。
9. 非球面只给曲率公差、不给面形 → `TIRR` 必须单独给（见 `zemax-asphere-skill`）。
10. 忽略镜筒/隔圈公差 → 装配后仍超差，隔圈厚度通常 ±0.02~0.05 mm。

## 8. 与其它 skill 的分工
| 需要什么 | 看哪里 |
|---|---|
| **Q1–Q8 等级表、厂商对照、ISO 默认公差** | `references/production-tolerance-grades.md` |
| 温度漂移、主动调焦行程 | `zemax-athermal-skill` |
| 非球面面形/反曲/非球面度 | `zemax-asphere-skill` |
| 评价函数、操作数语义 | `zemax-ADAS-skill/references/operands.md` |
| 工具报错、参数静默失效 | `zemax-ADAS-skill/references/zosmcp-troubleshooting.md` |
