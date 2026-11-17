# 工作流模板（路线 A / B / 渐进孔径 / 变量分批）

> **何时加载**：选定路线、准备第一步操作时；或优化中途确认"下一步按什么顺序做"时。
> **本文件只放可抄的步骤序列**；为什么这么排、每步边界 → `staged-optimization.md`；操作数选型 → `operands.md`；红线 R# 均指 `SKILL.md` §2。
> 所有步骤受 `SKILL.md` §1 M1–M3 前置门约束：`make_variable` / `run_optimization` 前必须贴阶段表。

---

## W1 路线 A：平面起步法（无现成面表）

```
1  get_system_info              核对范例玻璃/厚度/胶合面
2  edit_surface ×7              非胶合折射面 → "Infinity"
3  edit_surface                 最后折射面 R = -(nd-1)×f′
4  get_first_order_data         验证 EFFL
5  make_variable ×N             按 A1→A3 分批放曲率；离焦/空气间隔留到 B 阶段（严格串行）
6  clear_operands(confirm=True)
7  add_operand(insert_at=1..K)  规格 + 护栏【置顶】
8  set_default_merit_function(start_at=K+1)
9  run_optimization(DLS) ×N     连续两轮 <1% 停
10 run_optimization(OD)         换算法确认收敛
11 make_variable(param="material") ×N → Hammer 分段跑（先补护栏，R4）
12-17 一阶量 → 操作数/材料读回 → 几何体检 → 导出 3D → save_file(正式路径)
```

---

## W2 路线 B：专利 / 教材四步法

```
【建结构】
B1  get_project_context / get_system_info
B2  insert_surface(position=2) ×N       原面全部后移
B3  edit_surface(radius, thickness, material) 逐面填（平面传 "Infinity"）
B4  edit_surface(is_stop=True)          自动取消原光阑
B5  set_aperture / set_fields / set_wavelengths
B6  get_first_order_data + get_image_quality   核对 EFFL/TOTR/BFL

【步 1｜DLS：允许集 = 10 半径 + 4 正透镜厚 + 光阑前后空气；按 A1→A3、B1→B3 逐批加入，玻璃固定，3 视场】
B7-B9   make_variable(按 A1→A3 / B1→B3 分批设，每批跑 DLS + 按 `staged-optimization.md` 第 3 节汇报)
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

【验收】B34-B36 见 `SKILL.md` §5
```

**三条顺序铁律**：拓扑从不由优化器决定（改片数人工换结构）；玻璃一定放在形状之后（形状还差时换玻璃必得畸形补偿组合）；约束只能逐步加严，不能中途放松。

---

## W3 渐进孔径子流程

```
C0 EPD = EFFL / F#            由目标 F 数换算入瞳直径
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

---

## W4 变量分批

不在这里重复。执行前读 `staged-optimization.md` 第 3 节：A1→A3 / B1→B4 状态机、每批放什么、汇报表与熔断判据。
