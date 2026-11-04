---
name: zemax-ghost-skill
description: '光学系统鬼影（Ghost）与杂散光（Stray light）分析：鬼影三要素（面反射率/几何/光源）、Path Analysis 与 ZRD 光线数据库、Ghost Focus Generator 的版本可用性、一阶鬼影估算、GISET 与 PST 判据、镀膜与 BSDF 设置、非序列建模要求。Use when: 做鬼影分析、杂散光分析、评估强光源鬼影、算 GISET 或 PST、判断某两个面的反射是否会落到像面、设置镀膜反射率、非序列模式建模、ZRD 路径筛选、鬼影整改。关键词：鬼影、Ghost、鬼影指数、GISET、杂散光、Stray light、PST、点源透过率、Veiling glare、ZRD、Path Analysis、Ghost Focus Generator、BSDF、ABg、镀膜、反射率、非序列、NSC、混合模式、Critical Ray Tracer。'
---

# 鬼影与杂散光分析

> **先分清两条链路**：鬼影（Ghost）是镜片表面之间的**两次反射**，序列模式就能算；
> 杂散光（Stray light）主要来自镜筒/隔圈的**散射与一次漫反射**，必须进非序列。
> 两者工具、数据、判据都不同，别混。

## 1. 鬼影三要素

鬼影强度 ≈ **反射率 × 几何遮拦 × 光源亮度**，三者缺一不可：

| 要素 | 需要什么 | 缺了会怎样 |
|---|---|---|
| **反射率** | 各面实测/设计镀膜曲线（AR 膜残余 0.2~0.5%，未镀膜 4%） | 鬼影强度差 20 倍，算出的数没意义 |
| **几何** | 面型 + 口径 + 光阑，判断鬼影是否落入像面、离像面多远 | 不知道鬼影是"糊成一团"还是"锐利成像" |
| **光源** | 强光源角位置（太阳、对向车灯、路灯） | 不知道哪个视场角最危险 |

**判据（GISET，鬼影指数）**：鬼影在像面的照度 / 主像照度。

| GISET | 判定 |
|---|---|
| > 1e-2 | 明显可见，必须整改 |
| 1e-3 ~ 1e-2 | 强光源下可见，需评估 |
| 1e-4 ~ 1e-3 | 弱，仅在极强光源下可见（多数车载的验收线） |
| < 1e-4 | 可接受 |

## 2. 本版 OpticStudio 的实际能力（2026-11-04 实测）

| 能力 | 状态 | 证据 |
|---|---|---|
| **Ghost Focus Generator** | ❌ **本版没有** | `I_Analyses` 的 90 个 `New_*` 方法里查无此项 |
| **Path Analysis** | ⚠️ 存在但受限 | `New_PathAnalysis` 可用，`IAS_PathAnalysis` 有 `RayDatabaseFile / FilterString / RelativeMinimumFlux / FirstRay / LastRay / SortBy / GeneratePathFilters` |
| **ZRD 光线数据库** | ❌ **API 无法生成** | 只能读（`Tools.OpenRayDatabaseReader`）；批量追迹 `IBatchRayTrace` 无 ZRD 输出 |
| Critical Ray Tracer | ✅ 有 | `New_CriticalRayTracer` + `Tools.OpenCriticalRaysetGenerator`，导出关键光线集给 CAD 做杂散光 |
| 非序列 NSC | 接口在，未封装 | `New_NSCSingleRayTrace` / `New_NSCGeometricMtf` / `Tools.OpenNSCRayTrace` |
| 镀膜 / BSDF 设置 | 未封装 | 需直接在 LDE `Coating` 列与 NSC 面属性里写 |

**结论：纯 API 跑不了鬼影分析**——Path Analysis 需要一个已存在的 `.ZRD`，而 ZRD 只能从 GUI 或非序列追迹产生。
本技能下文给出三条可落地路线。

## 3. 三条路线（按成本排序）

### 路线 A：GUI 生成 ZRD → API 分析（最快，推荐）

1. GUI 里跑一次带光线数据库的追迹（Analyze 菜单的 Ray Trace / 优化器的 Save Ray Database，
   或直接 `Tools.OpenNSCRayTrace` 在混合模式下开启 SaveZRD）。
2. 记下 `.ZRD` 路径。
3. 调 `get_ghost_path_analysis(zrd="...")`（本工具链入口，见 §5）→ 自动跑 Path Analysis，
   按 `RelativeMinimumFlux` 过滤并按通量排序，得到「哪些面组合、强度多少」。

Path Analysis 的本质是：把 ZRD 里每条光线的**完整路径段**枚举出来，
用 `FilterString`（如 `R2` = 两次反射）挑鬼影路径，`SortBy` 按通量排序。

### 路线 B：一阶鬼影估算（无 ZRD 时的替代，**已实测可用**）

纯解析 y–nu 递推，枚举 C(N,2) 个双次反射路径。实现见 `references/ghost-analysis-methods.md` §2，
本设计 91 个面组合跑完约 2 秒。

**必须先过的校验**（不过就不要看结果）：

| 量 | 判据 |
|---|---|
| TOTR | 与 Zemax 一阶量差 < 1e-3 mm |
| EFFL | 差 < 0.01 mm |
| BFL | 差 < 0.01 mm |
| 像面 y | < 0.01 mm（轴上应≈0） |

本设计实测：30.4995 / 15.1195 / 1.0804 / −0.0006，全部通过（残差来自用 nd 代替 0.588 µm）。
**校验不过 = 反射符号或反向传递方向写错了**，常见错法是反向传递没有取负厚度、
或第二次反射的 `(n'−n)` 用了 `−2n` 而不是 `+2n`。

三个关键实现点：
1. 反射统一写作 `u = u − y·c·(−2·n_in)`，随后 `n = −n_in`；
2. 反向传递用**负厚度** `y += (−t_k)·(u/n)`，中间面只做介质切换 `n_out = −n_before(k)`；
3. 第二次反射后 `n` 回到 `+n_after(i)`，再正向追到像面。

**弥散直径** `D = 2·|y_img|`（用边缘光线 py=1 与主光线 py=0 的落点差）。
**强度** `I = R²·(1−R)^(N−2)·η`，`η` 是光瞳通过率（沿 py 采样，检查每面 `|y| ≤ 半口径`）。

**排序要用"相对峰值照度"而不是总通量**：`I_rel = I / D²`，再乘光源亮度比。
只看总通量会把"糊成大光斑"和"锐利小亮点"排成一样，而后者才是刺眼的。


### 路线 C：非序列杂散光（有结构才做）

必需输入：**机械 STEP 模型**（镜筒、隔圈、压圈、Sensor 腔）。
表面属性：ABg / Harvey BSDF + 吸收 + 黑漆；光源离轴 0~90° 扫描；
输出 **PST 曲线**（点源透过率）。Zemax 在复杂结构下效率偏低，工程上常上 FRED / LightTools。

## 4. 判据对照

| 项 | 阈值 | 说明 |
|---|---|---|
| GISET | < 1e-3（车载常用），< 1e-4（严格） | 鬼影照度/主像照度 |
| 鬼影离像面距离 | 越大越好 | 远离像面 → 弥散开 → 不刺眼 |
| PST（离轴 10°~30°） | 车载常要求 < 1e-4 ~ 1e-5 | 强光源抑制能力 |
| Veiling glare | < 3% | 大面积杂光的整体对比度损失 |

## 5. 本工具链入口（临时）

会话启动时 MCP 工具表已锁定，新增工具/参数不生效。当前鬼影分析挂在：

```
get_image_quality(wave = -1)   →  path_analysis（鬼影路径分析）
```

- `wave >= 0` 仍是正常像质查询，`wave = -1` 走鬼影。
- 无 ZRD 时返回 `GetSettings=None`（Path Analysis 在拿到光线数据库前不暴露设置口）。
- **MCP 重启后应拆成独立工具 `get_ghost_analysis(zrd, min_flux)`。**

## 6. 常见坑

1. **把 Path Analysis 当成 Ghost Focus Generator** —— 前者要 ZRD，后者不存在于本版，
   看到 `GetSettings returned None` 就是这条。
2. **没有镀膜数据就出数** —— 用 4%（未镀膜）还是 0.3%（AR）差一个量级，结论会完全反过来。
3. **只按反射率排序** —— 最强反射的那两个面不一定最危险，还要看鬼影是否落在像面附近。
4. **胶合面也要算** —— 胶合面两边折射率差小、反射弱，但数量多，会叠出弱鬼影带。
5. **非球面对鬼影的影响** —— 会把鬼影能量摊开，看起来"消失"，实际是弥散成背景，PST 会变差。
6. **顺序模式做不了杂散光** —— 光线不会打到镜筒内壁，必须 NSC/混合。

## 7. 与其它 skill 的分工

| 需要什么 | 看哪里 |
|---|---|
| 详细公式、判据推导、NSC 建模清单 | `references/ghost-analysis-methods.md` |
| 面型/口径/净空、挡光判断 | `zemax-ADAS-skill` |
| 非球面面型对散射的影响 | `zemax-asphere-skill` |
| 公差与良率 | `zemax-tolerance-skill` |
| 热离焦、调焦行程 | `zemax-athermal-skill` |
