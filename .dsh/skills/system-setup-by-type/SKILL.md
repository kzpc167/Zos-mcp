---
name: system-setup-by-type
description: '根据光学系统类型动态确定正确的 Zemax 设置参数（孔径类型/视场类型/评价函数操作数/关键约束）。Use when: 开始任何新的光学设计任务时，或需要确定孔径、视场、MF 操作数的正确配置时。关键词: 系统参数设置、孔径类型、视场类型、评价函数、远摄、显微、望远、投影、准直、扩束、f-θ、柯克、双高斯。'
argument-hint: '描述你要设计的光学系统类型（如"航拍物镜"、"显微物镜 NA=0.4"、"激光准直镜"等）'
---

# 光学系统参数设置指南（动态版）

## 使用本 Skill 的流程

**第一步**：根据用户描述，识别系统类型（见下文分类表）。
**第二步**：按该类型的配置表设置孔径、视场、波长、评价函数操作数。
**第三步**：如遇多种特征混合（如"远摄+变焦"），取各自最高优先级配置合并。

---

## 系统类型识别关键词

| 系统类型 | 关键词/特征 |
|---|---|
| 普通相机/航拍物镜（无穷远物） | 相机、航拍、物镜、无穷远、F数、像高 y' |
| 远摄物镜 (Telephoto) | 远摄、TP、远摄比 γ<1、前后组、压缩总长 |
| 反远摄物镜 (Retrofocus) | 反远摄、广角、κ>1、BFL>f'、鱼眼 |
| 显微物镜 (Microscope) | 显微、物镜 NA、有限共轭、放大率β、物距有限 |
| 望远物镜 (Telescope) | 望远、开普勒、伽利略、物镜+目镜、角放大率 |
| 准直镜 (Collimator) | 准直、平行光输出、点光源→平行、激光准直 |
| 投影物镜 (Projection) | 投影、SLM、LCD、DLP、有限共轭、像方远心 |
| f-θ 扫描物镜 | f-θ、扫描、振镜、激光打标、平场扫描 |
| 激光扩束镜 (Beam Expander) | 扩束、扩束比、高斯光束、开普勒/伽利略扩束 |
| 柯克/天塞物镜 (Cooke/Tessar) | 柯克、CK、天塞、三片、三组 |
| 双高斯物镜 (Double Gauss) | 双高斯、DG、大孔径、大视场、6片 |
| 变焦镜头 (Zoom) | 变焦、多重结构、焦距可变、变倍比 |

---

## 各类系统完整配置

---

### 1. 普通相机物镜 / 航拍物镜（无穷远物，有限像高）

**典型指标**：f=50~1000mm，F/2~10，y'=4~22mm，无穷远物距

**孔径**：
```
# 选其一：
set_aperture("EntrancePupilDiameter", EPD)   # EPD = f / F#
set_aperture("ImageSpaceFNumber", F)
```

**视场**（用近轴像高，因为 y' 是像高规格）：
```
set_fields("ParaxialImageHeight", [
  {"x": 0, "y": 0},
  {"x": 0, "y": 0.7 * y_max},
  {"x": 0, "y": y_max}
])
```

**波长**：F/d/C 三色（可见光，消色差设计必须）
```
set_wavelengths(wavelengths=[
  {"value": 0.4861, "weight": 1},
  {"value": 0.5876, "weight": 1},
  {"value": 0.6563, "weight": 1}
])
```

**物面**：保持默认无穷远（OBJ thickness = infinity，无需修改）

**评价函数关键操作数**：
```
EFFL  target=f,   weight=5,  int1=2   # 锁定焦距（d光）
BFL   target=BFL, weight=0          # 监视后焦距（仅监视）
TOTR  target=T,   weight=1,  int1=1  # 总长约束（可选）
DIMX  target=3,   weight=0.1         # 畸变 <3%（可选）
```

---

### 2. 远摄物镜 (Telephoto, γ<1)

**典型指标**：f=250~1000mm，F/3~10，γ=0.65~0.85，前组正+后组负

**孔径**：同相机物镜，用 EPD 或 Image Space F/#

**视场**：
```
set_fields("ParaxialImageHeight", [...])  # 同普通物镜
```

**波长**：F/d/C 三色（同上）

**评价函数关键操作数（远摄专用）**：
```
EFFL  target=f,    weight=5,  int1=2        # 系统总焦距
EFLY  target=f1,   weight=3,  int1=1, int2=前组最后面  # 前组焦距
EFLY  target=f2,   weight=3,  int1=后组第一面, int2=后组最后面  # 后组焦距（负值）
DIVI  target=γ,    weight=10, int1=TOTR_row, int2=EFFL_row  # 远摄比 γ=T/f
TOTR  target=T,    weight=1,  int1=1        # 总长
CTGT  target=d_min, weight=1, int1=组间空气面  # 前后组间隔下限
CTLT  target=d_max, weight=1, int1=组间空气面  # 前后组间隔上限
MNCG  target=2,    weight=0.02, int1=1, int2=最后玻璃面  # 玻璃最小中心厚
MNEG  target=2,    weight=0.02, int1=1, int2=最后玻璃面  # 玻璃最小边缘厚
MXCG  target=18,   weight=0.02, int1=1, int2=最后玻璃面  # 玻璃最大中心厚
MXEG  target=18,   weight=0.02, int1=1, int2=最后玻璃面  # 玻璃最大边缘厚
```

**前后组焦距计算公式**（薄透镜近似，用于初始设计）：
$$f_1' = \frac{\gamma f'}{2-\gamma}, \quad f_2' = -\frac{\gamma^2 f'}{4(1-\gamma)}$$

**注意**：`DIVI` 操作数需要引用已存在的 TOTR 和 EFFL 行号（Int1/Int2），须在它们添加后才能设置。

---

### 3. 反远摄物镜 (Retrofocus, κ>1)

**典型指标**：广角/鱼眼，BFL > f'，前组负+后组正

**孔径**：
```
set_aperture("EntrancePupilDiameter", EPD)
```

**视场**：大视场，视场角方式（用 Angle 而不是像高）：
```
set_fields("Angle", [
  {"x": 0, "y": 0},
  {"x": 0, "y": 0.7 * ω_max},
  {"x": 0, "y": ω_max}
])
```

**评价函数关键操作数**：
```
EFFL  target=f,    weight=5
CTGT  target=BFL,  weight=1, int1=最后玻璃面  # BFL 下限（BFL/f > κ）
DIMX  target=3,    weight=0.1                  # 畸变约束（广角畸变大，酌情放宽）
```

**注意**：反远摄比 κ = BFL/f' > 1，需要用 `CTGT` 约束最后一面厚度（即 BFL）大于目标值。

---

### 4. 显微物镜 (Microscope Objective)

**核心特点**：有限共轭物距、物方 NA 定义孔径、反向追迹（物在像面方向）

**孔径**（有限共轭用近轴工作 F/#）：
```
# NA' = n' * sin(u')，有限共轭时：
set_aperture("ObjectSpaceNA", NA)
# 或：F/# = 1/(2*NA)，用 ImageSpaceFNumber = 1/(2*NA)
```

**物面设置**（有限物距！必须修改第0面厚度）：
```
edit_surface(0, thickness=-L_object)  # 负值，物在镜前，如 -190mm
# L_object = f' * (1 - 1/β) * ... 见共轭距公式
```
共轭距公式：$f' = \frac{-\beta L}{(1-\beta)^2}$，三个量只给两个权重，一般给焦距和共轭距。

**视场**（用物高，因为规格给的是视场直径/物方）：
```
set_fields("ObjectHeight", [
  {"x": 0, "y": 0},
  {"x": 0, "y": 0.7 * y_object},
  {"x": 0, "y": y_object}
])
```

**波长**：可见光三色，或按应用（荧光显微需考虑特定波长）

**评价函数关键操作数**：
```
EFFL  target=f,   weight=5,  int1=2        # 焦距
TTHI  target=L,   weight=1,  int1=0, int2=最后面  # 共轭距 L（物到像）
ISNA  target=NA,  weight=3                  # 像方 NA 约束
PMAG  target=β,   weight=0                  # 监视放大率
```

**评价函数类型**：推荐用**波前优化**（Wavefront），显微物镜是小像差系统，波前优化更适合：
```
set_default_merit_function(data=0, ...)  # data=0 = Wavefront
```

**光阑位置**：光阑卡在第一个透镜表面（`is_stop=True` on surface 1），**光阑厚度不释放为变量**。

---

### 4B. 完整显微镜系统 (Microscope + Eyepiece)

**核心特点**：显微物镜与目镜合成，既要保持物镜共轭距/工作距/NA，又要保持目镜焦距和总倍率。不能直接套普通显微物镜或普通相机物镜模板。

**孔径**（按讲义 6-3）：
```
set_aperture("ImageSpaceFNumber", 2.0)
set_ray_aiming(enabled=true, mode="Paraxial")
```

**视场**：完整目视显微镜通常按目镜视场角检查，例如 10x/20° 目镜可用：
```
set_fields("Angle", [
  {"x": 0, "y": 0},
  {"x": 0, "y": 14},
  {"x": 0, "y": 20}
])
```

**讲义 6-3 评价函数骨架**（行号必须用 `build_operand_block` 的 label/ref 自动解析，不手写）：
```
# MAGNIFICATION
REAR/REAY surface=intermediate_image_surface, wave=2, hy=1  # 物镜物高，监视
REAR/REAY surface=objective_image_surface,     wave=2, hy=1  # 物镜像高，监视
DIVI target=10, weight=0~0.1                                # 物镜倍率；讲义为监视，工程优化可低权重锁定
CONS target=250                                             # 明视距离
EFLY int1=eyepiece_first_surface, int2=eyepiece_last_surface, target=25, weight=0
DIVI target=10, weight=0                                    # 目镜倍率监视
PROD target=100, weight=0.1                                 # 总倍率

# SYSTEM TRACK / WORKING DISTANCE
TTHI int1=eyepiece_first_surface, int2=final_surface, target=231, weight>0
TTHI int1=objective_start_surface, int2=final_surface, target=195, weight=0.1
CTGT int1=last_objective_glass_surface, target=7, weight=0.1~1  # 工作距下限，不是精确等式

# THICKNESS BOUNDARY
MNCT/MNET/MNCG/MNEG/MXCG/MXEG 只约束物镜可变玻璃面段；排除成熟目镜和 0.17mm 盖玻片。
```

**面号规则**：讲义中的 `9-14`、`15` 等面号只对讲义示例成立。Agent 必须先用 `get_system_info` / layout / surface comments 确认当前文件的真实面号；例如插入目镜后，物镜玻璃面段可能变成 `10-15`，此时局部边界用 `10-15` 是合理的。

**REAR 与 REAY 取舍**：讲义说明两者均可。`REAR` 只控制径向高度，适合绝对倍率；若需要验证倒像方向或符号，应改用 `REAY` 并检查目标正负号。

**SPT 到波前的切换**：先用 RMS spot 默认块收敛几何和点列图；若 MTF/波前未达衍射极限，再保持上述几何块不变，把默认块改为 Wavefront，并用短轮次 DLS 探路。不得在几何约束未稳时直接长轮次波前优化。

**通光/相对照度硬门槛**：完整显微镜按 20° 目镜视场检查时，每轮像质验收前必须优先调用 `get_relative_illumination_data()`。若最大视场相对照度为 0、低于工程阈值、`blocked_fields` 非空或 `drop_events` 显示边缘照度骤降，SPT、点列图、MTF 均不可作为有效像质结果，应优先调用 `get_vignetting_diagram_data()` / `get_ray_fan_data()` 定位遮拦，并处理渐晕/光阑/孔径/Ray Aiming/视场设置。`check_field_illumination()` 只作为 RELI 操作数兜底，不能替代 Analysis 图窗结果。

**MTF 验收**：显微镜 MTF 优化与验收使用标准 `MTFS`/`MTFT`，并优先用 `get_fft_mtf_vs_field(frequencies=[50,100,200,300])` 获取 Zemax Analysis 数据。临时 MFE 工具 `get_mtf/get_mtf_curve` 可用于快速复核；若工具、MFE、图窗之间不一致，先诊断参数和通光状态，不继续优化。

**APO 判断**：`AXCL` 只能说明近轴轴向色差，不能单独作为复消色差验收。APO 设计应结合三色多孔径 `REAY/TRAY` 差值约束、`get_longitudinal_aberration_data()`、`get_lateral_color_data()` 和边缘孔径球差检查。

**畸变约束**：显微镜可用 `DIMX/DISC` 监视畸变。早期优化不建议强压畸变，否则会和 NA、场曲、SPT 竞争；当 spot/NA 稳定后，若用途要求显微畸变 <1%，再以低权重加入。

---

### 5. 望远物镜 (Telescope Objective)

**核心特点**：无穷远物，角度视场，用口径（EPD）定义

**孔径**：
```
set_aperture("EntrancePupilDiameter", D)  # 口径 D，如 50mm/100mm
```

**视场**（望远镜用角度，规格给的是全视场角 2ω）：
```
set_fields("Angle", [
  {"x": 0, "y": 0},
  {"x": 0, "y": 0.7 * ω_max},
  {"x": 0, "y": ω_max}
])
```

**波长**：F/d/C 三色

**评价函数关键操作数**：
```
EFFL  target=f,    weight=5,  int1=2   # 焦距
TOTR  target=T,    weight=0            # 监视总长
BFL   target=BFL,  weight=0            # 监视后焦距（需留空间放目镜）
```

**注意**：若设计完整双组望远镜（物镜+目镜），需要在目镜物面处添加视场光阑（中间实像面）。

---

### 6. 准直镜 (Collimator) / 激光准直

**核心特点**：点光源→平行光输出（无穷远像），或平行光→聚焦到点

**孔径**：
```
set_aperture("EntrancePupilDiameter", D)
```

**视场**：单视场（轴上点），或小角度
```
set_fields("Angle", [{"x": 0, "y": 0}])
# 若激光单模则只需轴上视场
```

**物面**：**有限物距**（光源在焦面）：
```
edit_surface(0, thickness=-f)  # 物在焦点处，厚度 = -f'
```

**波长**：单色激光，按实际波长设置，如 1064nm：
```
set_wavelengths(wavelengths=[{"value": 1.064, "weight": 1}])
```

**评价函数关键操作数**：
```
EFFL  target=f,   weight=5
# 准直镜无像高约束，主要控制波前误差（OPD < λ/4）
```

**评价函数类型**：波前优化（小像差）：`data=0`

---

### 7. 投影物镜 (Projection Lens)

**核心特点**：有限共轭，像方远心（出瞳在无穷远），反向追迹（SLM在物侧），偏置

**孔径**：
```
set_aperture("ImageSpaceFNumber", F)
# 或 EntrancePupilDiameter
```

**物面**（SLM 在物侧，有限物距）：
```
edit_surface(0, thickness=-L_throw)  # 投影距（投射距）
```

**视场**（物高，规格给 SLM 芯片尺寸）：
```
set_fields("ObjectHeight", [
  {"x": 0, "y": 0},
  {"x": 0, "y": 0.7 * y_slm},
  {"x": 0, "y": y_slm}
])
# 若有 offset（偏置），x=0 但 y 从非零开始：
set_fields("ObjectHeight", [
  {"x": 0, "y": y_slm * offset_ratio},          # 偏置下边界
  {"x": 0, "y": y_slm * (0.5 + offset_ratio)},
  {"x": 0, "y": y_slm * (1 + offset_ratio)}     # 偏置上边界
])
```

**评价函数关键操作数**：
```
EFFL  target=f,    weight=5
PMAG  target=β,    weight=3   # 放大率约束（如 -0.5 表示 2× 缩小投影）
TTHI  target=L,    weight=1, int1=0, int2=最后面  # 共轭距
DIMX  target=1,    weight=1   # 畸变 <1%（投影畸变要求严）
```

**注意**：像方远心需要确认出瞳在无穷远，可在 MFE 中添加 `RANG` 操作数检查主光线角度。

---

### 8. f-θ 扫描物镜 (f-theta Scan Lens)

**核心特点**：负畸变满足 f-θ 条件（像高=f×θ），平场，无穷远物

**孔径**：
```
set_aperture("EntrancePupilDiameter", D_beam)  # 输入激光束径
```

**视场**（用角度，θ 是扫描角）：
```
set_fields("Angle", [
  {"x": 0, "y": 0},
  {"x": 0, "y": 0.7 * θ_max},
  {"x": 0, "y": θ_max}
])
```

**波长**：单色激光，按实际波长

**评价函数关键操作数**：
```
EFFL  target=f,    weight=5
DIMX  target=Δ,    weight=5   # 必须控制畸变！f-θ 需要负畸变满足线性关系
# f-θ 畸变目标值：Δ% = (θ/tan(θ) - 1) × 100，在最大扫描角处计算
# 例：θ_max=25°, tan(25°)=0.4663, θ_rad=0.4363 → Δ% = (0.4363/0.4663 - 1)×100 = -6.4%
```

**注意**：f-θ 物镜的畸变目标值是负的，需计算 $\Delta = (f\theta - f\tan\theta) / (f\tan\theta) \times 100\%$。

---

### 9. 激光扩束镜 (Beam Expander)

**核心特点**：无焦系统（afocal），输入/输出均为平行光，扩束比 = 出口直径/入口直径

**孔径**：
```
set_aperture("EntrancePupilDiameter", D_in)  # 输入光束直径
```

**视场**：单轴上视场（激光扩束不考虑视场）：
```
set_fields("Angle", [{"x": 0, "y": 0}])
```

**物面**：无穷远（默认）

**波长**：单色激光，按实际波长

**系统模式**：无焦系统，在 System → System Explorer → Afocal Image Space 中开启 Afocal Mode（若不支持 API，需手动操作）

**评价函数关键操作数**：
```
TTHI  target=d_total, weight=0    # 监视系统总长
# 用 ANAC（角度像差）代替 TRAC 进行波前优化
# 角度优化更适合无焦系统：
# set_default_merit_function(data=3 or 4)  # 角向优化
```

**注意**：无焦模式下评价函数应选**角向优化**（Angular Spot）而非 Spot Radius，API 中 `data=4`。

---

### 10. 柯克三片 / 天塞物镜 (Cooke Triplet / Tessar)

**核心特点**：三片 +-+ 结构，光阑在中间负片，中等视场

**孔径**：`EntrancePupilDiameter` 或 `ImageSpaceFNumber`

**视场**：
```
set_fields("ParaxialImageHeight", [0, 0.7*y', y'])
# 或角度视场（若规格给的是视场角 ω）：
set_fields("Angle", [0, 0.7*ω, ω])
```

**评价函数关键操作数**：
```
EFFL  target=f,   weight=5
BFL   target=BFL, weight=1   # 后焦距约束（需大于最后透镜到像面距离）
DIMX  target=3,   weight=0.1
```

---

### 11. 双高斯物镜 (Double Gauss)

**核心特点**：大孔径（F<2）、中偏大视场（2ω>60°），6片4组，光阑居中

**孔径**：大孔径，用 F# ：
```
set_aperture("ImageSpaceFNumber", F)  # 如 F=1.8
```

**视场**：
```
set_fields("ParaxialImageHeight", [0, 0.7*y', y'])
```

**拦光控制**：双高斯通常需要设置渐晕（vignetting）来限制大孔径斜光束像差，需要手动在 Field 设置 VDX/VDY（渐晕系数），API 无直接工具，需提示用户手动设置或跳过渐晕优化。

**评价函数关键操作数**：
```
EFFL  target=f,    weight=5
BFL   target=BFL,  weight=1   # 单反需要 BFL > 38mm（翻转镜空间）
DIMX  target=3,    weight=0.1
```

---

### 12. 变焦镜头 (Zoom Lens)

**核心特点**：多重结构（Multi-Configuration），每个结构对应一个焦距状态

**操作**：变焦系统**超出当前 MCP 工具能力**（多重结构编辑器 MCE 暂无 API）。
- 需提示用户：变焦系统的多重结构需要**在 OpticStudio GUI 中手动设置**。
- MCP 工具可以完成单一焦距状态的优化，但无法操作 MCE。

---

## 通用注意事项

### 物距与孔径类型的对应关系

| 物距 | 孔径类型推荐 |
|---|---|
| 无穷远 | `ImageSpaceFNumber` 或 `EntrancePupilDiameter` |
| 有限共轭（显微/投影） | `ObjectSpaceNA`（显微）或 `ImageSpaceFNumber`（投影） |
| 激光扩束（无焦） | `EntrancePupilDiameter`（输入束径） |

### 视场类型选择逻辑

```
如果 物距无穷远 且 规格给视场角 → Angle
如果 物距无穷远 且 规格给像高 y' → ParaxialImageHeight
如果 物距有限   且 规格给物方高度 → ObjectHeight
如果 物距有限   且 规格给实际像高 → RealImageHeight（畸变大时）
```

### 波长设置原则

| 应用 | 波长配置 |
|---|---|
| 可见光成像（消色差） | F(0.4861) / d(0.5876) / C(0.6563) μm，3条 |
| 可见光成像（单色） | d(0.5876) μm，1条 |
| 近红外成像 | 0.8 / 0.9 / 1.0 μm |
| Nd:YAG 激光 | 1.064 μm，1条 |
| He-Ne 激光 | 0.6328 μm，1条 |
| 蓝光激光（DVD） | 0.405 μm，1条 |

**严禁使用 `set_wavelengths` 的 `preset` 参数**（ZOS-API 2018 版不可靠）。

### 评价函数优化类型选择

| 系统特点 | 推荐优化类型 |
|---|---|
| 接近衍射极限（显微、准直） | 波前（Wavefront），`data=0` |
| 中等像差（相机、望远、投影） | 点列图半径（SpotRadius），`data=1` |
| 无焦系统（扩束镜） | 角向（Angular Spot），`data=4` |
| 需要控制 MTF | 添加 `MECT`/`MECS` 操作数 |
