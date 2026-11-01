# zosmcp 无热化工具链：修复记录与 ZOS-API 真相

> **状态：2026-10-31 已修复并实测通过**（此前 5 个工具里 4 个是空壳）。
> 本文件记录「修了什么 + 踩到的 API 真相」，避免下次重新猜。

---

## 一、修复前后对照

| 工具 | 修复前 | **修复后（已实测）** |
|---|---|---|
| `set_temperature_configs` | 不创建 MCE，只把温度塞进返回 dict | **真建组态**：`AddConfiguration(False)` + TEMP 操作数 + read_back 校验 + MCE 回读 |
| `set_thermal_glass_tce` | try 块里只有注释，TCE/dn-dT 恒为 null | **GTCE 操作数实测**读 8 片真实 TCE（5.8~8.2 ppm/℃），读完删临时行 |
| `add_thermal_pickup_solve` | 猜 SolveType ID 18~21，且**挂在错误的单元格上**（LDE 而非 MCE）| **重构为 MCE 级**：建 CRVT/THIC 操作数 + 组态 2..N 挂 ThermalPickup(id=30) |
| `optimize_athermal` | 只是 `run_optimization` 包装 | 真读全温 BFL 前后对比 + 组态数校验 + 漂移改善判定 |
| `get_thermal_defocus` | 温度硬编码 `[-40,25,85]`，从不切组态 | 温度从 MCE 读 + `SetCurrentConfiguration(n)` 真切 + **假阳性检测** |

---

## 二、ZOS-API 关键事实（都是实测出来的，别再猜）

### 2.1 MCE 温度组态

```python
# 枚举值
MultiConfigOperandType_TEMP = 94     # constants 里能找到这个名字
MultiConfigOperandType_CRVT / THIC   # 曲率 / 厚度，Param1 = 面号

# 组态数
mce.AddConfiguration(False)          # 参数是 withPickup，必须传，不能无参
mce.DeleteConfiguration(index)

# 操作数
mce.AddOperand()                     # 追加到末尾
mce.InsertNewOperandAt(row)
op.ChangeType(94)                    # 设成 TEMP
op.Param1 = surface_number           # CRVT/THIC 用
op.GetOperandCell(config).DoubleValue = value
```

### 2.2 ⚠️ 切组态是**方法**不是属性

```python
mce.SetCurrentConfiguration(2)      # ✅ 正确
mce.CurrentConfiguration = 2        # ❌ AttributeError：IMultiConfigEditor 没这个属性
```

这一条坑了很久：官方 .NET 文档写的是属性 `CurrentConfiguration`，
但 win32com 生成的 `IMultiConfigEditor` 包装里**只有 `SetCurrentConfiguration(n)` 方法**。
读当前组态也没有对应属性，只能自己记。

### 2.3 ⚠️ Thermal Pickup 挂在 **MCE 单元格**，不是 LDE 单元格

这是最容易搞错的地方。Ansys 官方 Example 18「Make Thermal」的正确姿势：

```python
# 1) MCE 里建 CRVT/THIC 操作数，Param1 = 面号
op = mce.GetOperandAt(row)          # Type = THIC, Param1 = 面号
# 2) 组态 1 放基准值
op.GetOperandCell(1).DoubleValue = thickness
# 3) 组态 2..N 的同一操作数单元格挂 solve
solve = op.GetOperandCell(2).CreateSolveType(30)   # 30 = SolveType.ThermalPickup
solve._S_ThermalPickup.Configuration = 1           # 跟随组态1，不是 TCE！
op.GetOperandCell(2).SetSolveData(solve)
# 4) 全局开关
system.SystemData.Environment.AdjustIndexToEnvironment = True
```

**关键认知**：
- solve 参数是 **`Configuration`（跟随哪个组态）**，**不是 TCE**。
  膨胀量由玻璃材料自身的 TCE + 系统温度决定，人为写 TCE 是错的。
- **`tce` 这个入参是伪需求**，保留只为兼容旧调用，实际不生效。

### 2.4 ⚠️ ThermalPickup 的枚举值 = 30，但读不出名字

```python
solve = cell.CreateSolveType(30)
solve.Type                # → 30（数字）或空字符串，win32com 读不出枚举名
```

**判据不要用 Type 名称**（读回是数字或空），而要看 solve 对象是否暴露 `_S_ThermalPickup` 子接口：

```python
if getattr(solve, "_S_ThermalPickup", None) is not None:
    # 这就是 Thermal Pickup
```

同理，`dir(win32com.constants)` 里**没有任何 `SolveType_*` 常量**（连 "solve" 都不含），
所以"从常量表找 SolveType_ThermalPickup"这条路根本走不通，只能 ID 扫描 + 子接口判断。

### 2.5 `DNDT` 操作数**不存在**

想读 dn/dT 会发现 `add_operand("DNDT")` 报「未知操作数类型」。Zemax 没有这个操作数。
- 玻璃 TCE 有：**`GTCE`**（返回值单位 ppm/℃，实测 5.8~8.2，合理）
- dn/dT 无操作数，只能：OpticStudio GUI 的 `Analyze → Materials` 窗口查，
  或建两个温度组态后读同一面的 `INDX` 差值除以 ΔT。

### 2.6 `SystemData.TemperaturePressure` 读不到

`_get_current_temperature()` 返回 None（API 版本差异）。
不影响 MCE 温度组态——温度真源是 MCE 的 TEMP 操作数，不依赖这个。

---

## 三、实测验证数据（车载 15mm F/1.4）

**玻璃 TCE（GTCE 实测）**：

| 玻璃 | 面 | TCE (ppm/℃) |
|---|---:|---:|
| H-ZLAF68N | 1 | 5.8 |
| H-ZLAF68C | 3 | 7.0 |
| ZF51 | 6 | 8.2 |
| H-LAK53A | 7 | 6.1 |
| H-ZLAF68B | 9 | 6.8 |
| H-ZLAF78B | 11 | 6.8 |
| H-LAF50B | 13 | 5.8 |
| H-K9L | 15 | 7.6 |

**热拾取正确性验证**（只给面 1 厚度挂 Thermal Pickup）：

```
面1 厚度 2.5945 mm，玻璃 TCE 5.8 ppm/℃
理论: ΔL = 2.5945 × 5.8e-6 × ΔT
  ΔT = -65℃ (-40℃) → -0.978 µm
  ΔT = +60℃ ( 85℃) → +0.903 µm
实测: -0.978 µm / +0.903 µm     ✅ 逐位吻合
```

**这条验证说明**：MCE 组态 + 热拾取 + 温度切换整条链路是通的，
数值不是"看起来对"，而是与手算一致。

---

## 四、仍存在的限制

1. **空气间隔的镜筒膨胀**：Thermal Pickup 让单元格跟随组态 1 按**材料 TCE** 缩放，
   而空气间隔应跟镜筒（铝 23.1 ppm）。目前工具只对 LDE 里的玻璃面/厚度做，
   空气间隔要单独处理——可用 MCE 的 THIC 操作数对空气层手写不同的膨胀，
   或建一个"虚拟镜筒面"作参考。**这是下一步要补的**。
2. **`optimize_athermal` 的多组态加权**：目前依赖 MFE 操作数 Config 列设为 0
   （所有组态共用）才能生效；工具只做校验和提示，不自动改 MFE 的 Config 列。
3. **dn/dT** 仍无工具读取（见 2.5）。

---

## 五、通用教训（复用到其它工具）

**工具文档写得越详细，越要验证它真的做了这件事。**

这 5 个工具的描述里连公式 `value(T) = value(T0) * [1 + TCE * (T - T0)]` 都写了，
看起来像成熟功能，实际函数体是空注释。

**验证套路**：
1. 调一次，看**数值**是否合理（不是看 `ok`）
2. 数值全 null / 全相同 / 恰好等于别处已知值 → 三项任一命中，判为坏
3. 去 `tools.py` 搜函数名读实现，20 秒看出是真空壳还是参数错
4. 修的时候**先查官方 Example**（Ansys Developer Portal 的 ZOS-API Examples），
   比自己猜 API 快得多——这次的 MCE 级 Thermal Pickup 就是从 Example 18 找到的
