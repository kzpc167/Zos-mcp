---
name: zemax-ADAS-skill
description: 'ADAS 车载镜头光学设计经验（从双高斯起步）。记录用 zosmcp MCP 工具进行"平面起步法"双高斯设计的完整流程、评价函数配置、替代玻璃+Hammer 优化、渐晕设置、关键坑与解法。Use when: 设计 ADAS 或相机镜头、双高斯物镜、镜头初始结构构建、评价函数优化、EFFL 保证焦距、波长引用被重置、替代玻璃替换、Hammer 全局优化、渐晕/拦光等非变焦设计场景。'
---

# ADAS 镜头设计经验 — 从双高斯起步（zosmcp 实战）

> 本 skill 由实战沉淀，全部操作通过 zosmcp（mcp__zemax-opticstudio__*）完成，
> 不新建 Python 脚本、不手动建 .zmx 文件。

> **📌 设计思路（方法论）见 `references/design-thinking.md`** —— 那是本 skill 的灵魂：
> 结构选型、起步求解、优化分阶段、收敛判断、像差平衡、ADAS 特殊思路。
> 操作步骤（本文件）是"怎么动"，设计思路是"为什么这么动"。做任何新设计前先读思路专篇。

> **📌 操作数物理含义 + 选型逻辑见 `references/operands.md`** —— 每个操作数代表什么物理量、
> 何时该用、目标值/权重怎么定。配评价函数前先读它。

> **📌 渐晕的物理原理 + ADAS 权衡见 `references/vignetting.md`** —— 为什么做渐晕、像质⇄照度权衡、
> VCX/VCY 语义、ADAS 里该拦多少。设渐晕前先读它。

> **📌 具体案例数值不进 skill** —— 面表、半口径、玻璃替换链、A/B 两版对比等交付快照，
> 统一放在 `D:/Zemax-mcp/zemax-ADAS/*_设计报告.md`。本 skill 只保留可复用方法 + §六 的压缩基准。
>
> 分层：`SKILL.md`＝怎么做（含压缩基准）｜`design-thinking.md`＝为什么｜`operands.md`＝操作数

## 〇、zsomcp 能力扩展记录（替代玻璃 + Hammer）

本次训练过程中，为完成"替代玻璃优化"，给 zosmcp 扩展了两个能力（已合并进 `tools.py`）：

1. **`make_variable(param="material")`** —— 把玻璃设为"替代玻璃(Substitute)"变量
   - 用法：`make_variable(surface_number=N, param="material", variable=true, catalog="SCHOTT")`
   - 实现要点（血泪教训）：`CreateSolveType(22)` 只是**创建** solve 对象，**必须再调 `SetSolveData(solve)` 写回单元格才生效**，否则读回 `material_solve` 仍是 1(Fixed)。
   - 验证：`get_system_info` 会读回每个面的 `material_solve`，**22=替代玻璃**，1=固定，2=变量。

2. **`run_optimization(algorithm="Hammer")`** —— 锤优化/全局搜索
   - 替代玻璃的**离散替换**只能由 Hammer 触发，DLS/OD（局部优化）不会换玻璃。
   - **官方正确用法（ZOS-API IHammerOptimization）**：
     ```
     HammerOpt = Tools.OpenHammerOptimization()
     HammerOpt.RunAndWaitWithTimeout(seconds)  # 持续运行 N 秒，超时后工具继续跑
     HammerOpt.Cancel()                         # 停止
     HammerOpt.WaitForCompletion()              # 等异步停止
     HammerOpt.Close()
     ```
   - ⚠️ **坑：不要设 `AutomaticOptimization=True`** —— 那是 Hammer 里的"自动优化"按钮，只迭代一轮就停，
     不是"持续运行"。持续运行要靠 `Run()` / `RunAndWaitWithTimeout()`（ISystemTool 基类方法）。
   - ⚠️ **坑：Hammer 工具异常退出会导致 IPC 管道结束，连带断掉 OpticStudio 的 extension 连接**，
     甚至可能闪退。建议在 Zemax 里取消勾选「断开连接时自动关闭」。
   - 实战验证：连续跑约 3.5 分钟后，玻璃从 SK2/SK16/F5 替换为 SK15/PSK52/F5/F5/PSK53A/SK16，MF 再降 0.5%。

**关键经验**：
- 改 MCP 代码后**必须读回验证**，不能只看工具返回的 `ok`（本次就因"返回 ok 但 solve 没生效"踩了坑）。
- **替代玻璃没替换 = 跑的时间不够，不是"玻璃已最优"**（实战纠正过的错误认知）。
- `SolveType` 枚举：`MaterialSubstitute=22`、`Variable=2`、`Fixed=1`。
- **长时间 Hammer 的可靠姿势**：用 `run_optimization(algorithm="Hammer", duration_seconds=N)` 分段跑
  （内部 RunAndWaitWithTimeout + Cancel + WaitForCompletion，**结果必定 commit 回系统**），
  每段结束读 MF 判断收敛。不要用异步 `start_hammer`（状态引用跨调用会丢，`stop_hammer` 失效 → 整段优化成果丢失）。
  实战：步骤6 重做时 120 秒 × 2 段，MF 0.001788 → 0.000645（↓64%），玻璃整体换血。

3. **Hammer 会自动落盘最优解（`_0000_HAMMER.zos`）—— 结果不会因 OpticStudio 重启而丢**
   - Hammer 运行期间/结束时，Zemax 自动把当前最优解另存为 `<原名>_0000_HAMMER.zos`（`0000` 是更优解序号）。
   - OpticStudio 重启后会自动重新打开这个 `_0000_HAMMER.zos`。所以「连接断开 / OpticStudio 重启」≠ 优化结果丢失。
   - 验证方法：`get_project_context` 看 `current_file` 是否带 `_0000_HAMMER` 后缀，再 `get_merit_function` 对 MF。
   - 收尾动作：把这个 `_0000_HAMMER.zos` **另存回正式文件名**（`save_file(filename=正式名)`），保持命名统一。
   - 实战：Hammer 收敛到 MF 0.000801 后 OpticStudio 自动重启，一度以为结果丢了；实际早已自动存成
     `双高斯3_0000_HAMMER.zos` 并被重新打开，MF 逐位吻合。

### 🚨 铁律：zemax MCP 工具必须【严格串行】调用

**绝不能在同一条消息里并行发多个 `mcp__zemax-opticstudio__*` 调用。**
ZOS-API 的 COM 是 STA 单线程模型，MCP 服务器在同一线程上串行处理调用；并发调用会直接让 MCP 服务器进程崩溃
（现象：前几个返回 ok，后续全部 `Connection closed`，随后 `Not connected`，`tasklist` 里 python 进程消失，
而 OpticStudio 本身还活着）。恢复只能重启 WorkBuddy，且**内存里未保存的改动会丢**。

好的做法：逐个调用 → 等结果 → 再发下一个；批量改 10 个变量就老实地发 10 次。省下的那几秒远不值一次崩溃。

## 一、设计任务定义（首例）

双高斯物镜：f′=100mm，D/f′=1/3（即 F/3，EPD=33.33mm），2ω=28°（ω=14°），可见光 F/d/C。

## 二、"平面起步法"初始结构构建（核心方法）

教科书方法：拿一组成熟双高斯范例（如 SK2 + SK16/F5 胶合 + 光阑 + F5/SK16 胶合 + SK16 单片），
**保持所有厚度与玻璃不变**，然后：

1. **两个胶合面保持平面**（范例中它们本来就是平面，不动）
2. **其余 7 个折射面半径全部取平面**（radius=1e18）
3. **最后一个折射面承担全部光焦度**：
   - 初始半径用单折射面公式：**R = -(n_d - 1) × f′**
   - 例：SK16 nd=1.62041 → R = -0.62041 × 100 = **-62.041mm**
   - 实测一次到位：EFFL=100.0003mm（无需迭代！）
4. **变量**：7 个折射面半径 + 离焦量（最后面到像面的厚度）
5. 孔径/视场/波长：EPD=33.33、Angle 视场 0/10/14°、F(0.4861)/d(0.5876)/C(0.6563)

## 三、评价函数配置（教材法）

清空 MFE 后逐条添加（add_operand）：

| 操作数 | 参数（单元格） | Target | Weight | 含义 |
|--------|--------------|--------|--------|------|
| RSCE | Int1=3(Ring), Int2=0(Wave=主), Hx=0, Hy=0 | 0 | 1 | 轴上 RMS 光斑(质心) |
| RSCE | 同上, Hy=0.7 | 0 | 1 | 0.7 视场 |
| RSCE | 同上, Hy=1 | 0 | 1 | 全视场 |
| AXCL | Int1=1(F), Int2=3(C) | 0 | 1 | 轴向色差 F-C |
| LACL | Int1=1(F), Int2=3 | 0 | 1 | 倍率色差 F-C |
| GMTT | Int1=2(Samp), Int2=0(Wave), Hx=1(Field), Hy=20(Freq) | 1 | 1 | 轴上子午几何 MTF@20lp/mm |

单元格映射经验：**GMT 系列的 Field/Freq 在 Hx/Hy 列**（不是 Int3/Int4）。

## 四、关键坑与解法（实战血泪）

### 坑 1：优化后焦距跑飞（最重要！）
- **现象**：7 个半径设变量优化后 EFFL 100→61.88。因为优化器把平面改成曲面，光焦度重新分布。
- **根因**："最后一面保证焦距"教材上是给最后面加曲率 solve，但 **zosmcp 没有 solve 工具**。
- **解法**：把最后面半径也设为变量 + 加 `EFFL(target=100, weight=5, 波长=d光)` 操作数。
  这是无 solve 工具时等效且标准的做法。最终 EFFL 收敛到 100.007。

### 坑 2：set_wavelengths 重置 MFE 波长引用（隐蔽！）
- **现象**：优化中发现 AXCL/LACL 值突然=0，查 `get_operands` 发现波长参数从 (1,3) 变成 (1,1)。
- **根因**：`set_wavelengths` 会**删除并重建波长列表**，Zemax 把 MFE 里引用波长号的行重置为 1。
- **解法**：`set_wavelengths` 之后**必须用 `edit_operand` 重新核对/修正所有含波长号的操作数**（AXCL/LACL/EFFL 等）。
- **预防**：波长尽量在加操作数之前设置好；若必须中途改，改完立即全查一遍 MFE。

### 坑 3：EFFL 波长号存储位置异常
- 该 Zemax 版本（2024 R1）EFFL 的波长号写入 Int1 读回 0，实际生效在 Int2 列。
- `add_operand` 传 `int1=2` 时值实际落到 Int2 —— 直接用 `edit_operand(row, int2=波长号)` 修正，
  并以 `get_operands` 读回的 value 是否合理来判断是否生效。

### 坑 4：主波长控制
- 三条波长等权重时主波长默认第 1 条（F 线）。要主波长=d 光，设权重 0.5/1/0.5。

### 坑 5：zosmcp 自动备份
- `clear_operands` / `run_optimization` / `edit_operand` / `remove_surface` 等都会在
  `<文件目录>/backups/` 自动生成 .zos/.ZDA 备份。用户不要备份时，完工后删除该目录。

### 坑 6：渐晕因子（VCX/VCY）语义方向 —— 极易搞反（最重要！）

- **Zemax 视场数据里的 Vignetting Factors（VCX/VCY）＝「渐晕掉的比例」，不是「压缩/保留比例」**：
  - **0 = 无渐晕**（也是未设置时的默认值，读回 0.0）
  - **1 = 100% 渐晕**（光束压到零，一根光线都过不去）
- 用户说「Y 方向渐晕因子 ≤ 0.45、X ≤ 0.3」，数值就是**拦光量上限**，直接写 **VCY=0.45、VCX=0.3**，
  不要做什么「1 − 上限」的换算（换算了就方向反了）。
- 实战踩坑：曾把 VCX/VCY 理解成「压缩因子」，给 0° 视场设 1.0/1.0 → 轴上光线**全部消失**（点列 RMS=0）；
  给离轴设 0.7/0.55 → 实际拦光 70%/55%，超出上限。正确终态：0° 设 0/0，离轴设 0.3/0.45。
- **设置入口**：`set_fields(fields=[{x,y,vcx,vcy}, ...])`（已支持字段级 vcx/vcy）。IField 上直接有
  `VCX`/`VCY` 可写属性（在 `_prop_map_put_` 里），无需 VignettingFactors 包装对象。
- **验证唯一可靠判据**：`set_fields` 返回的 `readback`（读回各视场 Y/VCX/VCY）＋ 点列图光线是否消失。
  ⚠️ 半口径（semi_diameter）和 `get_vignetting_diagram_data` 的文本预览**都不能**可靠反映渐晕因子
  （前者由「清除渐晕后光线」决定，后者缓存旧结果）。
- **渐晕只加离轴视场**：轴上 0° 视场保持 0/0（无渐晕），否则白白损失轴上照度。
- 副作用：重度渐晕后 2D 横截面导出（OpenCrossSectionExport）可能写空文件并 fallback 到 3D。

## 五、评价函数正确姿势（重要！先向导后操作数）

**推荐流程（用户指定，效果远好于纯手工操作数）：**
1. 先 `clear_operands` 清空
2. 先 `add_operand` 追加自定义约束（EFFL / AXCL / LACL 等）——它们占据 MFE 前几行
3. 再 `set_default_merit_function_after_current_block` 生成**点列图优化向导**（data=1 Spot Radius）
   ——自动追加在自定义约束之后，避免覆盖
4. `run_optimization` 迭代

**对比效果（同一双高斯）：**
| 指标 | 纯手工(RSCE+GMTT) | 向导+约束 |
|------|------------------|-----------|
| MF | 0.181 | 0.00177（尺度不同，点列图RMS）|
| AXCL(F-C) | 0.138 mm | **0.0020 mm** |
| LACL | 0.036 mm | **0.0076 mm** |
| EFFL | 100.007 | 100.06 |

**要点：**
- `set_default_merit_function_after_current_block` 是关键工具——它在当前 MFE 末尾追加向导块，
  **不会覆盖**前面已加的自定义操作数（而 `set_default_merit_function` 会从 start_at 覆盖）。
- 点列图向导生成大量 TRAC 操作数（本次 139 行，含玻璃/空气厚度边界约束 MNCT/MXCT 等）。
- 建议开启 `use_glass_thickness` / `use_air_thickness` 约束防止厚度跑飞。
- 色差用 EFFL+AXCL+LACL 三个操作数约束即可，无需手工 RSCE。

## 六、优化历程与最终基准（双高斯 f′=100 / F3 / 2ω=28°）

> 最早期"纯手工操作数（RSCE+GMTT）"版本的数据（MF 0.181、AXCL 0.138mm）已并入第五节对比表，不再单列。

### 6.1 步骤 1~6 的 MF 递进（同一系统，逐步放/收变量）

| 步骤 | 变量集 | 评价函数 | MF |
|------|--------|----------|-----|
| 起点（平面起步）| — | — | EFFL=102.06（未锁）|
| 1 | 8 个折射面半径 + 离焦量（两个胶合面固定）| 弥散圆 + `EFFL(2);100;1` | 0.00214 |
| 2 | ＋2 个胶合面半径（共 10 个半径）| 同上 | 0.00144 |
| 3 | ＋全部 8 个厚度（6 块透镜 + 光阑前后 2 空气间隔）| 同上 | 0.00112 |
| 4 | 收窄：厚度只留 4 块胶合透镜厚度 + 2 空气间隔 | 同上 | 0.00111 |
| 5 | 收窄：只留 10 半径 + 离焦量 + 2 空气间隔（13 变量）| 同上 | 0.00111 |
| 6 | ＋6 块玻璃设替代玻璃（共 19 变量），Hammer 持续跑 | 同上 | **0.0006453** |

**读法**：步骤 1→3 每放一批自由度降一档；步骤 4→5 收变量 MF 不动（结构更干净、像质不损）；
步骤 6 替代玻璃 + Hammer 一次降 64%（0.001788 → 0.0006453）。

### 6.2 最终基准（步骤 6 完成后，可直接拿来对比新任务）

| 指标 | 值 |
|------|-----|
| EFFL | 100.011 mm |
| TOTR | 126.89 mm |
| 点列图 RMS（0 / 0.7ω / 1.0ω）| 3.51 / 4.35 / 4.60 µm |
| 最大几何光斑（同上）| 7.42 / 7.49 / 14.50 µm |
| 玻璃（Hammer 自动替换后）| N-LASF44 / N-FK51 / KZFS8 / F2 / N-LAK12 / N-LASF31 |

### 6.3 两条可直接复用的判据

1. **纯弥散圆（点列图 RMS）+ EFFL，vs 追加 RSCE/AXCL/LACL/GMTT 专项约束**：
   前者把**全视场压均匀**（边缘 14.70 → 4.60 µm），但**轴上略退**（1.98 → 3.51 µm）、总长更短（138.35 → 126.89 mm）；
   后者轴上更尖锐、边缘更松、色差控制更明确。**要均衡选前者，要轴上极限/明确色差指标选后者。**
2. **步骤 6 不放透镜厚度变量 → 必出极端弯月**：
   实测两个胶合组弯曲因子 B = −5.13 / +5.42（`check_manufacturability` 报 warn），
   边厚虽仍为正（2.0~22.9 mm），但加工与彗差校正困难。**下一轮务必放开透镜厚度或加形状约束。**

> **完整案例数值（面表、半口径、玻璃替换链、A/B 两版对比）见交付报告
> `D:/Zemax-mcp/zemax-ADAS/双高斯2_设计报告.md`** ——
> 本文件只保留上面的压缩基准，**同一份数字不存两处**（存多处必然随迭代腐坏）。

## 七、标准流程模板（可直接复用）

```
1. get_system_info            // 读范例结构，核对玻璃/厚度/胶合面
2. edit_surface ×7            // 非胶合折射面 → 平面(1e18)
3. edit_surface               // 最后折射面 R = -(nd-1)×f′
4. get_first_order_data       // 验证 EFFL（公式法通常一次到位）
5. make_variable ×N           // 半径 + 离焦量 + 空气间隔（🚨严格串行，一次一个）
6. clear_operands(confirm)    // 清空 MFE
7. add_operand EFFL           // EFFL(int2=主波长号); 100; 1 —— 自定义约束【先】加
8. set_default_merit_function_after_current_block  // 弥散圆向导【后】追加，不覆盖
9. run_optimization DLS ×N    // 直到 MF 相邻两轮差 <0.001
10. run_optimization OD       // 换算法确认收敛
11. 要换玻璃时：make_variable(param="material", catalog="SCHOTT") ×6
    → run_optimization(Hammer, duration_seconds=120) 分段跑，每段读 MF
12. get_first_order_data      // 核对 EFFL；若跑焦 → 坑1解法
13. get_operands / get_system_info  // 核对操作数值、material_solve；波长引用被重置 → 坑2解法
14. check_manufacturability   // 边厚 + 弯曲因子，防止极端弯月
15. export_layout_image       // 串行分别导出 3D (view=current, angle_x/y/z=0, hide_lens_edges=true) 与 2D
16. save_file                 // 原地保存
17. 删除 backups/（如用户不需要）
```

### 布局图交付

- 完成设计检查后，使用 `export_layout_image` 导出并交付两张布局图；两个 MCP 调用必须严格串行。
- 三维图使用 `layout_type="3D"`、`view="current"`、`angle_x=0`、`angle_y=0`、`angle_z=0`、`hide_lens_edges=true`，保存为 `layouts/layout_3D.png`。
- 二维图使用 `layout_type="2D"`，保存为 `layouts/layout_2D.png`。
- 检查工具返回成功及图片路径，并在最终回复中提供两张图片；若某张导出失败，明确报告失败，不要把另一种视图冒充为它。

## 八、下一步（ADAS 化方向）

双高斯只是训练起点。ADAS 车载镜头的真正差异点（待后续实战补充）：
- 大视场（30°~120°+）：反远摄/鱼眼结构替代双高斯
- 无热化（-40~85°C）：多玻璃组合消温漂
- 高相对照度：光阑位置与像方远心度设计
- 像高定义视场：ParaxialImageHeight 而非 Angle
