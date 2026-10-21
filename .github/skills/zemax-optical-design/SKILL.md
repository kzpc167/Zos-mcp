---
name: zemax-optical-design
description: 'Zemax OpticStudio 光学设计与优化经验。Use when: designing lenses, optimizing optical systems via MCP tools, setting up merit functions, adding operands like EFFL/BFL, configuring wavelengths/fields/aperture, avoiding common pitfalls with COM interface and optimization divergence.'
argument-hint: '描述要设计的光学系统（如消色差透镜、望远物镜等）'
---

# Zemax OpticStudio 光学设计经验

## 适用场景

- 使用 MCP 工具与 OpticStudio 交互进行光学系统设计
- 构建消色差透镜、望远物镜等序列式光学系统
- 设置评价函数并运行优化
- 排查优化发散或结构不合理的问题

## 重要经验教训

### 1. 连接管理

- OpticStudio Interactive Extension 会话会超时断开，每次操作前应确认连接状态
- 若 `get_system_info` 返回连接错误，调用 `reconnect_zemax` 重连
- 重连前需在 OpticStudio 中重新点击 **Programming → Interactive Extension**

### 2. 波长设置

- **`set_wavelengths` 的 `preset` 参数在 2018 版 ZOS-API 中不可靠**，preset 调用后可能只保留1个波长
- **始终使用手动波长列表**，不用 preset：
  ```
  set_wavelengths(wavelengths=[
    {"value": 0.4861, "weight": 1},  // F 线
    {"value": 0.5876, "weight": 1},  // d 线
    {"value": 0.6563, "weight": 1}   // C 线
  ])
  ```
- 设置后必须用 `get_system_info` 验证波长数量和值是否正确
- 消色差设计必须至少使用 F/d/C 三个波长

### 3. 玻璃库管理

- **可通过 API 管理玻璃库**：`get_glass_catalogs` 查询可用/已加载目录，`set_glass_catalogs` 添加/移除目录
- 使用非默认玻璃（如 CDGM）前，先用 `get_glass_catalogs` 确认目录已加载，未加载则用 `set_glass_catalogs(add=["CDGM"])` 添加
- API 路径：`system.SystemData.MaterialCatalogs`（ISDMaterialCatalogData 接口）
- 常用 CDGM 玻璃：H-K9L（冕牌，低色散）、H-ZF1（火石，高色散）
- 常用 SCHOTT 玻璃：N-BK7（冕牌）、N-SF2 / N-SF5（火石）

### 4. 光圈设置

- F/# = f/D，所以 EPD = f / F#
- 例：f=100mm, F/3 → EPD = 33.33mm
- 用 `set_aperture("EntrancePupilDiameter", 33.33)` 设置

### 5. 评价函数设置（关键！）

- **先用 `set_default_merit_function` 生成基准操作数**（波前或光斑）
- **然后用 `add_operand` 添加约束**（如 EFFL 焦距目标）
- 评价函数向导会覆盖从 start_at 行开始的内容，所以**约束操作数要在向导之后添加**
- 推荐启用玻璃/空气厚度约束避免优化发散：
  ```
  set_default_merit_function(
    opt_type=0,           // RMS
    data=0,               // 波前
    reference=0,          // 质心
    rings=3, arms=3,
    use_glass_thickness=true, glass_min=2, glass_max=25,
    use_air_thickness=true, air_min=3, air_max=200
  )
  ```

### 6. EFFL 操作数

- `add_operand("EFFL", target=100, weight=5, int1=2)` 中 **int1 是波长序号**（推荐用 d 光所在序号）
- 权重建议 ≥ 2（与波前操作数竞争时需要较大权重才能精确收敛到目标焦距）

### 7. 变量设置策略（核心经验！）

- **分阶段放变量，不要一次全开！**
- ❌ **错误做法**：所有曲率+所有厚度同时做变量 → 优化器极易跑飞到物理不可能的解（负厚度、极端曲率）
- ✅ **正确流程**：
  1. 第1轮：仅 5 个曲率半径做变量，所有厚度固定 → 收敛到合理初始结构
  2. 第2轮：放开气隙、单片厚度、BFL 做变量（保持双胶合厚度固定） → 进一步优化
  3. **绝不要放开胶合透镜组内部厚度**（除非有明确的厚度约束），否则厚度会跑到不合理值
- 如果优化结果出现负厚度、极大厚度(>100mm)、极小曲率(<5mm) → 说明解已发散，需恢复初始值重来

### 8. 优化策略

- **DLS（阻尼最小二乘）**为主，每次跑 Automatic 循环
- DLS 收敛后再跑一轮 **OD（正交下降）** 确认是否有更优解
- 多轮迭代直到 MF 不再下降（两轮之间差异 < 0.001 即收敛）
- 如果 MF 很高（>1），检查是否有不合理的变量设置或缺少约束
- **用 `quick_focus` 时注意**：它用光斑尺寸准则，会移动像面位置，可能破坏波前优化结果。使用后需重新跑 DLS

### 9. "2+1" 消色差透镜初始结构参考

基于 DB-1 双胶合 (H-K9L + H-ZF1)，在后方加单片正透镜 (H-K9L)：

| 面 | R (mm) | T (mm) | 材料 | 说明 |
|----|--------|--------|------|------|
| 1 (STO) | 52.7 | 9 | H-K9L | 双胶合前片 |
| 2 | -45.8 | 2 | H-ZF1 | 双胶合后片 |
| 3 | -209.2 | 15 | (air) | 气隙，不宜太大(15-40mm) |
| 4 | 200 | 5 | H-K9L | 单片前面，弱正透镜 |
| 5 | -200 | 70 | (air) | BFL |

- 单片初始用对称双凸（R=200/-200）或弱弯月，让优化器自行调整
- 气隙不宜 > 50mm，否则单片口径利用率低

### 10. 结果验证

- `get_first_order_data` 读取 EFFL / TOTR 验证焦距和总长
- `get_operands` 查看所有操作数当前值
- MF < 0.07 waves RMS 近衍射极限（F/3 系统）
- 所有厚度应 > 0，气隙 > 2mm，BFL > 10mm

### 11. 厚度约束必须基于口径，而非固定值（关键！）

- `set_default_merit_function` 中的 `glass_max` 是优化器允许的玻璃最大厚度上限
- **如果设置过大（如 glass_max=20mm），优化器会将厚度打到上限，产生厚径比极大的透镜（如 φ35mm 透镜厚达 20mm），外形完全不合理**
- **正确做法：按口径估算**
  - 大口径透镜（φ>30mm）：`glass_max` ≤ 口径 30%，如 φ35mm → `glass_max=10`
  - 中等口径（φ15-30mm）：`glass_max` ≤ 口径 35%，如 φ20mm → `glass_max=7`
  - 负片/薄元件：`glass_min`=2、`glass_max` 可偏小（3-6mm）
- 放开玻璃厚度为变量时，需额外检查优化后的厚径比（`thickness / (2 × semi_diameter)`），超过 35% 应手动修正并重新优化

### 12. 表面厚度被"求解"锁定时必须检查 ZMX 文件

- 如果反复调用 `edit_surface` 修改厚度，但 `get_system_info` 显示该厚度始终不变 → **说明该面存在 Zemax 求解（Solve）**，最常见的是 `MAZH`（边缘光线高度求解）或 `MRAY`（近轴光线高度求解）
- **MCP 工具集目前不提供移除求解的功能**，此时必须直接编辑 ZMX 文件
- 处理步骤：
  1. 先调用 `save_file` 保存当前状态（确保文件是最新的）
  2. 用编辑器打开 ZMX 文件，找到对应 SURF 块中的 `MAZH` / `MRAY` 行，直接删除
  3. 设置正确的厚度数值（修改 `DISZ` 行）
  4. 用 `open_file` 重新加载修改后的文件
  5. 用 `get_system_info` 验证厚度值是否已生效
- 可以通过观察 ZMX 文件的表面块（SURF）判断求解类型：
  - `MAZH 0 0` → 边缘光线高度求解（锁定为某个高度）
  - `MRAY 0 0` → 近轴光线高度求解
  - `PRAM x y` → 参数求解

### 13. 双胶合透镜设计：不要对玻璃厚度做变量优化

- 双胶合只有 3 个曲率自由度，真正的光焦度和色差校正均由曲率控制
- 将玻璃厚度设为变量时，优化器总会将其推到 `glass_max` 上限（数学上有利但物理不合理）
- **结论：双胶合设计中，玻璃厚度应始终固定，仅以曲率半径 + BFL 作为优化变量**
- 合理厚度预设（参考 DB 系列）：
  - 冕玻璃正片（如 H-K9L）：T ≈ 口径的 20-25%，例如 φ80mm → T=16-20mm
  - 火石玻璃负片（如 H-ZF1）：T ≈ 口径的 8-12%，例如 φ80mm → T=6-10mm

### 14. 正确选择缩放的参考 DB 初始结构（关键！）

- DB-1 到 DB-6 的 F/# 从 3 到 10 对应不同孔径，**初始结构应选 F/# 与设计目标最接近的**
- 例如：目标 f=800mm F/10 → 选 **DB-6**（F/10），然后整体 × 8 缩放
- 缩放规则：所有曲率半径和厚度 × (f目标 / f参考)，通常 f参考 = 100mm
- 错误选择低 F/# 的参考（如用 DB-1 F/3 缩放到 F/10）会让优化器从错误的初始弯曲方向收敛到局部解

### 15. ZMX 文件编码：UTF-16LE 与 ASCII

- **新版 OpticStudio（2018+）保存的 ZMX 文件为 UTF-16LE 编码**，无法用 `read_file` 直接阅读（读出乱码字节）
- **旧版或手工创建的 ASCII 格式**可正常读取
- 判断方法：`read_file` 结果显示 `fe 56 00 45 00 52 00` → UTF-16LE；直接显示 `VERS ...` → ASCII
- **如需修改 UTF-16LE 文件结构**（如删除 solve、调整厚度），最可靠的做法是：
  1. 创建新的干净 ASCII ZMX 文件（用 `create_file` 工具）
  2. 直接填入正确的初始结构参数
  3. 用 `open_file` 加载后继续优化

### 16. 望远物镜（长焦、小视场）的评价函数设置

- 望远物镜视场极小（ω < 0.5°），像差以轴上球差和轴向色差为主，彗差/像散可忽略
- 评价函数**必须显式添加** AXCL 和 SPHA 操作数，否则优化器仅对 RMS 波前做最小化，色差可能被间接"换走"而非真正校正
- 推荐配置：
  ```
  set_default_merit_function(opt_type=0, data=0, ...)   // RMS 波前基准
  add_operand("EFFL", target=f, weight=5, int1=2)       // 焦距
  add_operand("AXCL", target=0, weight=2)               // 轴向色差
  add_operand("SPHA", target=0, weight=1, int1=1, int2=2) // 球差（近轴）
  ```
- AXCL 初始值若 > 0.1mm（相对于像素6.25μm极大），说明用了与 F/# 不匹配的初始结构

## 已知限制

- `set_wavelengths` 的 preset 参数在旧版本不可靠
- 无法直接读取像差图/MTF 数据（仅能读取 MFE 操作数值）
- COM 接口的 IWavelength.Value 属性在不同版本名称可能不同（已通过探测机制兼容）
- **MCP 工具不支持移除表面求解**（Solve），需直接编辑 ZMX 文件处理
- **`set_glass_catalogs` / `get_glass_catalogs` 工具存在 Bug**（`'method' object is not iterable`），无法通过 API 管理玻璃库；改为在 ZMX 文件的 `GCAT` 行直接写入所需目录名（如 `GCAT SCHOTT CDGM`）

## 标准设计流程模板

```
1. get_system_info                     // 查看当前状态
2. get_glass_catalogs                  // 检查玻璃库
3. set_glass_catalogs (如需添加)        // 加载所需玻璃库
4. set_wavelengths (手动列表)           // F/d/C 三色
5. set_aperture                        // 设置光圈
6. set_fields                          // 设置视场
7. insert_surface / edit_surface ×N    // 搭建初始结构
8. set_default_merit_function           // 启用厚度约束
9. add_operand("EFFL", ...)             // 焦距约束
10. make_variable (仅曲率)              // 第1轮：仅曲率
11. run_optimization (DLS Automatic)    // 优化
12. run_optimization (DLS Automatic)    // 确认收敛
13. make_variable (放开部分厚度)        // 第2轮：加厚度
14. run_optimization (DLS Automatic)    // 优化
15. run_optimization (OD Automatic)     // 换算法确认
16. get_first_order_data                // 验证焦距/总长
17. get_system_info                     // 检查结构合理性
18. save_file                           // 保存
```
