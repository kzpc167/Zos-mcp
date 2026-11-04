---
name: zemax-asphere-skill
description: 'Zemax 非球面设计全流程：k 受控优化、A4/A6 交替固定两段法、反曲（斜率反号/曲率反号）的判定与消除、反曲点精确求解、通光口径 vs 物理口径、非球面度（BFS 偏离）、斜率角与局部曲率、边缘厚度与 MTF 取舍、可制造性验收。Use when: 优化圆锥系数 k、释放/冻结 A4 A6、k 越界、非球面反曲或拐点、矢高图看到反曲、边缘斜率过陡、非球面度超差、半口径虚大、弯曲因子 B 过大、仅放开单片变量做局部优化、SUMM/DIFF 不生效、MTF 与面型冲突。关键词：圆锥系数、Conic Constant、COVA、CVVA、CVGT、A4、A6、偶次非球面、矢高、斜率、曲率、反曲、拐点、BFS、非球面度、通光口径、REAY、SDRV、局部优化。'
---

# 非球面设计规程（k / A4 / 反曲 / 可制造性）

> 适用：已有一版可用设计，需要在**不破坏 MTF** 的前提下受控地放开非球面 k / A4，并把面型、边缘厚度、弯曲因子一起验收。
> 全部操作经 `mcp__zemax-opticstudio__*`；COM 调用**严格串行**（一次一条消息）。

## 0. 绝对规则（违反即回退）

1. **k 优化阶段只放 k。** A4、A6、A8… 必须 `make_variable(param="A4", variable=false)` 显式固定；"没动它"不等于"不是变量"。
2. **A4 只在 k 收敛且落在边界内之后才允许释放。** 释放 A4 时 A6 及以上仍固定；**严禁 k 与 A4 及以上同时处于变量状态**。
3. **k 必须有硬边界。** 用 `COVA` 读取 k，再用 `OPGT`/`OPLT` 夹住；软 target 会被 MTF/OPDM 权重压穿，不可作为边界。
4. **每轮优化后必须做面型检查。** 输出边缘矢高、边缘斜率、最大斜率、**反曲点位置**、曲率是否变号；**斜率变号 = 反曲，直接判不合格**；同时必须给出「反曲点 − 通光半径」的余量，贴线（<5%）按不合格处理（实测出现过余量只剩 0.40 mm、9% 的情况）。`z''` 变号 = 拐点，必须显式报告位置并评估抛光风险。
5. **只放开允许的变量。** 微调阶段先把其余全部变量逐个固定（本工具链没有"全部冻结"按钮，只有逐项 `make_variable`）。
6. **只用局部优化（DLS/OD）。** 未获授权不得跑 Hammer/全局搜索。
7. **反曲不能靠 MFE 操作数消除，只能改面型参数。** 面斜率在评价函数里读不出来（`SDRV`/`SSAG` 的参数单元格写不进，见 §6）；唯一可用的间接护栏是先把 A4/A6 固定，再用 `CVGT`/`CVLT` 卡住顶点曲率上下限（§3.7）。

## 1. 本工具链实测的操作数语义

| 操作数 | 参数 | 含义 | 实测/注意 |
|---|---|---|---|
| `COVA` | `Int1=面号` | **圆锥常数 k** | 已验证：面 1 返回 −16.966，与 k 一致 |
| `CVVA` | `Int1=面号` | 曲率 c = 1/R | 面 9 返回 −0.01597（R=−62.6） |
| `DIFF` | `Param1=行A, Param2=行B` | 值 = A − B | **MF 里计入，但 DLS 不求导**，不能驱动优化 |
| `SUMM` | `Param1=行A, Param2=行B` | 值 = A + B | 同上，**DLS 忽略其梯度** |
| `OPGT` | `Int1=被引用行号` | 值必须 > target | 软惩罚；权重不足时会被更强项压穿 |
| `OPLT` | `Int1=被引用行号` | 值必须 < target | 同上 |
| `MTFT/MTFS` | `Int1=采样, Int2=波长, Hx=视场号(1-based), Hy=频率` | MTF | `Hx` 是视场号，不是归一化 Hx |
| `MNEG` | `Int1=i, Int2=i` | 元件 i 的边缘厚度 | 目标值要按真实 ET 定义留余量 |

**曲率与弯曲因子**：

```
c1 = 1/R1, c2 = 1/R2
B  = (R2 + R1) / (R2 - R1) = (c1 + c2) / (c1 - c2)
```

- 降 |B| 的物理动作是**改变弯曲**（c1 + c2），不是改变光焦度（c1 − c2）。
- 保持 c1 − c2 不变、把 c1 + c2 拉向 0，可在不改变薄透镜光焦度的前提下减小 |B|。

## 2. 标准流程

```
S1  基线：get_system_info + get_first_order_data + get_mtf + check_manufacturability
    记录每面 R / k / A4 / A6、EFTL、边缘厚度、B、120 lp/mm 各视场 MTF。
S2  固定 A4/A6：make_variable(A4=false, A6=false) ×首末片
S3  加 k 约束：
      add_operand(COVA, int1=surf, weight=0)        # 监视行
      add_operand(OPGT, int1=<COVA行>, target=-1.95, weight=100~10000)
      add_operand(OPLT, int1=<COVA行>, target= 0.95, weight=100~10000)
    目标区间按需求内缩（要求 [−2,1] 时用 [−1.95,0.95] 留余量）。
S4  只放 k：make_variable(param="conic", variable=true) ×首末片
S5  run_optimization(DLS, Automatic)
S6  读回：get_operands 查 COVA 行的 k；若越界，先加大 OPGT/OPLT 权重或内缩 target。
S7  面型检查（见 §3）。不合格 → 调整 target/权重或回退，不得进入 S8。
S8  k 收敛后才允许释放 A4。**推荐分两步走（§3.7 B）**：
    S8a  固定 A4、放开 A6 → DLS → 检查反曲（让 A6 单独去补面形）
    S8b  固定 A6、放开 A4 → DLS → 保持不反曲的前提下把 MTF 拉回来
    S8c  两个都固定，把当前值锁成设计值
    每步都重复 S6/S7；出现斜率反号就回退上一步、把该系数往可行方向收。
S9  反曲护栏（可选）：A4/A6 固定后，按 §3.7 C 解出临界曲率，
    加 CVVA(监视) + CVGT/CVLT(约束) 卡住顶点曲率；同时用 REAY 监视通光半径。
```

**边界权重经验**：k 越界 0.06 时，权重 100 可以把 k 拉回；越界 0.0004 时权重 100 完全无效，需 10000。越界越小，权重越要大，且优先用原生约束而不是复合操作数。

## 3. 面型检查（必做）

### 3.1 偶次非球面公式与导数

```
t(r)   = 1 − (1+k)·c²r²            c = 1/R
z(r)   = c·r²/(1+√t) + A4·r⁴ + A6·r⁶
z'(r)  = c·r/√t      + 4·A4·r³ + 6·A6·r⁵
z''(r) = c/t^1.5     + 12·A4·r² + 30·A6·r⁴
```

用 `c=1/R` 而不是 `r²/R²`：R 变号时不容易写错。

### 3.2 两种"反曲"必须分开报

| 名称 | 判据 | 后果 |
|---|---|---|
| **斜率反号**（真反曲） | `z'(r)` 在口径内变号，`z'=0` 的点即反曲点 | 面形边缘下翻。抛光模贴不上、模压脱模崩边，**直接判不合格** |
| **曲率反号**（拐点） | `z''(r)` 变号 | 面形由凸转凹，局部曲率半径穿过 ∞。斜率不变号、追迹正常，但抛光会在该半径处留中频环带、干涉图明暗反转 |

两者不同步：z′ 变号必然先经过 z″ 变号；但 z″ 变号不一定发展到 z′ 变号。**只报"无反曲"而漏掉拐点是常见错误。**

实测演进链（15 mm F/1.4，L1 前表面，通光 6.44 mm）：

| 状态 | k | A4 | z′=0 | z″=0 | 判定 |
|---|---:|---:|---|---|---|
| 初版 | −1.0 | −9.77e−5 | **6.845（通光内）** | 4.108 | 反曲，不合格 |
| 改 k | −2.0 | −5.63e−5 | 无（全口径） | 5.980 | 斜率不反曲了，拐点仍在通光内 |
| **最终** | −1.0 | **−7.43e−5** | **8.505（通光外 1.94 mm）** | 5.161 | 合格，仅剩拐点 |

### 3.3 反曲点要解出来，不能只靠采样判号

采样只能答"有没有"，给不出余量。用二分求 `z'=0` 的根，再和口径比：

```python
import math
def inflections(R, k, A4, A6, r_max, n=8000):
    c = 1.0/R
    s  = lambda r: math.sqrt(max(1e-12, 1-(1+k)*c*c*r*r))
    z1 = lambda r: c*r/s(r) + 4*A4*r**3 + 6*A6*r**5
    z2 = lambda r: c/s(r)**3 + 12*A4*r**2 + 30*A6*r**4
    def roots(f, hi):
        out = []
        for i in range(1, n):
            a, b = hi*i/n, hi*(i+1)/n
            if f(a)*f(b) < 0:
                lo, hh, fa = a, b, f(a)
                for _ in range(120):
                    m = 0.5*(lo+hh)
                    if fa*f(m) <= 0: hh = m
                    else: lo, fa = m, f(m)
                out.append(0.5*(lo+hh))
        return out
    return roots(z1, r_max*1.6), roots(z2, r_max*1.6)   # 搜到 1.6 倍口径
```

**搜索范围必须放到口径的 1.5~1.6 倍**：只扫到 `r_max` 只会得到"无根"，看不出反曲点其实就差了 0.2 mm。

**k=−1 可闭式解**：此时 √t≡1，`z'(r)/r = c + 4A4·u + 6A6·u²`（u=r²）是二次方程，直接求根，不必数值搜索。

### 3.4 口径：物理半口径 ≠ 通光口径（最容易冤枉面型的坑）

`get_system_info` 的 `semi_diameter` 是**机械/绘图口径**，常远大于实际通光区。实测两片超了 18% 和 65%：

| | semi_diameter | REAY 实测通光半径 | 虚大 |
|---|---:|---:|---:|
| L1 前 | 7.592 | 6.443 | +18% |
| L7 前 | 4.850 | 2.948 | +65% |

读实际通光用 `REAY(surf, wave, Hx, Hy, Px, Py)`，对最大视场取 `Py=±1` 两侧的**最大绝对值**——主光线偏离会让上下边缘不对称，只测一侧会漏：

```
REAY(int1=1, int2=1, hx=0.866, hy=0.499, py=+1, weight=0)  → +4.093
REAY(int1=1, int2=1, hx=0.866, hy=0.499, py=-1, weight=0)  → -6.443   ← 真正最大值
```

**两个口径都要报**：判反曲/像差用通光口径；判加工难度（非球面度、边缘斜率、ET）用物理口径，因为要磨到那么大。

### 3.5 非球面度（相对最佳拟合球 BFS 的最大偏离）

拟合 `z_s(r) = zc + Rb − sign(Rb)·√(Rb²−r²)`：对 Rb 做黄金分割一维搜索、对 zc 做线性最小二乘，取 `max|z−z_s|`。

- 实测：物理口径下两片都 ≈**98 µm**（超 50 µm 线近一倍），按通光口径只有 **47 / 15 µm**。
- **先收 `semi_diameter` 再谈非球面度。** `semi_diameter` 不参与光线追迹，收到「通光 + 0.2~0.3 mm」零代价，却能同时把非球面度、边缘斜率拉回安全区，还顺手把贴边的反曲区从镜片上切掉。

### 3.6 判定表

| 检查 | 判据 | 安全线 | 处理 |
|---|---|---|---|
| 斜率变号 | `z'(r)` 在通光内变号 | 不允许 | **反曲，不合格**，回退改面型 |
| 反曲点余量 | `r_inf − r_ca` | ≥5%（最好 ≥10%） | 贴线即视为不合格 |
| 边缘斜率 | `atan(\|z'(r_edge)\|)` | < 60°（>30° 偏陡需报告） | 收敛或改面型 |
| 曲率变号 | `z''(r)` 变号 | 记录位置 | 在通光内 = 抛光风险，单列说明 |
| 边缘矢高 | `z(r_edge)` | 与厚度/净空一起核 | 供 ET、净空计算 |
| 非球面度 | BFS 最大偏离 | < 50 µm | 超了先收半口径，再改 A4/A6 |

### 3.7 消除反曲的三条路

**A. 改 k（最快，一次到位）**
k<−1（双曲面）让基础项曲率变化更快，能在同一口径下压住负 A4 造成的下翻。实测 k 由 −1 改到 −2，z′=0 从 6.845（通光内）直接消失。代价是改变了整个面形，像质要重跑。

**B. A4/A6 交替固定两段法（推荐，实测有效）**

```
1 固定 A4、放开 A6 → DLS → 得到 z′ 不反号的面型（A6 单独去补）
2 固定 A6、放开 A4 → DLS → 在不反曲的前提下把 MTF 拉回来
```

一次只放一个高阶系数，让它去适配已经钉死的形状。**A4/A6 同时放开时，优化器会用两个系数互相补偿，很容易造出反曲面**——这是"越优化越反曲"的根因。收尾时两个都固定，把当前值锁成设计值。

**C. CVGT/CVLT 顶点曲率护栏（唯一可放进 MFE 的间接约束）**

A4/A6 固定后，反曲点只由顶点曲率 c=1/R 决定：c 越大、R 越小，反曲点越往外。于是卡住 c 的上下限，就等价于卡住反曲点：

```
add_operand(CVVA, int1=surf, weight=0)                      # 读 c
add_operand(CVGT, int1=surf, target=c_crit*0.7, weight=100) # c ≥ 下限 → 反曲点在外
```

临界 c 的求法：在 `r = r_ca` 处令 `z'(r)=0` 反解 c，再留 60~70% 裕量。实测面 1 的 c_crit=0.0121（R=82.8），取 0.020（R=50）；面 13 的 c_crit=−0.0587（\|R\|=17.0），取 −0.100（\|R\|=10）。

⚠️ **前提是 A4/A6 保持 Fixed。** 一旦放开，阈值失效且不会报任何错——这是这套护栏唯一的失效模式。

## 4. 冲突与不可行时的决策

当 MTF 与面型/厚度冲突时，按顺序判断：

1. **先看边缘 MTF 余量。** 若最差视场 T 只剩 <0.01，任何面型改动都会把它压到 0.4 以下——这是硬冲突，不是优化没跑够。
2. **检查限制范围。** 用户只允许放某片 3 个变量时，不要偷偷放开别的面；把"不可行"用量化数据说明。
3. **不要用软 target 硬顶。** 复合操作数（SUMM/DIFF）无梯度；软权重会被 MTF/OPDM 压穿。
4. **给出可选方案**：
   - 放开相邻镜片半径/厚度（扩大自由度）；
   - 接受最差视场 MTF 下降（例如从 0.40 降到 0.37）；
   - 更换材料 / 增加校正面（若结构允许）。

**B 因子案例结论（已实测）**：某 15 mm F/1.4 系统中 L5 的 B=−9.5，仅放开 L5 的 R1/R2/CT 做局部 DLS，B 无法实质下降；扫描显示 B=−9.3 时边缘视场 T MTF=0.4017，B=−9.2 时 0.3982（失败），B=−8.8 时 0.369（失败）。即：**极端 B 是当前结构满足边缘 MTF 的最优形态**，2% 以内的改善是噪声级别。

## 5. 验收清单

每轮优化后逐项执行：

| # | 检查 | 命令 | 判据 |
|---|---|---|---|
| 1 | k 值 | `get_operands` 读 COVA 行 | 在 [−2.0, 1.0]（或指定区间）内 |
| 2 | 变量清单 | `get_system_info` 的 `solve` | 只有被授权的变量为 2 |
| 3 | 面型 | §3.3 解析计算 | 斜率不变号；**反曲点余量（r_inf − r_ca）≥5%**；记录边缘斜率、拐点位置 |
| 3b | 非球面度 | §3.5 BFS | 通光口径下最大偏离 < 50 µm；物理口径另报 |
| 3c | 通光口径 | `REAY` 两侧 Py=±1 | 与 `semi_diameter` 对比，虚大 >20% 就建议收口径 |
| 4 | MTF | `get_mtf(frequency=120)` | 要求视场 T/S 全部 > 阈值 |
| 5 | 边缘厚度 | `check_manufacturability` | ET ≥ 要求值；B 过大单列警告 |
| 6 | 一阶量 | `get_first_order_data` | EFFL 漂移在允许范围 |

## 6. 已知坑（本工具链实测）

| 坑 | 现象 | 处理 |
|---|---|---|
| `get_image_quality` 离轴视场 | 对 field 4/5 固定 `Hx=0`，读到的是子午点而非对角点 | 对角视场一律用 `get_mtf` / `get_fft_mtf_vs_field` |
| 默认 MF 重建 | `set_default_merit_function(start_at=…)` 后，前面的 MTF 行 Hx 可能被重置为 1 | 重建后逐行读回 `get_operands`，必要时重新写 `edit_operand(hx=…)` |
| 打开同路径备份 | `open_file` 打开当前已激活的同一路径时不重新加载，且可能把内存状态写回该文件 | 恢复前先复制成**新文件名**，再打开副本 |
| `SUMM`/`DIFF` | 评价函数里贡献很大，但 DLS 不收敛/不移动 | 不用于驱动优化；用原生 `CVGT/CVLT` 或手动扫描 |
| `OPGT/OPLT` 软惩罚 | 小越界（<0.001）时权重 100 被 MTF 压穿 | 加大到 10000，或改用原生硬约束 |
| A4 猛收 | 从 −6e−5 直接改到 −1.5e−6 再 DLS，会跳到劣解（MTF 0.28~0.33） | 不要大跳；从可行边界逐步逼近，或接受原解 |
| EFFL 漂移 | 只改 L5 R1/R2/CT，EFFL 可从 14.91 漂到 14.83 | 验收时单列 EFFL；必要时加回 EFFL 权重或微调 CT |
| **`SDRV` 读面斜率** | Param2 写入 `read_back ''`；Py 列报 `Expected Integer, got 'Double'`；值恒为 0 | 面斜率在 MFE 层**读不到**。改用解析式（§3.3）；不要反复花时间试 |
| **`SSAG` 读矢高** | int2 写 5 读回 1（改不动），值恒为 0 | 同上，不能用来做差分求斜率 |
| **`PARM` 读 A4/A6** | 该操作数在本版本不存在（`add_operand` 直接报"未知操作数类型"） | 系数只能从 `get_system_info` 的 `asphere_coefficients` 读 |
| **`semi_diameter` 虚大** | 常比实际通光大 18%~65%，使非球面度、边缘斜率、ET 判定全部虚高 | 用 `REAY` 读真实通光，两个口径分开报（§3.4） |
| **反曲误判为"没有"** | 只扫到 `r_max`，反曲点恰好在口径外 0.2 mm 就判"无根" | 搜索范围放到 1.6 倍口径（§3.3） |

## 7. 最小命令序列（MCP）

```text
get_system_info
get_first_order_data
get_mtf(frequency=120, wave=0)
check_manufacturability

make_variable(surface=1, param="A4", variable=false)
make_variable(surface=1, param="A6", variable=false)
make_variable(surface=13, param="A4", variable=false)
make_variable(surface=13, param="A6", variable=false)

add_operand("COVA", int1=1,  weight=0)
add_operand("OPGT", int1=<COVA1行>, target=-1.95, weight=100)
add_operand("OPLT", int1=<COVA1行>, target= 0.95, weight=100)
add_operand("COVA", int1=13, weight=0)
add_operand("OPGT", int1=<COVA13行>, target=-1.95, weight=100)
add_operand("OPLT", int1=<COVA13行>, target= 0.95, weight=100)

make_variable(surface=1, param="conic", variable=true)
make_variable(surface=13, param="conic", variable=true)
run_optimization(algorithm="DLS")
get_operands            # 读 COVA 行，确认 k 在界内
# §3 面型检查通过后，才允许：
make_variable(surface=1, param="A4", variable=true)
make_variable(surface=13, param="A4", variable=true)
run_optimization(algorithm="DLS")
get_operands / get_mtf / check_manufacturability / §3 检查
```
