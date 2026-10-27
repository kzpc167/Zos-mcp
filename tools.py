"""Zemax 工具定义与实现 — 供 AI Agent 调用."""

import json
import math
import shutil
import struct
import time
import traceback
import zlib
from datetime import datetime
from pathlib import Path

from zemax_connection import ZemaxConnection
from logger import logger

# 仓库根 = tools.py 所在目录；此前写成 parent.parent，会退到 D:\ 并导致 rglob 全盘扫描
_WORKSPACE_ROOT = Path(__file__).resolve().parent
_IGNORED_PROJECT_DIRS = {".git", ".venv", "__pycache__", "backups", "build", "layouts", "logs"}

# 元件序号圈码（check_interference 等报告里用）
_CIRCLED = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥",
            7: "⑦", 8: "⑧", 9: "⑨", 10: "⑩", 11: "⑪", 12: "⑫"}


def _short_name(name: str) -> str:
    """把 '元件②' → '②'、'光阑(STOP)' → 'STOP'，用于图上紧凑标注。"""
    s = str(name or "")
    if "STOP" in s or "光阑" in s:
        return "STOP"
    return s.replace("元件", "").strip() or s

# ---------------------------------------------------------------------------
#  MCP 工具模式定义（JSON Schema，沿用 OpenAI function-calling 格式）
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": (
                "获取当前光学系统概览：所有表面（编号/类型/曲率半径/厚度/材料/半口径/圆锥系数）、"
                "系统光圈、视场点、波长配置"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_surface",
            "description": "在指定位置插入一个新的标准表面",
            "parameters": {
                "type": "object",
                "properties": {
                    "position": {
                        "type": "integer",
                        "description": "插入位置的表面编号 (0=物面后, N=像面前)",
                    }
                },
                "required": ["position"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_surface",
            "description": (
                "编辑指定表面的属性。只需提供要修改的参数，未提供的保持不变。"
                "radius=1e18 表示平面 (Infinity)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "surface_number": {
                        "type": "integer",
                        "description": "表面编号 (0=物面, 最后一个=像面)",
                    },
                    "radius": {
                        "type": "number",
                        "description": "曲率半径 (mm)，正值凸面朝向物方",
                    },
                    "thickness": {
                        "type": "number",
                        "description": "到下一面的距离 (mm)",
                    },
                    "material": {
                        "type": "string",
                        "description": "玻璃材料名称，如 BK7, N-BK7, SF2, MIRROR 等",
                    },
                    "semi_diameter": {
                        "type": "number",
                        "description": "半口径 (mm)",
                    },
                    "conic": {
                        "type": "number",
                        "description": "圆锥系数 (0=球面, -1=抛物面)",
                    },
                    "comment": {
                        "type": "string",
                        "description": "表面注释",
                    },
                    "is_stop": {
                        "type": "boolean",
                        "description": "是否设为光阑面",
                    },
                },
                "required": ["surface_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_surface",
            "description": "删除指定编号的表面（不能删除物面和像面）",
            "parameters": {
                "type": "object",
                "properties": {
                    "surface_number": {
                        "type": "integer",
                        "description": "要删除的表面编号",
                    }
                },
                "required": ["surface_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_aperture",
            "description": "设置系统光圈类型和数值",
            "parameters": {
                "type": "object",
                "properties": {
                    "aperture_type": {
                        "type": "string",
                        "enum": [
                            "EntrancePupilDiameter",
                            "ImageSpaceFNumber",
                            "ObjectSpaceNA",
                            "FloatByStopSize",
                        ],
                        "description": "光圈类型",
                    },
                    "value": {"type": "number", "description": "光圈值"},
                },
                "required": ["aperture_type", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_fields",
            "description": "设置系统视场（会清除并替换所有现有视场点）",
            "parameters": {
                "type": "object",
                "properties": {
                    "field_type": {
                        "type": "string",
                        "enum": [
                            "Angle",
                            "ObjectHeight",
                            "ParaxialImageHeight",
                            "RealImageHeight",
                        ],
                        "description": "视场类型",
                    },
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number", "description": "X 视场值"},
                                "y": {"type": "number", "description": "Y 视场值"},
                                "weight": {
                                    "type": "number",
                                    "description": "权重 (默认 1.0)",
                                },
                                "vcx": {
                                    "type": "number",
                                    "description": "X 方向渐晕压缩因子 (0~1)，1=无渐晕；0.3 表示拦掉 70% 边缘光线",
                                },
                                "vcy": {
                                    "type": "number",
                                    "description": "Y 方向渐晕压缩因子 (0~1)，1=无渐晕；0.45 表示拦掉 55% 边缘光线",
                                },
                            },
                            "required": ["x", "y"],
                        },
                        "description": "视场点列表",
                    },
                },
                "required": ["field_type", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_wavelengths",
            "description": "设置系统波长（会清除并替换所有现有波长）",
            "parameters": {
                "type": "object",
                "properties": {
                    "wavelengths": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "value": {
                                    "type": "number",
                                    "description": "波长值 (微米)",
                                },
                                "weight": {
                                    "type": "number",
                                    "description": "权重 (默认 1.0)",
                                },
                            },
                            "required": ["value"],
                        },
                        "description": "波长列表",
                    },
                    "preset": {
                        "type": "string",
                        "enum": ["d_light", "C_light", "F_light", "FdC_Visible"],
                        "description": "使用预设波长 (设置此项时忽略 wavelengths)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_variable",
            "description": "将指定表面的某个参数设为变量 (可优化) 或固定。param=material 时把玻璃设为替代玻璃(Substitute)变量，可用 catalog 指定搜索的玻璃库目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "surface_number": {
                        "type": "integer",
                        "description": "表面编号",
                    },
                    "param": {
                        "type": "string",
                        "enum": ["radius", "thickness", "conic", "material"],
                        "description": "参数名称",
                    },
                    "catalog": {
                        "type": "string",
                        "description": "仅 param=material 时使用：替代玻璃搜索的玻璃库目录名(如 SCHOTT/CDGM/OHARA)。不提供则用系统当前已加载目录。",
                    },
                    "variable": {
                        "type": "boolean",
                        "description": "true=变量, false=固定",
                    },
                },
                "required": ["surface_number", "param", "variable"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_model_glass",
            "description": (
                "把某面的玻璃替换为『模型玻璃(Model Glass)』，可选把折射率 nd / 阿贝数 vd / 偏色散 dPgF 设为优化变量。"
                "对应教材里『将透镜材料改为模型玻璃并增加为变量』这一步。不传 index/abbe 时沿用当前玻璃的 nd/vd。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "surface_number": {"type": "integer", "description": "表面编号"},
                    "index": {"type": "number", "description": "模型玻璃折射率 nd（不填则用当前玻璃值）"},
                    "abbe": {"type": "number", "description": "模型玻璃阿贝数 vd（不填则用当前玻璃值）"},
                    "vary_index": {"type": "boolean", "description": "nd 是否作为变量 (默认 true)"},
                    "vary_abbe": {"type": "boolean", "description": "vd 是否作为变量 (默认 true)"},
                    "dpgf": {"type": "number", "description": "偏色散 dPgF（可选）"},
                    "vary_dpgf": {"type": "boolean", "description": "dPgF 是否作为变量 (默认 false)"},
                },
                "required": ["surface_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_solve",
            "description": (
                "设置表面单元格的 Solve。solve_type=marginal_ray_height 表示'边缘光线高度'求解"
                "（教材里令像平面自动定位、使轴上边缘光线交高为零：height=0, pupil_zone=0）；"
                "也支持 fixed / variable。param 指定作用在 radius/thickness/conic 上。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "surface_number": {"type": "integer", "description": "表面编号"},
                    "solve_type": {
                        "type": "string",
                        "enum": ["marginal_ray_height", "fixed", "variable"],
                        "description": "solve 类型 (默认 marginal_ray_height)",
                    },
                    "param": {
                        "type": "string",
                        "enum": ["radius", "thickness", "conic"],
                        "description": "作用位置 (默认 thickness)",
                    },
                    "height": {"type": "number", "description": "边缘光线高度目标 (默认 0)"},
                    "pupil_zone": {"type": "number", "description": "光瞳带 (默认 0 = 边缘光线)"},
                },
                "required": ["surface_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_optimization",
            "description": "运行优化（DLS=阻尼最小二乘, OD=正交下降, Hammer=锤优化/全局搜索，用于替代玻璃和全局寻优）。Hammer 是持续运行型优化，用 duration_seconds 控制运行时长。",
            "parameters": {
                "type": "object",
                "properties": {
                    "algorithm": {
                        "type": "string",
                        "enum": ["DLS", "OD", "Hammer"],
                        "description": "DLS=阻尼最小二乘, OD=正交下降, Hammer=锤优化(替代玻璃/全局搜索) (默认 DLS)",
                    },
                    "duration_seconds": {
                        "type": "integer",
                        "description": "仅 Hammer 使用：持续运行时长(秒)。Hammer 是持续搜索型优化，值越大搜索越充分(默认 30)。",
                    },
                    "cycles": {
                        "type": "string",
                        "enum": [
                            "Automatic",
                            "Fixed_1",
                            "Fixed_5",
                            "Fixed_10",
                            "Fixed_50",
                        ],
                        "description": "循环次数 (默认 Automatic)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_hammer",
            "description": "启动 Hammer 锤优化并持续运行（界面保持打开、不关闭）。返回初始评价函数值。之后可用 get_hammer_status 定期读 MF、stop_hammer 停止。用于替代玻璃/全局寻优的长时间持续优化。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hammer_status",
            "description": "读取 Hammer 当前评价函数值（不停止、不关闭界面）。返回当前 MF、起始 MF 和下降量。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_hammer",
            "description": "停止 Hammer 优化并关闭界面。返回起始 MF、最终 MF 和总下降量。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quick_focus",
            "description": "运行快速聚焦 (调整像面位置使 RMS 光斑最小)",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_merit_function",
            "description": "获取当前评价函数值",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "new_file",
            "description": "新建一个空的光学系统。默认先保存当前系统，并由自动备份机制保护当前文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "save_first": {
                        "type": "boolean",
                        "description": "新建前是否先保存当前系统，默认 true",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_file",
            "description": "保存当前光学系统",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "另存为的完整路径 (.zmx)，不提供则保存到当前路径",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_file",
            "description": "打开指定的 .zmx 光学系统文件。默认先保存当前系统，并由自动备份机制保护当前文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": ".zmx 文件的完整路径",
                    },
                    "save_first": {
                        "type": "boolean",
                        "description": "打开新文件前是否先保存当前系统，默认 true",
                    }
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_context",
            "description": "获取当前工程上下文：当前 .zmx 文件、备份/布局目录、工作区内可用设计文件列表。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_backups",
            "description": "列出当前系统同目录 backups/ 下的自动备份文件，按修改时间倒序排列。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_surface_type",
            "description": "设置表面类型 (如 Standard, EvenAsphere, Paraxial 等)",
            "parameters": {
                "type": "object",
                "properties": {
                    "surface_number": {
                        "type": "integer",
                        "description": "表面编号",
                    },
                    "surface_type": {
                        "type": "string",
                        "description": "表面类型名称，如 Standard, EvenAsphere, Paraxial, IdealLens 等",
                    },
                },
                "required": ["surface_number", "surface_type"],
            },
        },
    },
    # ----- 评价函数编辑工具 -----
    {
        "type": "function",
        "function": {
            "name": "set_default_merit_function",
            "description": (
                "使用序列优化向导设置默认评价函数（会覆盖从 start_at 行开始的内容）。"
                "这是设置标准成像评价函数最快捷的方式。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "opt_type": {
                        "type": "integer",
                        "description": "优化类型: 0=RMS(均方根), 1=PTV(峰谷值)",
                    },
                    "data": {
                        "type": "integer",
                        "description": "优化数据: 0=波前(Wavefront), 1=光斑半径(SpotRadius), 2=光斑X, 3=光斑Y, 4=角度空间光斑",
                    },
                    "reference": {
                        "type": "integer",
                        "description": "参考: 0=质心(Centroid), 1=主光线(ChiefRay), 2=无参考",
                    },
                    "rings": {
                        "type": "integer",
                        "description": "环数: 0=1, 1=2, 2=3, 3=4, 4=5, 5=6",
                    },
                    "arms": {
                        "type": "integer",
                        "description": "臂数: 0=6, 1=8, 2=10, 3=12",
                    },
                    "use_glass_thickness": {
                        "type": "boolean",
                        "description": "是否添加玻璃厚度约束",
                    },
                    "glass_min": {"type": "number", "description": "玻璃最小中心厚度(mm)"},
                    "glass_max": {"type": "number", "description": "玻璃最大中心厚度(mm)"},
                    "use_air_thickness": {
                        "type": "boolean",
                        "description": "是否添加空气间隔约束",
                    },
                    "air_min": {"type": "number", "description": "空气最小间隔(mm)"},
                    "air_max": {"type": "number", "description": "空气最大间隔(mm)"},
                    "overall_weight": {"type": "number", "description": "整体权重 (默认 1.0)"},
                    "start_at": {
                        "type": "integer",
                        "description": "从MFE第几行开始覆盖 (默认 1=全部覆盖)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_operand",
            "description": (
                "向评价函数编辑器(MFE)添加一个操作数行。"
                "常用操作数: "
                "EFFL(有效焦距,Int1=波长号), "
                "EFLY(Y方向焦距), "
                "BFL(后焦距), "
                "TOTR(总长,Int1=起始面,Int2=终止面), "
                "TTHI(总玻璃厚度,Int1=起始面,Int2=终止面), "
                "MNCT(最小中心厚度), MXCT(最大中心厚度), "
                "MNEG(最小边缘厚度), MXEG(最大边缘厚度), "
                "DIMX(最大畸变%), AXCL(轴向色差), LACL(横向色差), "
                "PETC(Petzval曲率), OPTH(光程差)。"
                "weight=0 表示仅监视不参与优化。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operand_type": {
                        "type": "string",
                        "description": "操作数类型名称(4字母代码)，如 EFFL, BFL, TOTR 等",
                    },
                    "insert_at": {
                        "type": "integer",
                        "description": "可选：插入到指定 MFE 行号；不提供则追加到末尾。用于把自定义约束放在默认评价函数块之前。",
                    },
                    "target": {"type": "number", "description": "目标值"},
                    "weight": {
                        "type": "number",
                        "description": "权重 (0=仅监视, >0=参与优化)。默认 1.0",
                    },
                    "int1": {
                        "type": "integer",
                        "description": "整数参数1 (含义取决于操作数类型，常为表面号或波长号，0=默认)",
                    },
                    "int2": {
                        "type": "integer",
                        "description": "整数参数2 (含义取决于操作数类型，常为波长号或视场号，0=默认)",
                    },
                    "hx": {"type": "number", "description": "Hx/Param3 单元格值"},
                    "hy": {"type": "number", "description": "Hy/Param4 单元格值"},
                    "px": {"type": "number", "description": "Px/Param5 单元格值"},
                    "py": {"type": "number", "description": "Py/Param6 单元格值"},
                    "ex": {"type": "number", "description": "Ex/Param7 单元格值"},
                    "ey": {"type": "number", "description": "Ey/Param8 单元格值"},
                    "param1": {"type": "number", "description": "通用 Param1/Int1 单元格值，会覆盖 int1"},
                    "param2": {"type": "number", "description": "通用 Param2/Int2 单元格值，会覆盖 int2"},
                    "param3": {"type": "number", "description": "通用 Param3/Hx 单元格值，会覆盖 hx"},
                    "param4": {"type": "number", "description": "通用 Param4/Hy 单元格值，会覆盖 hy"},
                    "param5": {"type": "number", "description": "通用 Param5/Px 单元格值，会覆盖 px"},
                    "param6": {"type": "number", "description": "通用 Param6/Py 单元格值，会覆盖 py"},
                    "param7": {"type": "number", "description": "通用 Param7/Ex 单元格值，会覆盖 ex"},
                    "param8": {"type": "number", "description": "通用 Param8/Ey 单元格值，会覆盖 ey"},
                },
                "required": ["operand_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_operand",
            "description": "修改 MFE 中已有操作数行的任意单元格参数、目标值或权重。",
            "parameters": {
                "type": "object",
                "properties": {
                    "row": {"type": "integer", "description": "MFE 行号，从 1 开始"},
                    "operand_type": {"type": "string", "description": "可选：新的操作数类型，如 REAY"},
                    "target": {"type": "number", "description": "可选：目标值"},
                    "weight": {"type": "number", "description": "可选：权重"},
                    "int1": {"type": "integer", "description": "可选：Int1/Param1"},
                    "int2": {"type": "integer", "description": "可选：Int2/Param2"},
                    "hx": {"type": "number", "description": "可选：Hx/Param3"},
                    "hy": {"type": "number", "description": "可选：Hy/Param4"},
                    "px": {"type": "number", "description": "可选：Px/Param5"},
                    "py": {"type": "number", "description": "可选：Py/Param6"},
                    "ex": {"type": "number", "description": "可选：Ex/Param7"},
                    "ey": {"type": "number", "description": "可选：Ey/Param8"},
                    "param1": {"type": "number", "description": "可选：通用 Param1"},
                    "param2": {"type": "number", "description": "可选：通用 Param2"},
                    "param3": {"type": "number", "description": "可选：通用 Param3"},
                    "param4": {"type": "number", "description": "可选：通用 Param4"},
                    "param5": {"type": "number", "description": "可选：通用 Param5"},
                    "param6": {"type": "number", "description": "可选：通用 Param6"},
                    "param7": {"type": "number", "description": "可选：通用 Param7"},
                    "param8": {"type": "number", "description": "可选：通用 Param8"},
                },
                "required": ["row"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_operands",
            "description": "清空 MFE 中所有可删除操作数。必须显式传 confirm=true；返回清空后的剩余行数和下一可插入行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirm": {"type": "boolean", "description": "必须为 true 才会清空"},
                },
                "required": ["confirm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_merit_breakdown",
            "description": "按贡献度排序返回 MFE 主导项，用于 MF 异常或优化停滞时定位问题行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "top_n": {"type": "integer", "description": "返回前 N 个贡献项，默认 20"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_operand_block",
            "description": "按 label/ref 原子构建一组 MFE 操作数，自动解析 DIVI/PROD 等行号引用，避免 Agent 猜行号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "operands": {
                        "type": "array",
                        "description": "操作数列表。每项可含 label、operand_type、target、weight、int1/int2 或 int1_ref/int2_ref，以及 hx/hy/px/py/ex/ey。",
                        "items": {"type": "object"},
                    },
                    "insert_at": {"type": "integer", "description": "可选：从指定 MFE 行开始插入；不提供则追加。"},
                    "clear_first": {"type": "boolean", "description": "是否先清空 MFE，默认 false。"},
                },
                "required": ["operands"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_default_merit_function_after_current_block",
            "description": "从当前 MFE 最后一行之后自动生成默认评价函数，避免手算 start_at 覆盖自定义约束块。",
            "parameters": {
                "type": "object",
                "properties": {
                    "opt_type": {"type": "integer", "description": "优化类型: 0=RMS, 1=PTV"},
                    "data": {"type": "integer", "description": "优化数据: 0=波前, 1=光斑半径"},
                    "reference": {"type": "integer", "description": "参考: 0=质心, 1=主光线, 2=无参考"},
                    "rings": {"type": "integer", "description": "环数枚举"},
                    "arms": {"type": "integer", "description": "臂数枚举"},
                    "use_glass_thickness": {"type": "boolean", "description": "是否添加玻璃厚度约束"},
                    "glass_min": {"type": "number", "description": "玻璃最小厚度"},
                    "glass_max": {"type": "number", "description": "玻璃最大厚度"},
                    "use_air_thickness": {"type": "boolean", "description": "是否添加空气厚度约束"},
                    "air_min": {"type": "number", "description": "空气最小厚度"},
                    "air_max": {"type": "number", "description": "空气最大厚度"},
                    "overall_weight": {"type": "number", "description": "整体权重"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ray_aiming_settings",
            "description": "读取当前系统 Ray Aiming / 光线瞄准相关设置；若当前 ZOS-API 版本不暴露该属性，会返回候选探测结果。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_ray_aiming",
            "description": "尝试开启/关闭 Ray Aiming（光线瞄准）。当前版本若不暴露 COM 属性，会返回明确错误和手动处理建议。",
            "parameters": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean", "description": "是否开启光线瞄准"},
                    "mode": {"type": "string", "enum": ["Off", "Paraxial", "Real"], "description": "光线瞄准模式，默认 Paraxial"},
                    "use_cache": {"type": "boolean", "description": "是否尝试启用 Ray Aiming 缓存，默认 true"},
                },
                "required": ["enabled"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_operands",
            "description": "获取评价函数编辑器(MFE)中所有操作数行的详细信息（类型/目标/权重/当前值）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_operands",
            "description": "从评价函数编辑器(MFE)中删除指定操作数行。清空全部请使用 clear_operands(confirm=true)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "rows": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "要删除的行号列表(1-based)。不提供则清除所有操作数",
                    },
                },
                "required": [],
            },
        },
    },
    # ----- 系统分析工具 -----
    {
        "type": "function",
        "function": {
            "name": "get_first_order_data",
            "description": (
                "计算并获取系统一阶光学参数：有效焦距(EFFL)、后焦距(BFL)、总长(TOTR)。"
                "通过在MFE末尾临时插入监视操作数来计算，不影响现有评价函数。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # ----- 玻璃库管理工具 -----
    {
        "type": "function",
        "function": {
            "name": "get_glass_catalogs",
            "description": (
                "获取玻璃库（材料目录）信息：当前使用的目录列表、系统中所有可用的目录列表。"
                "可选：查询某个目录中的所有材料名称。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "catalog": {
                        "type": "string",
                        "description": "要查询材料列表的目录名称（如 SCHOTT, OHARA, HOYA 等）。不提供则只返回目录列表。",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_glass_catalogs",
            "description": (
                "管理系统使用的玻璃库（材料目录）：添加或移除目录。"
                "添加前会检查该目录是否可用，移除前会检查是否正在使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "add": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要添加的目录名称列表，如 [\"SCHOTT\", \"OHARA\"]",
                    },
                    "remove": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要移除的目录名称列表",
                    },
                },
                "required": [],
            },
        },
    },
    # ----- UI 刷新与布局工具 -----
    {
        "type": "function",
        "function": {
            "name": "update_ui",
            "description": (
                "刷新 OpticStudio 图形界面。调用后 GUI 中已打开的编辑器和分析窗口都会更新显示。"
                "在通过 API 修改系统后调用此工具可使 LDE、2D Layout 等窗口同步刷新。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_layout",
            "description": (
                "在 OpticStudio GUI 中打开一个新的 2D 或 3D 布局图窗口，显示当前光学系统结构。"
                "窗口会自动计算并渲染；不提供 export_path 时会自动导出到当前工程 layouts/ 目录并返回路径。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "layout_type": {
                        "type": "string",
                        "enum": ["2D", "3D"],
                        "description": "布局类型: 2D=横截面, 3D=三维视图 (默认 2D)",
                    },
                    "export_path": {
                        "type": "string",
                        "description": "可选：导出图像的文件路径 (支持 .bmp/.wmf)。不提供则自动生成。",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_layout_image",
            "description": (
                "把当前布局图导出为真实位图（PNG），返回可直接查看的图片路径。"
                "走 system.Tools.Layouts 的图形导出接口（Open3DViewerExport / OpenCrossSectionExport），"
                "按官方用法设置 OutputFilename/像素尺寸后必须 RunAndWaitForCompletion 才会真正渲染写盘。"
                "3D 默认用 CameraViewpointAngleX/Y/Z = 0/0/0 的标准视角（与 Zemax GUI 一致），"
                "返回值里的 camera.readback_deg 是实际生效的角度，可直接核对。"
                "用于让 Agent 与用户都能看到结构图，检查元件干涉、光线是否合理等。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "layout_type": {
                        "type": "string",
                        "enum": ["2D", "3D"],
                        "description": "2D=横截面布局, 3D=三维布局 (默认 3D)",
                    },
                    "width": {
                        "type": "integer",
                        "description": "输出像素宽 (默认 1600)",
                    },
                    "height": {
                        "type": "integer",
                        "description": "输出像素高 (默认 1000)",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "可选：指定输出路径(.png)。不提供则存到当前工程 layouts/ 目录",
                    },
                    "hide_lens_edges": {
                        "type": "boolean",
                        "description": "3D 布局是否隐藏透镜边缘/X 条（默认 true，出图更干净，只看面形与光线）",
                    },
                    "view": {
                        "type": "string",
                        "enum": ["current", "isometric", "xy", "yz", "xz"],
                        "description": (
                            "3D 相机视角。current（默认）= 不调预设，改用下面的 angle_x/y/z 角度，"
                            "默认角度 0/0/0 即 Zemax 3D 布局的标准视角（与 GUI 一致）；"
                            "isometric=正等轴测预设（有立体感，但角度非 0）；xy/yz/xz=三视图预设。"
                        ),
                    },
                    "angle_x": {
                        "type": "number",
                        "description": "3D 相机绕 X 轴旋转角度（度），仅 view=current 时生效，默认 0",
                    },
                    "angle_y": {
                        "type": "number",
                        "description": "3D 相机绕 Y 轴旋转角度（度），仅 view=current 时生效，默认 0",
                    },
                    "angle_z": {
                        "type": "number",
                        "description": "3D 相机绕 Z 轴旋转角度（度），仅 view=current 时生效，默认 0",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_interference",
            "description": (
                "检查所有相邻实体（透镜元件之间、透镜与光阑之间）在边缘处是否实体相交。"
                "按 z_edge = z_vertex + sag(半口径, R) 计算边缘净空，负值表示已经插在一起。"
                "**这是 check_manufacturability 的盲区**（后者只看单个元件的边厚/弯曲因子，不看实体之间）。"
                "每轮优化后必跑，尤其当布局图上看不清光阑与透镜是否贴合时——用数值代替肉眼。"
                "默认同时生成几何示意图（不依赖位图像素标定，按 LDE 数据确定性复现）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_clearance": {
                        "type": "number",
                        "description": (
                            "透镜元件之间判定为 pass 的最小净空 (mm，默认 0.1)；"
                            "小于此值报 warn，小于 0 报 fail。设计里 0.2~0.25mm 的空气层是正常的，所以默认值不宜放大"
                        ),
                    },
                    "stop_clearance": {
                        "type": "number",
                        "description": (
                            "透镜与光阑之间判定为 pass 的最小净空 (mm，默认 2.0)。"
                            "光阑座需要装配空间；1mm 在布局图上几乎看不出，会被误判为重叠"
                        ),
                    },
                    "save_image": {
                        "type": "boolean",
                        "description": "是否生成净空剖面示意图（默认 true，存为 layouts/_clearance_check.png）",
                    },
                    "image_path": {
                        "type": "string",
                        "description": "可选：示意图输出路径(.png)，不提供则存到 layouts/_clearance_check.png",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_image_quality",
            "description": (
                "获取当前系统各视场的成像质量定量指标：RMS 弥散斑半径 (μm)、RMS 波前误差 (waves)，"
                "并计算艾里斑半径、判断是否达到衍射极限 (Marechal 准则 RMS < λ/14)。"
                "这是设计验收的核心评估工具，建议每轮优化后调用以确认是否满足 SPT 指标。"
                "注意：RSCE/RWCE 操作数使用当前 MFE 的采样配置；若未设置评价函数，"
                "建议先调用 set_default_merit_function 以配置有效采样。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "wave": {
                        "type": "integer",
                        "description": "波长编号 (1-N)；0 = 多色综合 (默认)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_aberrations",
            "description": (
                "获取系统三阶塞德尔像差系数（球差 W040、慧差 W131、像散 W222、"
                "场曲 W220、畸变 W311，单位 λ）以及轴向色差 (mm) 和横向色差。"
                "通过 dominant_aberration 字段可知哪种像差主导，从而指导优化策略。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_distortion",
            "description": (
                "获取多个归一化视场高度处的几何畸变 (%) 数据。"
                "目视系统要求 < 5%；显微镜系统通常要求 < 1%；测量仪器要求 < 0.1%。"
                "返回最大畸变值和逐视场采样表。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "num_points": {
                        "type": "integer",
                        "description": "沿视场方向采样点数量 (3-11)，默认 5",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mtf",
            "description": (
                "获取指定空间频率 (cycles/mm) 处各视场的 MTF 值（切向 T / 弧矢 S），"
                "并与理论衍射极限 MTF 比较。"
                "衍射截止频率 = 2×NA/λ_primary；超出截止频率则 MTF 理论为 0。"
                "建议在衍射截止频率的 0.5 倍处检查 MTF 以判断是否达到衍射极限。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "frequency": {
                        "type": "number",
                        "description": "空间频率 (cycles/mm，线对/毫米)",
                    },
                    "wave": {
                        "type": "integer",
                        "description": "波长编号 (1-N)；0 = 多色综合 (默认)",
                    },
                },
                "required": ["frequency"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_field_illumination",
            "description": (
                "检查各视场的相对照度/通光状态，识别 0 光强、严重渐晕或被遮拦视场。"
                "显微镜、望远镜和大视场系统优化后必须调用；若某视场相对照度接近 0，"
                "点列图/MTF/SPT 对该视场不可作为有效验收。若 RELI 对离轴视场退化为全 1.0，"
                "工具会按低置信度返回，要求交叉验证。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "wave": {
                        "type": "integer",
                        "description": "波长编号 (1-N)；0 = 主波长 (默认)",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "低照度阈值，默认 0.05；低于此值视为近似无有效通光。",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mtf_curve",
            "description": (
                "在多个空间频率点（0 到截止频率之间均匀采样）计算 MTF，返回完整曲线数据，"
                "同时给出衍射极限 MTF 曲线用于对比。"
                "比单次 get_mtf 调用更全面，适合验收阶段评估系统传递函数曲线整体形状。"
                "返回：各频率点各视场 T/S MTF，以及衍射极限理论值列表。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "num_points": {
                        "type": "integer",
                        "description": "频率采样点数量 (3-10)，默认 5",
                    },
                    "max_frequency": {
                        "type": "number",
                        "description": "最大频率上限 (cycles/mm)；0 = 自动取衍射截止频率",
                    },
                    "wave": {
                        "type": "integer",
                        "description": "波长编号 (1-N)；0 = 多色综合 (默认)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_analysis_data",
            "description": "运行任意已支持的 Zemax Analysis 图窗，返回结构化 DataSeries/DataGrids/SpotData、文本导出和图像导出状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "analysis": {
                        "type": "string",
                        "enum": [
                            "standard_spot", "relative_illumination", "vignetting_diagram",
                            "ray_fan", "opd_fan", "longitudinal_aberration", "lateral_color",
                            "fft_mtf", "fft_mtf_vs_field", "huygens_mtf", "field_curvature_distortion",
                            "wavefront_map",
                        ],
                        "description": "要运行的分析类型。",
                    },
                    "settings": {"type": "object", "description": "可选设置覆盖，如 field/wave/sample_size/remove_vignetting/frequencies。"},
                    "keep_window": {"type": "boolean", "description": "是否保留 Zemax 分析窗口，默认 false。"},
                    "export_image": {"type": "boolean", "description": "是否尝试导出图像，默认 true。"},
                    "export_text": {"type": "boolean", "description": "是否导出文本，默认 true。"},
                },
                "required": ["analysis"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_relative_illumination_data",
            "description": "通过 Zemax Relative Illumination Analysis 获取相对照度曲线，并自动标记 0 光强、边缘照度骤降和低置信度结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "wave": {"type": "integer", "description": "波长编号 (1-N)；0 = 主波长 (默认)"},
                    "threshold": {"type": "number", "description": "低照度阈值，默认 0.05"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vignetting_diagram_data",
            "description": "运行 Vignetting Diagram，导出渐晕/遮拦诊断数据与图像，用于定位最大视场被截断问题。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spot_diagram_data",
            "description": "通过 Standard Spot Diagram Analysis 获取点列图数据，返回每视场 RMS/GEO spot、空视场标记、文本和图像导出路径。",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "integer", "description": "视场编号；0 = 所有视场 (默认)"},
                    "wave": {"type": "integer", "description": "波长编号；0 = 所有波长 (默认)"},
                    "ray_density": {"type": "integer", "description": "点列图采样密度枚举，默认不改 Zemax 当前值"},
                    "show_airy_disk": {"type": "boolean", "description": "是否显示 Airy disk，默认 true"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_spot_diagram_image",
            "description": (
                "把点列图（Standard Spot）保存为 PNG 图片，固定文件名 layouts/spot_diagram.png（覆盖旧图），"
                "默认叠加艾里斑参考圆（Airy Disk，按 1.22·λ·F# 计算）。"
                "ZOS-API 的分析类没有位图导出接口，因此按真实光线落点渲染，数值与 Zemax 一致。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "show_airy": {"type": "boolean", "description": "是否绘制艾里斑参考圆，默认 true"},
                    "wave": {"type": "integer", "description": "波长编号；0 = 全部 (默认)"},
                    "file_path": {"type": "string", "description": "可选：自定义输出路径(.png)，默认 layouts/spot_diagram.png"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fft_mtf_vs_field",
            "description": "通过 FFT MTF vs Field Analysis 获取指定频率随视场变化的 MTF 曲线，替代不稳定的临时 MFE MTF 采样。",
            "parameters": {
                "type": "object",
                "properties": {
                    "frequencies": {"type": "array", "items": {"type": "number"}, "description": "最多 6 个空间频率 cycles/mm，默认 [50,100,200,300]"},
                    "wave": {"type": "integer", "description": "波长编号；0 = 所有波长 (默认)"},
                    "sample_size": {"type": "integer", "description": "采样枚举，默认不改 Zemax 当前值"},
                    "remove_vignetting": {"type": "boolean", "description": "是否 Remove Vignetting，默认 false"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ray_fan_data",
            "description": "通过 Ray Fan Analysis 获取子午/弧矢光扇数据，统计缺失采样比例，用于遮拦和像差诊断。",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "integer", "description": "视场编号；0 = 所有视场 (默认)"},
                    "wave": {"type": "integer", "description": "波长编号；0 = 所有波长 (默认)"},
                    "number_of_rays": {"type": "integer", "description": "光扇采样光线数，默认不改 Zemax 当前值"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_opd_fan_data",
            "description": "通过 Optical Path Fan Analysis 获取 OPD 光扇数据，辅助判断波前误差和衍射极限状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "integer", "description": "视场编号；0 = 所有视场 (默认)"},
                    "wave": {"type": "integer", "description": "波长编号；0 = 所有波长 (默认)"},
                    "number_of_rays": {"type": "integer", "description": "光扇采样光线数，默认不改 Zemax 当前值"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_longitudinal_aberration_data",
            "description": "通过 Longitudinal Aberration Analysis 获取轴向相差/球色差数据，用于 APO 验收。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lateral_color_data",
            "description": "通过 Lateral Color Analysis 获取垂轴色差数据，用于离轴色差验收。",
            "parameters": {
                "type": "object",
                "properties": {
                    "use_real_rays": {"type": "boolean", "description": "是否使用 real rays，默认 true"},
                    "show_airy_disk": {"type": "boolean", "description": "是否显示 Airy disk，默认 true"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_field_curvature_distortion_data",
            "description": "通过 Field Curvature and Distortion Analysis 获取场曲/畸变曲线，补充 MFE 畸变操作数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "wave": {"type": "integer", "description": "波长编号；0 = 所有波长 (默认)"},
                    "ignore_vignette": {"type": "boolean", "description": "是否忽略渐晕，默认 false"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wavefront_map_data",
            "description": "通过 Wavefront Map Analysis 获取波前 DataGrid 与导出图像，用于局部遮拦和波前结构诊断。",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "integer", "description": "视场编号；0 = 所有视场/默认"},
                    "wave": {"type": "integer", "description": "波长编号；0 = 主波长/默认"},
                    "sampling": {"type": "integer", "description": "采样枚举，默认不改 Zemax 当前值"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_validation_report",
            "description": "批量运行相对照度、点列图、MTF vs Field、光扇、轴向/垂轴色差等分析，生成闭环验收报告。",
            "parameters": {
                "type": "object",
                "properties": {
                    "frequencies": {"type": "array", "items": {"type": "number"}, "description": "MTF vs Field 频率列表，默认 [50,100,200,300]"},
                    "include_heavy": {"type": "boolean", "description": "是否包含 Wavefront Map 等较重分析，默认 false"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_manufacturability",
            "description": (
                "对当前光学系统进行可制造性检查，输出每个透镜元件的加工关键指标：\n"
                "• 中心厚度（CT）和边缘厚度（ET）\n"
                "• CT/ET 比值（极端比值难以加工）\n"
                "• 透镜弯曲因子 B = (R2+R1)/(R2-R1)（极端弯月形）\n"
                "• 最小曲率半径是否可抛光（< 3mm 视为危险）\n"
                "• 最大半口径与中心厚度之比（纤薄透镜风险）\n"
                "对每个问题项给出具体警告，并给出综合评分 pass/warn/fail。\n"
                "建议在每次优化结束后调用，防止优化器造出无法加工的镜片。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ---------------------------------------------------------------------------
#  工具实现
# ---------------------------------------------------------------------------


class ZemaxToolkit:
    """封装所有 Zemax 工具的调用逻辑."""

    def __init__(self, conn: ZemaxConnection):
        self.conn = conn
        self._last_backup_info = None
        # Hammer 持续运行的持久状态（跨工具调用保持）
        self._hammer_opt = None
        self._hammer_tool_base = None
        self._hammer_start_mf = None

    # ---- 分发 (带自动重连) ----
    def dispatch(self, tool_name: str, arguments: dict) -> str:
        """根据工具名调用对应方法，返回 JSON 字符串结果.

        如果检测到 COM 连接断开，会自动尝试重连后再执行工具。
        """
        fn = getattr(self, tool_name, None)
        if fn is None:
            logger.warning(f"未知工具调用: {tool_name}")
            return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)

        # 执行前检测连接状态
        if not self.conn.is_alive:
            logger.warning(f"工具 {tool_name} 执行前检测到连接丢失，尝试自动重连")
            print("\033[33m  [连接丢失] 正在尝试自动重连...\033[0m")
            if not self.conn.reconnect():
                logger.error("自动重连失败，工具执行中止")
                return json.dumps(
                    {"error": "OpticStudio 连接已断开且无法自动重连。请在 Zemax 中重新打开 Interactive Extension，然后输入 reconnect 手动重连。"},
                    ensure_ascii=False,
                )
            logger.info("自动重连成功，继续执行工具")
            print("\033[32m  [已重连] 继续执行工具...\033[0m")

        backup_info = None
        if tool_name in _HIGH_RISK_TOOLS:
            backup_info = self._auto_backup_current_system(tool_name)
            self._last_backup_info = backup_info

        try:
            result = fn(**arguments)
            result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
            result_str = _attach_dispatch_metadata(result_str, backup_info)
            # 工具执行成功后自动刷新 UI（仅对写操作工具）
            if tool_name not in _READ_ONLY_TOOLS:
                self._auto_refresh_ui()
            return result_str
        except Exception as e:
            err_str = str(e)
            # 检测 COM 断连类异常，尝试重连后重试一次
            if _is_com_disconnect_error(err_str):
                logger.warning(f"工具 {tool_name} 触发 COM 断连异常，尝试重连: {err_str[:200]}")
                print("\033[33m  [COM 异常] 连接可能已断开，尝试重连...\033[0m")
                if self.conn.reconnect():
                    try:
                        result = fn(**arguments)
                        result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
                        result_str = _attach_dispatch_metadata(result_str, backup_info)
                        if tool_name not in _READ_ONLY_TOOLS:
                            self._auto_refresh_ui()
                        return result_str
                    except Exception as e2:
                        logger.error(f"工具 {tool_name} 重连后再次失败: {e2}", exc_info=True)
                        return json.dumps(
                            {"error": str(e2), "traceback": traceback.format_exc()},
                            ensure_ascii=False,
                        )
            logger.error(f"工具 {tool_name} 执行失败: {err_str[:300]}")
            return json.dumps(
                {"error": err_str, "traceback": traceback.format_exc()},
                ensure_ascii=False,
            )

    def _auto_refresh_ui(self) -> None:
        """工具执行后自动刷新 OpticStudio GUI（静默，不抛出异常）.

        策略：
        1. 先计算 MFE，避免 GUI 评价函数值停留在旧值
        2. 将 UpdateMode 设为 AllWindows，再调用 UpdateStatus()
        3. 显示 MFE，并刷新所有已打开分析窗口
        """
        try:
            system = self.conn.system
            try:
                self.conn.mfe.CalculateMeritFunction()
            except Exception:
                pass
            try:
                _safe_set_attr(system, "UpdateMode", 2)  # LensUpdateMode_AllWindows
            except Exception:
                pass
            try:
                getattr(system, "UpdateStatus")()
            except Exception:
                pass
            try:
                self.conn.mfe.ShowMFE()
            except Exception:
                pass
            try:
                analyses = getattr(system, "Analyses", None)
                n = _safe(analyses, "NumberOfAnalyses", 0)
                for i in range(1, n + 1):
                    try:
                        a = analyses.Get_AnalysisAtIndex(i)
                        if a is not None:
                            a.ApplyAndWaitForCompletion()
                    except Exception:
                        continue
            except Exception:
                pass
        except Exception:
            pass

    def _current_system_file(self) -> Path | None:
        """返回当前系统文件路径；未保存或不可用时返回 None。"""
        try:
            file_path = _safe(self.conn.system, "SystemFile", None)
            if not file_path:
                return None
            return Path(str(file_path))
        except Exception:
            return None

    def _auto_backup_current_system(self, reason: str) -> dict | None:
        """在高风险操作前备份当前系统文件。失败只记录日志，不阻断工具执行。"""
        current_file = self._current_system_file()
        if current_file is None or not str(current_file):
            return None

        try:
            getattr(self.conn.system, "Save")()
        except Exception as e:
            logger.warning(f"自动备份前保存当前系统失败，继续尝试复制磁盘文件: {e}")

        if not current_file.exists():
            logger.warning(f"自动备份跳过：当前系统文件不存在: {current_file}")
            return None

        try:
            safe_reason = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in reason)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = current_file.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            backup_file = backup_dir / f"{current_file.stem}_{safe_reason}_{timestamp}{current_file.suffix}"
            copied = [str(backup_file)]
            shutil.copy2(current_file, backup_file)

            for ext in (".ZDA", ".zda"):
                sidecar = current_file.with_suffix(ext)
                if sidecar.exists():
                    sidecar_backup = backup_file.with_suffix(ext)
                    shutil.copy2(sidecar, sidecar_backup)
                    copied.append(str(sidecar_backup))

            logger.info(f"自动备份完成: {backup_file}")
            return {
                "backup_path": str(backup_file),
                "backup_files": copied,
                "backup_reason": reason,
            }
        except Exception as e:
            logger.warning(f"自动备份失败: {e}", exc_info=True)
            return None

    def get_project_context(self) -> str:
        """获取当前工程上下文，帮助 Agent 正确选择/保存工程文件。"""
        current_file = self._current_system_file()
        current_dir = current_file.parent if current_file else _WORKSPACE_ROOT
        backups_dir = current_dir / "backups"
        layouts_dir = current_dir / "layouts"

        zmx_files = []
        seen = set()
        scan_dirs = [_WORKSPACE_ROOT]
        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for pattern in ("*.zmx", "*.ZMX"):
                for path in scan_dir.rglob(pattern):
                    try:
                        rel_parts = path.relative_to(_WORKSPACE_ROOT).parts
                        if any(part.lower() in _IGNORED_PROJECT_DIRS for part in rel_parts[:-1]):
                            continue
                    except Exception:
                        pass
                    key = str(path.resolve()).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        rel_path = path.relative_to(_WORKSPACE_ROOT).as_posix()
                    except Exception:
                        rel_path = str(path)
                    zmx_files.append({
                        "path": str(path),
                        "relative_path": rel_path,
                        "dir": path.parent.name,
                        "modified_time": _format_mtime(path),
                    })

        result = {
            "workspace_root": str(_WORKSPACE_ROOT),
            "current_file": str(current_file) if current_file else None,
            "current_dir": str(current_dir),
            "backups_dir": str(backups_dir),
            "layouts_dir": str(layouts_dir),
            "last_saved": _format_mtime(current_file) if current_file and current_file.exists() else None,
            "zmx_files": sorted(zmx_files, key=lambda item: item["relative_path"].lower()),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    def list_backups(self) -> str:
        """列出当前文件同目录 backups/ 中的备份文件，按时间倒序排列。"""
        current_file = self._current_system_file()
        current_dir = current_file.parent if current_file else _WORKSPACE_ROOT
        backups_dir = current_dir / "backups"
        backups = []
        if backups_dir.exists():
            for pattern in ("*.zmx", "*.ZMX"):
                for path in backups_dir.glob(pattern):
                    backups.append({
                        "path": str(path),
                        "filename": path.name,
                        "size_kb": round(path.stat().st_size / 1024, 1),
                        "modified_time": _format_mtime(path),
                    })
        backups.sort(key=lambda item: item["modified_time"] or "", reverse=True)
        return json.dumps({"backups_dir": str(backups_dir), "backups": backups}, ensure_ascii=False, indent=2)

    # ---- 系统信息 ----
    def get_system_info(self) -> str:
        sys_data = self.conn.system_data
        lde = self.conn.lde

        # 光圈
        aperture_info = {
            "type": str(sys_data.Aperture.ApertureType),
            "value": sys_data.Aperture.ApertureValue,
        }

        # 视场 (通过安全访问层读取)
        fields_info = []
        for i in range(1, sys_data.Fields.NumberOfFields + 1):
            f = sys_data.Fields.GetField(i)
            x, y, weight = self.conn.get_field_data(f)
            fields_info.append({"index": i, "x": x, "y": y, "weight": weight})

        # 波长 (通过安全访问层读取)
        wavelengths_info = []
        for i in range(1, sys_data.Wavelengths.NumberOfWavelengths + 1):
            w = sys_data.Wavelengths.GetWavelength(i)
            value, weight = self.conn.get_wavelength_data(w)
            wavelengths_info.append({"index": i, "value_um": value, "weight": weight})

        # 表面
        surfaces = []
        num_surf = lde.NumberOfSurfaces
        for i in range(num_surf):
            surf = lde.GetSurfaceAt(i)
            # 读取材料 solve 类型（用于验证替代玻璃等是否生效）
            material_solve = None
            try:
                mc = surf.MaterialCell
                sd = mc.GetSolveData()
                material_solve = _safe(sd, "Type", None)
            except Exception:
                material_solve = None
            surfaces.append(
                {
                    "number": i,
                    "comment": _safe(surf, "Comment", ""),
                    "radius": _safe(surf, "Radius", None),
                    "thickness": _safe(surf, "Thickness", None),
                    "material": _safe(surf, "Material", ""),
                    "material_solve": material_solve,
                    "semi_diameter": _safe(surf, "SemiDiameter", None),
                    "conic": _safe(surf, "Conic", 0.0),
                    "is_stop": _safe(surf, "IsStop", False),
                }
            )

        info = {
            "num_surfaces": num_surf,
            "aperture": aperture_info,
            "fields": fields_info,
            "wavelengths": wavelengths_info,
            "surfaces": surfaces,
        }
        return json.dumps(info, ensure_ascii=False, indent=2)

    # ---- 表面操作 ----
    def insert_surface(self, position: int) -> str:
        lde = self.conn.lde
        lde.InsertNewSurfaceAt(position)
        return json.dumps({"ok": True, "message": f"已在位置 {position} 插入新表面"}, ensure_ascii=False)

    def edit_surface(self, surface_number: int, **kwargs) -> str:
        lde = self.conn.lde
        surf = lde.GetSurfaceAt(surface_number)
        changed = []

        if "radius" in kwargs and kwargs["radius"] is not None:
            raw = kwargs["radius"]
            if isinstance(raw, str):
                token = raw.strip().lower()
                if token in ("infinity", "infinite", "inf", "∞", "平面", "flat"):
                    rval = float("inf")
                else:
                    rval = float(raw)
            else:
                rval = float(raw)
                # ≥1e15 视为平面：写真正的 Infinity，而不是留一个巨大数值
                if abs(rval) >= 1e15:
                    rval = float("inf")
            surf.Radius = rval
            changed.append("radius=Infinity" if rval == float("inf") else f"radius={kwargs['radius']}")

        if "thickness" in kwargs and kwargs["thickness"] is not None:
            surf.Thickness = float(kwargs["thickness"])
            changed.append(f"thickness={kwargs['thickness']}")

        if "material" in kwargs and kwargs["material"] is not None:
            surf.Material = str(kwargs["material"])
            changed.append(f"material={kwargs['material']}")

        if "semi_diameter" in kwargs and kwargs["semi_diameter"] is not None:
            surf.SemiDiameter = float(kwargs["semi_diameter"])
            changed.append(f"semi_diameter={kwargs['semi_diameter']}")

        if "conic" in kwargs and kwargs["conic"] is not None:
            surf.Conic = float(kwargs["conic"])
            changed.append(f"conic={kwargs['conic']}")

        if "comment" in kwargs and kwargs["comment"] is not None:
            surf.Comment = str(kwargs["comment"])
            changed.append(f"comment={kwargs['comment']}")

        if "is_stop" in kwargs and kwargs["is_stop"] is not None:
            if kwargs["is_stop"]:
                surf.IsStop = True
                changed.append("is_stop=True")

        return json.dumps(
            {"ok": True, "surface": surface_number, "changed": changed},
            ensure_ascii=False,
        )

    def remove_surface(self, surface_number: int) -> str:
        lde = self.conn.lde
        num = lde.NumberOfSurfaces
        if surface_number <= 0 or surface_number >= num - 1:
            return json.dumps(
                {"error": f"无法删除物面(0)或像面({num - 1})"},
                ensure_ascii=False,
            )
        lde.RemoveSurfaceAt(surface_number)
        return json.dumps({"ok": True, "message": f"已删除面 {surface_number}"}, ensure_ascii=False)

    def set_surface_type(self, surface_number: int, surface_type: str) -> str:
        lde = self.conn.lde
        surf = lde.GetSurfaceAt(surface_number)
        # 尝试通过名称查找类型 (COM 属性名为 typeName, 注意大小写)
        try:
            type_settings = surf.GetSurfaceTypeSettings(surface_type)
            surf.ChangeType(type_settings)
        except Exception:
            return json.dumps(
                {"error": f"无法将面 {surface_number} 改为类型 '{surface_type}'，请检查类型名称"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"ok": True, "message": f"面 {surface_number} 类型已改为 {surface_type}"},
            ensure_ascii=False,
        )

    # ---- 光圈 ----
    def set_aperture(self, aperture_type: str, value: float) -> str:
        aperture_map = {
            "EntrancePupilDiameter": 0,
            "ImageSpaceFNumber": 1,
            "ObjectSpaceNA": 2,
            "FloatByStopSize": 3,
        }
        sys_data = self.conn.system_data
        apt = sys_data.Aperture
        type_val = aperture_map.get(aperture_type, 0)
        apt.ApertureType = type_val
        apt.ApertureValue = value
        return json.dumps(
            {"ok": True, "aperture_type": aperture_type, "value": value},
            ensure_ascii=False,
        )

    # ---- 视场 ----
    def set_fields(self, field_type: str, fields: list) -> str:
        field_type_map = {
            "Angle": 0,
            "ObjectHeight": 1,
            "ParaxialImageHeight": 2,
            "RealImageHeight": 3,
        }
        sys_data = self.conn.system_data
        flds = sys_data.Fields

        # 设置视场类型
        type_val = field_type_map.get(field_type, 0)
        try:
            flds.SetFieldType(type_val)
        except Exception:
            pass  # 部分版本可能不支持

        # 清除现有视场 (保留至少1个)
        while flds.NumberOfFields > 1:
            flds.RemoveField(flds.NumberOfFields)

        # 设置第一个视场 (通过安全访问层)
        if fields:
            f0 = fields[0]
            first = flds.GetField(1)
            self.conn.set_field_data(first, x=f0.get("x", 0.0), y=f0.get("y", 0.0), weight=f0.get("weight", 1.0))
            _set_field_vignetting(first, f0.get("vcx"), f0.get("vcy"))

        # 添加其余视场
        for f in fields[1:]:
            flds.AddField(f.get("x", 0.0), f.get("y", 0.0), f.get("weight", 1.0))
            added = flds.GetField(flds.NumberOfFields)
            _set_field_vignetting(added, f.get("vcx"), f.get("vcy"))

        # 读回实际写入的 VCX/VCY 供验证
        readback = []
        for i in range(1, flds.NumberOfFields + 1):
            ff = flds.GetField(i)
            readback.append({
                "y": _safe(ff, "Y", None),
                "vcx": _safe(ff, "VCX", None),
                "vcy": _safe(ff, "VCY", None),
            })

        return json.dumps(
            {"ok": True, "field_type": field_type, "count": len(fields), "readback": readback},
            ensure_ascii=False,
        )

    # ---- 波长 ----
    def set_wavelengths(self, wavelengths: list = None, preset: str = None) -> str:
        sys_data = self.conn.system_data
        wls = sys_data.Wavelengths

        if preset:
            preset_map = {
                "d_light": 3,     # d-光 0.5876 μm
                "C_light": 2,     # C-光 0.6563 μm
                "F_light": 1,     # F-光 0.4861 μm
                "FdC_Visible": 4,  # F, d, C 三波长
            }
            val = preset_map.get(preset, 3)
            try:
                wls.SelectWavelengthPreset(val)
            except Exception as e:
                return json.dumps({"error": f"预设波长设置失败: {e}"}, ensure_ascii=False)
            return json.dumps({"ok": True, "preset": preset}, ensure_ascii=False)

        if not wavelengths:
            return json.dumps({"error": "需要提供 wavelengths 或 preset"}, ensure_ascii=False)

        # 清除现有波长
        while wls.NumberOfWavelengths > 1:
            wls.RemoveWavelength(wls.NumberOfWavelengths)

        # 设置第一个波长 (通过安全访问层)
        w0 = wavelengths[0]
        first = wls.GetWavelength(1)
        self.conn.set_wavelength_data(first, value=w0["value"], weight=w0.get("weight", 1.0))

        # 添加其余波长
        for w in wavelengths[1:]:
            wls.AddWavelength(w["value"], w.get("weight", 1.0))

        return json.dumps(
            {"ok": True, "count": len(wavelengths)},
            ensure_ascii=False,
        )

    # ---- 变量 ----
    def set_model_glass(self, surface_number: int, index: float | None = None,
                        abbe: float | None = None, vary_index: bool = True,
                        vary_abbe: bool = True, dpgf: float | None = None,
                        vary_dpgf: bool = False) -> str:
        """把某面的玻璃设为"模型玻璃"(Model Glass)，并可令折射率/阿贝数为变量。

        SolveType_MaterialModel=24；参数在 ISolveMaterialModel 上：
        IndexNd / AbbeVd / dPgF 为数值，VaryIndex / VaryAbbe / VarydPgF 为变量开关。
        不传 index/abbe 时沿用 Zemax 由当前真实玻璃初始化出的 nd/vd。
        """
        lde = self.conn.lde
        surf = lde.GetSurfaceAt(surface_number)
        cell = surf.MaterialCell
        try:
            solve = cell.CreateSolveType(24)  # SolveType_MaterialModel
        except Exception as e:
            return json.dumps({"error": f"创建模型玻璃 solve 失败: {e}"}, ensure_ascii=False)
        if solve is None:
            return json.dumps({"error": "CreateSolveType(24) 返回 None"}, ensure_ascii=False)

        detail: dict[str, object] = {}
        try:
            model = solve._S_MaterialModel
        except Exception as e:
            return json.dumps({"error": f"取 ISolveMaterialModel 失败: {e}"}, ensure_ascii=False)

        def _read(attr):
            try:
                return getattr(model, attr)
            except Exception:
                return None

        before = {"index": _read("IndexNd"), "abbe": _read("AbbeVd")}
        try:
            if index is not None:
                model.IndexNd = float(index)
            if abbe is not None:
                model.AbbeVd = float(abbe)
            model.VaryIndex = bool(vary_index)
            model.VaryAbbe = bool(vary_abbe)
            if dpgf is not None:
                model.dPgF = float(dpgf)
            model.VarydPgF = bool(vary_dpgf)
        except Exception as e:
            detail["warning"] = f"参数设置失败: {e}"

        cell.SetSolveData(solve)
        after = {"index": _read("IndexNd"), "abbe": _read("AbbeVd")}
        return json.dumps(
            {
                "ok": True,
                "surface": surface_number,
                "glass_before": str(_safe(surf, "Material", "")),
                "index_before": before.get("index"),
                "abbe_before": before.get("abbe"),
                "index_after": after.get("index"),
                "abbe_after": after.get("abbe"),
                "vary_index": bool(vary_index),
                "vary_abbe": bool(vary_abbe),
                "detail": detail,
            },
            ensure_ascii=False,
        )

    def set_solve(self, surface_number: int, solve_type: str = "marginal_ray_height",
                  param: str = "thickness", height: float = 0.0, pupil_zone: float = 0.0) -> str:
        """设置表面单元格的 Solve（边缘光线高度 / 固定 / 变量）。

        教材里"令程序自动选择像平面，使轴上点边缘光线交点高度为零"，
        对应像面厚度上的 Marginal Ray Height solve（Height=0, PupilZone=0）。
        """
        lde = self.conn.lde
        surf = lde.GetSurfaceAt(surface_number)
        cell_map = {"radius": "RadiusCell", "thickness": "ThicknessCell", "conic": "ConicCell"}
        cell_attr = cell_map.get((param or "").strip().lower())
        if not cell_attr:
            return json.dumps({"error": f"不支持的位置: {param}"}, ensure_ascii=False)
        cell = getattr(surf, cell_attr)
        st = (solve_type or "").strip().lower()

        if st in ("marginal_ray_height", "marginalrayheight", "mrh"):
            try:
                solve = cell.CreateSolveType(6)  # SolveType_MarginalRayHeight
            except Exception as e:
                return json.dumps({"error": f"创建 solve 失败: {e}"}, ensure_ascii=False)
            if solve is None:
                return json.dumps({"error": "CreateSolveType 返回 None"}, ensure_ascii=False)
            detail: dict[str, object] = {}
            try:
                mrh = solve._S_MarginalRayHeight
                mrh.Height = float(height)
                mrh.PupilZone = float(pupil_zone)
                detail = {"height": float(height), "pupil_zone": float(pupil_zone)}
            except Exception as e:
                detail = {"warning": f"参数设置失败: {e}"}
            cell.SetSolveData(solve)
            readback = None
            try:
                readback = cell.GetSolveData().Type
            except Exception:
                pass
            return json.dumps(
                {
                    "ok": True,
                    "surface": surface_number,
                    "solve": "marginal_ray_height",
                    "detail": detail,
                    "solve_type_readback": readback,
                },
                ensure_ascii=False,
            )
        if st == "fixed":
            cell.MakeSolveFixed()
            return json.dumps({"ok": True, "surface": surface_number, "solve": "fixed"}, ensure_ascii=False)
        if st == "variable":
            cell.MakeSolveVariable()
            return json.dumps({"ok": True, "surface": surface_number, "solve": "variable"}, ensure_ascii=False)
        return json.dumps({"error": f"不支持的 solve 类型: {solve_type}"}, ensure_ascii=False)

    def make_variable(self, surface_number: int, param: str, variable: bool, catalog: str = None) -> str:
        lde = self.conn.lde
        surf = lde.GetSurfaceAt(surface_number)

        cell_map = {
            "radius": "RadiusCell",
            "thickness": "ThicknessCell",
            "conic": "ConicCell",
            "material": "MaterialCell",
        }
        cell_attr = cell_map.get(param)
        if not cell_attr:
            return json.dumps({"error": f"不支持的参数: {param}"}, ensure_ascii=False)

        cell = getattr(surf, cell_attr)

        if param == "material":
            # 玻璃：variable=true 表示设为"替代玻璃"(Substitute solve)，让优化器在玻璃库中自动搜索更优玻璃。
            if variable:
                try:
                    # SolveType_MaterialSubstitute = 22
                    solve = cell.CreateSolveType(22)
                    if solve is not None:
                        # 设置替代玻璃搜索的目录 (ISolveMaterialSubstitute.catalog)
                        if catalog:
                            try:
                                solve.catalog = catalog
                            except Exception:
                                pass
                        # 关键：必须 SetSolveData 把 solve 写回单元格，否则不生效
                        cell.SetSolveData(solve)
                    status = "替代玻璃(Substitute)变量"
                except Exception as e:
                    return json.dumps(
                        {"error": f"设置替代玻璃失败: {e}"},
                        ensure_ascii=False,
                    )
            else:
                cell.MakeSolveFixed()
                status = "固定(玻璃)"
        else:
            if variable:
                cell.MakeSolveVariable()
                status = "变量"
            else:
                cell.MakeSolveFixed()
                status = "固定"

        return json.dumps(
            {"ok": True, "message": f"面 {surface_number} 的 {param} 已设为{status}"},
            ensure_ascii=False,
        )

    # ---- 优化 ----
    def run_optimization(self, algorithm: str = "DLS", cycles: str = "Automatic", duration_seconds: int = 30) -> str:
        from win32com.client import CastTo

        tools = self.conn.system.Tools

        # Hammer(锤优化/全局搜索) 用于替代玻璃、全局寻优；DLS/OD 是局部优化
        # Hammer 是"持续运行"型优化：官方用法 RunAndWaitWithTimeout(seconds) 持续运行 N 秒后 Cancel。
        if algorithm == "Hammer":
            opt = tools.OpenHammerOptimization()
            if opt is None:
                return json.dumps(
                    {"error": "无法打开锤优化(Hammer)工具。可能原因: 1) 没有设置评价函数; 2) Zemax UI 中有其他工具窗口打开; 3) 没有变量。请关闭 Zemax 中的其他工具窗口后重试。"},
                    ensure_ascii=False,
                )
            _safe_set_attr(opt, "Algorithm", 0)
            tool_base = _cast_to_system_tool(opt)
            # 官方用法（ZOS-API IHammerOptimization）：RunAndWaitWithTimeout(seconds) 持续运行 N 秒，
            # 超时后工具继续跑，需 Cancel + WaitForCompletion + Close。
            # 注意：不要设 AutomaticOptimization=True（那是"自动优化"按钮，只跑一轮）。
            try:
                tool_base.RunAndWaitWithTimeout(float(duration_seconds))
            except Exception:
                pass
            mfv = _safe(opt, "CurrentMeritFunction", None)
            try:
                tool_base.Cancel()
            except Exception:
                pass
            try:
                tool_base.WaitForCompletion()
            except Exception:
                pass
            tool_base.Close()
            return json.dumps(
                {"ok": True, "algorithm": "Hammer", "duration_seconds": duration_seconds, "final_merit_function": mfv},
                ensure_ascii=False,
            )

        opt = tools.OpenLocalOptimization()
        if opt is None:
            return json.dumps(
                {"error": "无法打开局部优化工具。可能原因: 1) 没有设置评价函数; 2) Zemax UI 中有其他工具窗口打开; 3) 没有变量。请关闭 Zemax 中的其他工具窗口后重试。"},
                ensure_ascii=False,
            )

        # 配置优化参数 (这些属性在 ILocalOptimization 接口上)
        if algorithm == "OD":
            _safe_set_attr(opt, "Algorithm", 1)  # OrthogonalDescent
        else:
            _safe_set_attr(opt, "Algorithm", 0)  # DampedLeastSquares

        cycles_map = {
            "Automatic": 0,
            "Fixed_1": 1,
            "Fixed_5": 5,
            "Fixed_10": 10,
            "Fixed_50": 50,
        }
        cycle_val = cycles_map.get(cycles, 0)
        if cycle_val == 0:
            _safe_set_attr(opt, "Cycles", -1)  # Automatic
        else:
            if not _safe_set_attr(opt, "NumberOfCycles", cycle_val):
                _safe_set_attr(opt, "Cycles", cycle_val)

        # RunAndWaitForCompletion / Close 在基类 ISystemTool 上
        # 参考 PyZOS inheritance_dict: ILocalOptimization -> ISystemTool
        tool_base = _cast_to_system_tool(opt)
        tool_base.RunAndWaitForCompletion()

        # CurrentMeritFunction 在 ILocalOptimization 上
        mfv = _safe(opt, "CurrentMeritFunction", None)

        tool_base.Close()

        return json.dumps(
            {"ok": True, "algorithm": algorithm, "cycles": cycles, "final_merit_function": mfv},
            ensure_ascii=False,
        )

    # ---- Hammer 持续运行（界面保持打开，跨工具调用保持状态）----
    def start_hammer(self) -> str:
        """启动 Hammer 持续运行（不关闭界面），返回初始 MF。之后可用 get_hammer_status 读 MF、stop_hammer 停止。

        官方正确用法（ZOS-API IHammerOptimization）：
            HammerOpt = Tools.OpenHammerOptimization()
            HammerOpt.Run()   # 异步启动，立即返回，持续运行
            HammerOpt.Cancel()  # 停止
            HammerOpt.WaitForCompletion()
            HammerOpt.Close()
        注意：不要设 AutomaticOptimization=True（那是"自动优化"按钮，只跑一轮）。
        """
        tools = self.conn.system.Tools
        opt = tools.OpenHammerOptimization()
        if opt is None:
            return json.dumps(
                {"error": "无法打开锤优化(Hammer)工具。可能原因: 1) 没有设置评价函数; 2) Zemax UI 中有其他工具窗口打开; 3) 没有变量。请关闭 Zemax 中的其他工具窗口后重试。"},
                ensure_ascii=False,
            )
        _safe_set_attr(opt, "Algorithm", 0)  # DampedLeastSquares
        tool_base = _cast_to_system_tool(opt)
        try:
            # 异步启动，立即返回，Hammer 在 Zemax 中持续运行
            tool_base.Run()
        except Exception as e:
            return json.dumps({"error": f"启动 Hammer 失败: {e}"}, ensure_ascii=False)

        # 保存持久引用，界面保持打开、持续运行
        self._hammer_opt = opt
        self._hammer_tool_base = tool_base
        self._hammer_start_mf = _safe(opt, "CurrentMeritFunction", None)

        return json.dumps(
            {"ok": True, "message": "Hammer 已启动并持续运行(界面保持打开)", "initial_merit_function": self._hammer_start_mf},
            ensure_ascii=False,
        )

    def get_hammer_status(self) -> str:
        """读取 Hammer 当前评价函数值（不停止、不关闭界面）。"""
        if self._hammer_opt is None:
            return json.dumps(
                {"ok": False, "error": "Hammer 未在运行。请先调用 start_hammer。"},
                ensure_ascii=False,
            )
        mfv = _safe(self._hammer_opt, "CurrentMeritFunction", None)
        return json.dumps(
            {
                "ok": True,
                "running": True,
                "current_merit_function": mfv,
                "start_merit_function": self._hammer_start_mf,
                "delta": (self._hammer_start_mf - mfv) if (self._hammer_start_mf is not None and mfv is not None) else None,
            },
            ensure_ascii=False,
        )

    def stop_hammer(self) -> str:
        """停止 Hammer 并关闭界面。"""
        if self._hammer_opt is None:
            return json.dumps(
                {"ok": False, "error": "Hammer 未在运行。请先调用 start_hammer。"},
                ensure_ascii=False,
            )
        mfv = _safe(self._hammer_opt, "CurrentMeritFunction", None)
        try:
            self._hammer_tool_base.Cancel()
        except Exception:
            pass
        try:
            self._hammer_tool_base.WaitForCompletion()
        except Exception:
            pass
        try:
            self._hammer_tool_base.Close()
        except Exception:
            pass
        start_mf = self._hammer_start_mf
        self._hammer_opt = None
        self._hammer_tool_base = None
        self._hammer_start_mf = None
        return json.dumps(
            {
                "ok": True,
                "message": "Hammer 已停止并关闭",
                "start_merit_function": start_mf,
                "final_merit_function": mfv,
                "delta": (start_mf - mfv) if (start_mf is not None and mfv is not None) else None,
            },
            ensure_ascii=False,
        )

    def quick_focus(self) -> str:
        from win32com.client import CastTo

        tools = self.conn.system.Tools
        qf = tools.OpenQuickFocus()
        if qf is None:
            return json.dumps(
                {"error": "无法打开快速聚焦工具。可能原因: Zemax UI 中有其他工具窗口打开。请关闭后重试。"},
                ensure_ascii=False,
            )

        # 配置参数 (IQuickFocus 接口上)
        _safe_set_attr(qf, "Criterion", 0)  # SpotSizeRadial
        _safe_set_attr(qf, "UseCentroid", True)

        # RunAndWaitForCompletion / Close 在基类 ISystemTool 上
        # 参考 PyZOS inheritance_dict: IQuickFocus -> ISystemTool
        tool_base = _cast_to_system_tool(qf)
        tool_base.RunAndWaitForCompletion()
        tool_base.Close()

        return json.dumps({"ok": True, "message": "快速聚焦完成"}, ensure_ascii=False)

    def get_merit_function(self) -> str:
        mfe = self.conn.mfe
        try:
            mfv = mfe.CalculateMeritFunction()
        except Exception:
            mfv = None
        return json.dumps({"merit_function_value": mfv}, ensure_ascii=False)

    # ---- 文件操作 ----
    def new_file(self, save_first: bool = True) -> str:
        if save_first:
            try:
                getattr(self.conn.system, "Save")()
            except Exception:
                pass
        getattr(self.conn.system, "New")(False)
        return json.dumps({"ok": True, "message": "已创建新系统", "saved_previous": bool(save_first)}, ensure_ascii=False)

    def save_file(self, filename: str | None = None) -> str:
        if filename:
            getattr(self.conn.system, "SaveAs")(filename)
            return json.dumps({"ok": True, "message": f"已另存为 {filename}"}, ensure_ascii=False)
        else:
            getattr(self.conn.system, "Save")()
            return json.dumps({"ok": True, "message": "已保存"}, ensure_ascii=False)

    def open_file(self, filename: str, save_first: bool = True) -> str:
        if save_first:
            try:
                getattr(self.conn.system, "Save")()
            except Exception:
                pass
        getattr(self.conn.system, "LoadFile")(filename, False)
        return json.dumps({"ok": True, "message": f"已打开 {filename}", "opened_file": filename, "saved_previous": bool(save_first)}, ensure_ascii=False)

    # ---- 评价函数编辑 ----
    def set_default_merit_function(self, opt_type: int = 0, data: int = 1,
                                   reference: int = 0, rings: int = 3, arms: int = 3,
                                   use_glass_thickness: bool = False,
                                   glass_min: float = 0, glass_max: float = 1000,
                                   use_air_thickness: bool = False,
                                   air_min: float = 0, air_max: float = 1000,
                                   overall_weight: float = 1.0, start_at: int = 1) -> str:
        """使用序列优化向导设置默认评价函数 (参考 PyZOS zSetDefaultMeritFunctionSEQ)."""
        from win32com.client import CastTo

        mfe = self.conn.mfe
        wizard = _safe(mfe, "SEQOptimizationWizard", None)
        if wizard is None:
            return json.dumps(
                {"error": "无法获取序列优化向导 (SEQOptimizationWizard)。请确认 MFE 可用。"},
                ensure_ascii=False,
            )

        # 设置向导参数
        _safe_set_attr(wizard, "Type", opt_type)
        _safe_set_attr(wizard, "Data", data)
        _safe_set_attr(wizard, "Reference", reference)
        _safe_set_attr(wizard, "Ring", rings)
        _safe_set_attr(wizard, "Arm", arms)
        _safe_set_attr(wizard, "IsGlassUsed", use_glass_thickness)
        _safe_set_attr(wizard, "GlassMin", glass_min)
        _safe_set_attr(wizard, "GlassMax", glass_max)
        _safe_set_attr(wizard, "IsAirUsed", use_air_thickness)
        _safe_set_attr(wizard, "AirMin", air_min)
        _safe_set_attr(wizard, "AirMax", air_max)
        _safe_set_attr(wizard, "OverallWeight", overall_weight)
        _safe_set_attr(wizard, "StartAt", start_at)

        # 执行向导: ISEQOptimizationWizard -> IWizard (base)
        # CommonSettings.OK() 定义在 IWizard 上，需要 CastTo
        executed = False
        for attempt_fn in [
            lambda: CastTo(wizard, "IWizard").CommonSettings.OK(),
            lambda: wizard.CommonSettings.OK(),
            lambda: wizard.OK(),
            lambda: wizard.Apply(),
        ]:
            try:
                attempt_fn()
                executed = True
                break
            except Exception:
                continue

        if not executed:
            return json.dumps(
                {"error": "无法执行优化向导。所有已知执行方法均失败。"},
                ensure_ascii=False,
            )

        try:
            mfv = mfe.CalculateMeritFunction()
        except Exception:
            mfv = None

        return json.dumps(
            {
                "ok": True,
                "message": "默认评价函数已通过向导设置",
                "merit_function_value": mfv,
                "num_operands": _safe(mfe, "NumberOfOperands", None),
            },
            ensure_ascii=False,
        )

    def add_operand(self, operand_type: str, target: float | None = None,
                    weight: float = 1.0, int1: int | None = None, int2: int | None = None,
                    insert_at: int | None = None,
                    **cell_values) -> str:
        """向 MFE 添加一个操作数行."""
        mfe = self.conn.mfe

        type_val = _resolve_operand_type(operand_type)
        if type_val is None:
            return json.dumps(
                {"error": f"未知操作数类型: '{operand_type}'。请使用标准4字母代码(如 EFFL, BFL, TOTR)。"},
                ensure_ascii=False,
            )

        # 默认追加到末尾；若指定 insert_at，则插入到该行之前
        num = _safe(mfe, "NumberOfOperands", 0)
        if insert_at is None:
            insert_row = num + 1
        else:
            insert_row = max(1, min(int(insert_at), num + 1))

        row = None
        try:
            row = mfe.InsertNewOperandAt(insert_row)
        except Exception as insert_error:
            try:
                if insert_row != num + 1:
                    return json.dumps(
                        {"error": f"无法在第 {insert_row} 行插入新操作数: {insert_error}"},
                        ensure_ascii=False,
                    )
                row = mfe.AddOperand()
                insert_row = _safe(mfe, "NumberOfOperands", num + 1)
            except Exception as e:
                return json.dumps({"error": f"无法插入新操作数行: {e}"}, ensure_ascii=False)

        if row is None:
            return json.dumps({"error": "插入新操作数行返回 None"}, ensure_ascii=False)

        # 设置操作数类型
        if not _set_row_operand_type(row, type_val):
            return json.dumps(
                {"error": f"无法设置操作数类型 {operand_type} (enum={type_val})"},
                ensure_ascii=False,
            )
        row = mfe.GetOperandAt(insert_row) or row

        # 设置目标值和权重
        if target is not None:
            _safe_set_attr(row, "Target", float(target))
        if weight is not None:
            _safe_set_attr(row, "Weight", float(weight))

        # 设置 MFE 参数单元格（Int1/Int2/Hx/Hy/Px/Py/Ex/Ey）
        write_results = _apply_operand_cell_values(row, int1=int1, int2=int2, **cell_values)
        write_failures = [item for item in write_results if not item.get("ok")]

        # 计算获取当前值
        try:
            mfe.CalculateMeritFunction()
        except Exception:
            pass

        current_row = mfe.GetOperandAt(insert_row)
        current_value = _safe(current_row, "Value", None)

        return json.dumps(
            {
                "ok": True,
            "row": insert_row,
                "type": operand_type,
                "target": target,
                "weight": weight,
                "current_value": current_value,
                "cells": _operand_cells_dict(current_row),
                "write_results": write_results,
                "write_failures": write_failures,
            },
            ensure_ascii=False,
        )

    def edit_operand(self, row: int, operand_type: str = None, target: float = None,
                     weight: float = None, int1: int = None, int2: int = None,
                     **cell_values) -> str:
        """修改 MFE 中已有操作数行的类型、目标、权重或单元格参数."""
        mfe = self.conn.mfe
        num = _safe(mfe, "NumberOfOperands", 0)
        if row < 1 or row > num:
            return json.dumps({"error": f"MFE 行号超出范围: {row}, 当前共有 {num} 行"}, ensure_ascii=False)

        row_obj = mfe.GetOperandAt(row)
        if row_obj is None:
            return json.dumps({"error": f"无法获取 MFE 第 {row} 行"}, ensure_ascii=False)

        if operand_type:
            type_val = _resolve_operand_type(operand_type)
            if type_val is None:
                return json.dumps({"error": f"未知操作数类型: '{operand_type}'"}, ensure_ascii=False)
            if not _set_row_operand_type(row_obj, type_val):
                return json.dumps({"error": f"无法设置操作数类型 {operand_type}"}, ensure_ascii=False)
            row_obj = mfe.GetOperandAt(row)

        if target is not None:
            _safe_set_attr(row_obj, "Target", float(target))
        if weight is not None:
            _safe_set_attr(row_obj, "Weight", float(weight))

        write_results = _apply_operand_cell_values(row_obj, int1=int1, int2=int2, **cell_values)
        write_failures = [item for item in write_results if not item.get("ok")]

        try:
            mfe.CalculateMeritFunction()
        except Exception:
            pass

        current_row = mfe.GetOperandAt(row)
        return json.dumps(
            {
                "ok": True,
                "row": row,
                "type": _safe(current_row, "TypeName", None) or str(_safe(current_row, "Type", "?")),
                "target": _safe(current_row, "Target", None),
                "weight": _safe(current_row, "Weight", None),
                "value": _safe(current_row, "Value", None),
                "cells": _operand_cells_dict(current_row),
                "write_results": write_results,
                "write_failures": write_failures,
            },
            ensure_ascii=False,
        )

    def get_operands(self) -> str:
        """获取 MFE 中所有操作数详情."""
        mfe = self.conn.mfe
        num = _safe(mfe, "NumberOfOperands", 0)

        try:
            mf_value = mfe.CalculateMeritFunction()
        except Exception:
            mf_value = None

        operands = []
        for i in range(1, num + 1):
            row = mfe.GetOperandAt(i)
            op = {
                "row": i,
                "type": _safe(row, "TypeName", None) or str(_safe(row, "Type", "?")),
                "target": _safe(row, "Target", None),
                "weight": _safe(row, "Weight", None),
                "value": _safe(row, "Value", None),
                "contribution": _read_mfe_row_cell_value(row, "ContributionCell"),
            }
            p1 = _safe(row, "Param1", None)
            p2 = _safe(row, "Param2", None)
            if p1 is not None:
                op["int1"] = p1
            if p2 is not None:
                op["int2"] = p2
            cells = _operand_cells_dict(row)
            op["cells"] = cells
            for key in ("int1", "int2", "hx", "hy", "px", "py", "ex", "ey"):
                if key in cells:
                    op[key] = cells[key]
            operands.append(op)

        return json.dumps(
            {"merit_function_value": mf_value, "num_operands": num, "operands": operands},
            ensure_ascii=False,
            indent=2,
        )

    def remove_operands(self, rows: list = None) -> str:
        """从 MFE 删除指定行。清空全部请使用 clear_operands(confirm=true)。"""
        mfe = self.conn.mfe

        def _del(pos):
            try:
                mfe.DeleteOperandAt(pos)
                return
            except (AttributeError, Exception):
                pass
            mfe.RemoveOperandAt(pos)

        if rows is None:
            return json.dumps(
                {"error": "remove_operands 需要 rows=[...]；如需清空全部，请调用 clear_operands(confirm=true)"},
                ensure_ascii=False,
            )
        if len(rows) == 0:
            return json.dumps(
                {"error": "rows 为空，未删除任何操作数；如需清空全部，请调用 clear_operands(confirm=true)"},
                ensure_ascii=False,
            )

        for row_num in sorted(rows, reverse=True):
            _del(row_num)
        return json.dumps(
            {"ok": True, "message": f"已删除 {len(rows)} 行操作数"},
            ensure_ascii=False,
        )

    def clear_operands(self, confirm: bool = False) -> str:
        """显式清空 MFE 中所有可删除操作数。"""
        if not confirm:
            return json.dumps({"error": "清空 MFE 必须传 confirm=true"}, ensure_ascii=False)

        mfe = self.conn.mfe

        def _del(pos):
            try:
                mfe.DeleteOperandAt(pos)
                return
            except (AttributeError, Exception):
                pass
            mfe.RemoveOperandAt(pos)

        count = 0
        num = _safe(mfe, "NumberOfOperands", 0)
        while num > 1:
            _del(num)
            count += 1
            num = _safe(mfe, "NumberOfOperands", 0)
        first_available_row = num + 1
        return json.dumps(
            {
                "ok": True,
                "message": f"已清除 {count} 行操作数，剩余 {num} 行",
                "cleared_rows": count,
                "remaining_rows": num,
                "first_available_row": first_available_row,
            },
            ensure_ascii=False,
        )

    def get_merit_breakdown(self, top_n: int = 20) -> str:
        """按贡献度排序返回 MFE 主导项。"""
        mfe = self.conn.mfe
        top_n = max(1, min(100, int(top_n or 20)))
        try:
            mf_value = mfe.CalculateMeritFunction()
        except Exception:
            mf_value = None

        rows = []
        num = _safe(mfe, "NumberOfOperands", 0)
        for i in range(1, num + 1):
            row = mfe.GetOperandAt(i)
            target = _safe(row, "Target", None)
            weight = _safe(row, "Weight", None)
            value = _safe(row, "Value", None)
            contribution = _read_mfe_row_cell_value(row, "ContributionCell")
            estimated = _weighted_error_estimate(target, weight, value)
            rows.append({
                "row": i,
                "type": _safe(row, "TypeName", None) or str(_safe(row, "Type", "?")),
                "target": target,
                "weight": weight,
                "value": value,
                "contribution": contribution,
                "weighted_error_estimate": estimated,
                "int1": _operand_cells_dict(row).get("int1"),
                "int2": _operand_cells_dict(row).get("int2"),
            })

        def sort_key(item):
            contribution = item.get("contribution")
            if isinstance(contribution, (int, float)) and math.isfinite(contribution):
                return abs(contribution)
            estimate = item.get("weighted_error_estimate")
            if isinstance(estimate, (int, float)) and math.isfinite(estimate):
                return abs(estimate)
            return -1

        sorted_rows = sorted(rows, key=sort_key, reverse=True)
        return json.dumps(
            {
                "merit_function_value": mf_value,
                "num_operands": num,
                "top_n": top_n,
                "items": sorted_rows[:top_n],
            },
            ensure_ascii=False,
            indent=2,
        )

    def build_operand_block(self, operands: list, insert_at: int | None = None,
                            clear_first: bool = False) -> str:
        """按 label/ref 原子构建 MFE 操作数块，自动解析行号引用。"""
        if clear_first:
            clear_result = json.loads(self.clear_operands(confirm=True))
            if not clear_result.get("ok"):
                return json.dumps(clear_result, ensure_ascii=False)

        label_rows = {}
        built = []
        next_insert = insert_at
        for index, spec in enumerate(operands or [], start=1):
            spec = dict(spec)
            label = spec.pop("label", None)
            operand_type = spec.pop("operand_type", None) or spec.pop("type", None)
            if not operand_type:
                return json.dumps({"error": f"第 {index} 个操作数缺少 operand_type/type"}, ensure_ascii=False)

            for param_name in ("int1", "int2", "param1", "param2"):
                ref_name = spec.pop(f"{param_name}_ref", None)
                if ref_name is not None:
                    if ref_name not in label_rows:
                        return json.dumps(
                            {"error": f"第 {index} 个操作数引用未知 label: {ref_name}"},
                            ensure_ascii=False,
                        )
                    spec[param_name] = label_rows[ref_name]

            if next_insert is not None:
                spec["insert_at"] = next_insert
            add_result = json.loads(self.add_operand(operand_type=operand_type, **spec))
            if not add_result.get("ok"):
                return json.dumps({"error": "构建操作数块失败", "failed_at": index, "detail": add_result}, ensure_ascii=False)

            row_num = add_result.get("row")
            if label:
                label_rows[label] = row_num
            built.append({"index": index, "label": label, "row": row_num, "type": operand_type})
            if next_insert is not None and isinstance(row_num, int):
                next_insert = row_num + 1

        try:
            mf_value = self.conn.mfe.CalculateMeritFunction()
        except Exception:
            mf_value = None
        return json.dumps(
            {"ok": True, "built": built, "label_rows": label_rows, "merit_function_value": mf_value},
            ensure_ascii=False,
            indent=2,
        )

    def set_default_merit_function_after_current_block(self, opt_type: int = 0, data: int = 1,
                                                       reference: int = 0, rings: int = 3, arms: int = 3,
                                                       use_glass_thickness: bool = False,
                                                       glass_min: float = 0, glass_max: float = 1000,
                                                       use_air_thickness: bool = False,
                                                       air_min: float = 0, air_max: float = 1000,
                                                       overall_weight: float = 1.0) -> str:
        """从当前 MFE 操作数之后生成默认评价函数。"""
        start_at = _safe(self.conn.mfe, "NumberOfOperands", 0) + 1
        result = json.loads(self.set_default_merit_function(
            opt_type=opt_type,
            data=data,
            reference=reference,
            rings=rings,
            arms=arms,
            use_glass_thickness=use_glass_thickness,
            glass_min=glass_min,
            glass_max=glass_max,
            use_air_thickness=use_air_thickness,
            air_min=air_min,
            air_max=air_max,
            overall_weight=overall_weight,
            start_at=start_at,
        ))
        result["start_at"] = start_at
        result["custom_block_rows"] = start_at - 1
        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_ray_aiming_settings(self) -> str:
        """读取 Ray Aiming 相关属性。"""
        probes = _probe_ray_aiming_properties(self.conn.system_data)
        return json.dumps({"supported": any(p.get("readable") for p in probes), "probes": probes}, ensure_ascii=False, indent=2)

    def set_ray_aiming(self, enabled: bool, mode: str = "Paraxial", use_cache: bool = True) -> str:
        """多策略尝试设置 Ray Aiming。"""
        result = _set_ray_aiming_properties(self.conn.system_data, bool(enabled), mode or "Paraxial", bool(use_cache))
        if result.get("ok"):
            self._auto_refresh_ui()
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ---- 系统分析 ----
    def get_first_order_data(self) -> str:
        """通过临时 MFE 操作数计算一阶光学参数 (不影响现有评价函数)."""
        mfe = self.conn.mfe
        orig_num = _safe(mfe, "NumberOfOperands", 0)

        calc_ops = [
            ("EFFL", "有效焦距 (mm)"),
            ("BFL", "后焦距 (mm)"),
            ("TOTR", "总长 (mm)"),
        ]

        # 在 MFE 末尾添加临时监视操作数
        added = []
        for op_name, _ in calc_ops:
            type_val = _resolve_operand_type(op_name)
            if type_val is None:
                continue
            try:
                pos = _safe(mfe, "NumberOfOperands", 0) + 1
                row = mfe.InsertNewOperandAt(pos)
            except Exception:
                try:
                    row = mfe.AddOperand()
                except Exception:
                    continue
            if row is None:
                continue

            _set_row_operand_type(row, type_val)
            _safe_set_attr(row, "Weight", 0.0)
            _safe_set_attr(row, "Target", 0.0)
            added.append((op_name, _safe(mfe, "NumberOfOperands", 0)))

        # 计算
        try:
            mf_value = mfe.CalculateMeritFunction()
        except Exception:
            mf_value = None

        # 读取结果
        data = {}
        for op_name, row_num in added:
            try:
                row = mfe.GetOperandAt(row_num)
                data[op_name] = _safe(row, "Value", None)
            except Exception:
                data[op_name] = None

        # 清除临时操作数 (逆序删除)
        for _, row_num in reversed(added):
            try:
                mfe.DeleteOperandAt(row_num)
            except Exception:
                try:
                    mfe.RemoveOperandAt(row_num)
                except Exception:
                    pass

        display = {}
        for op_name, label in calc_ops:
            if op_name in data:
                display[op_name] = {"label": label, "value": data[op_name]}

        return json.dumps(
            {"first_order_data": display, "merit_function_value": mf_value},
            ensure_ascii=False,
            indent=2,
        )

    # ---- 成像质量分析 ----

    def get_image_quality(self, wave: int = 0) -> str:
        """各视场 RMS 弥散斑半径、RMS 波前误差，并判断是否达到衍射极限。

        使用临时 MFE 操作数读取数值 (不修改现有评价函数)。

        操作数说明：
          RSCE(surf=last, wave=w, hx=0, hy=Hn, px=0, py=0) → RMS 弥散斑半径 (μm，质心参考)
          RWCE(surf=last, wave=w, hx=0, hy=Hn, px=0, py=0) → RMS 波前误差 (waves，质心参考)
          ISNA → 像方 NA（用于艾里斑计算）
        """
        mfe = self.conn.mfe
        sys_data = self.conn.system_data
        lde = self.conn.lde

        # 读取系统参数
        num_fields = sys_data.Fields.NumberOfFields
        num_waves = sys_data.Wavelengths.NumberOfWavelengths
        last_surf = lde.NumberOfSurfaces - 1  # 像面索引

        # 主波长（取中间波长）
        primary_wave_idx = (num_waves + 1) // 2  # e.g. 3波长 → index 2
        primary_wave_um = None
        try:
            w_obj = sys_data.Wavelengths.GetWavelength(primary_wave_idx)
            primary_wave_um, _ = self.conn.get_wavelength_data(w_obj)
        except Exception:
            primary_wave_um = 0.5876  # 默认 d 线

        wave_param = wave  # 0=多色, 1..N=单色

        # 检测镜头单位并计算 RSCE→μm 换算因子
        # RSCE 操作数返回值的单位与镜头单位一致 (mm→需乘1000, cm→10000, etc.)
        # ScaleToUnits enum: Millimeters=0, Centimeters=1, Inches=2, Meters=3
        lens_unit_to_um = 1000.0  # 默认 mm
        try:
            units_obj = _safe(sys_data, "Units", None)
            if units_obj is not None:
                lu = _safe(units_obj, "LensUnits", None)
                if lu == 0:   lens_unit_to_um = 1000.0   # mm → μm
                elif lu == 1: lens_unit_to_um = 10000.0  # cm → μm
                elif lu == 2: lens_unit_to_um = 25400.0  # inches → μm
                elif lu == 3: lens_unit_to_um = 1e6      # m → μm
        except Exception:
            pass

        # --- 逐视场添加临时操作数 ---
        added = []  # (field_idx, op_name, row_num)

        def _add_tmp(op_name, int_params: dict):
            """在 MFE 末尾添加临时操作数，返回行号或 None。"""
            type_val = _resolve_operand_type(op_name)
            if type_val is None:
                return None
            pos = _safe(mfe, "NumberOfOperands", 0) + 1
            row = None
            try:
                row = mfe.InsertNewOperandAt(pos)
            except Exception:
                try:
                    row = mfe.AddOperand()
                except Exception:
                    return None
            if row is None:
                return None
            _set_row_operand_type(row, type_val)
            _safe_set_attr(row, "Weight", 0.0)
            _safe_set_attr(row, "Target", 0.0)
            # 整数参数: Param1=surf, Param2=wave, Param3=field(对于场相关操作数)
            for pnum, pval in int_params.items():
                _set_operand_int_param(row, pnum, pval)
            return _safe(mfe, "NumberOfOperands", 0)

        # ISNA
        isna_row = _add_tmp("ISNA", {})
        added.append(("ISNA", isna_row))

        # RSCE / RWCE per field
        # RSCE: Param1=surf, Param2=wave; 视场通过 Hx/Hy 指定（用 MFE Cell 设置）
        # 更简单的方式: 对每个视场，用 Hy=field_norm_y 的方式
        # ZOS-API MFE RSCE 参数: Int1=surf, Int2=wave, Hx,Hy,Px,Py 在 GetOperandCell
        # 实际上 Zemax 对 RSCE 的 Hy 是归一化视场高度; 最简单是用 Param3=field_idx
        # 但不同版本可能不同；保险方式: 使用 Param2=field, Param1=wave 类似 MTFT

        # 使用较通用方式: RSCE(Int1=last_surf, Int2=wave, Hx=0, Hy=Hn)
        # 通过 GetOperandCell 设置 Hx/Hy/Px/Py
        def _set_cell(row_obj, col_idx, float_val=None, int_val=None):
            try:
                cell = row_obj.GetOperandCell(col_idx)
                if cell is None:
                    return
                if float_val is not None:
                    try:
                        cell.DoubleValue = float_val
                    except Exception:
                        try:
                            cell.Value = float_val
                        except Exception:
                            pass
                if int_val is not None:
                    try:
                        cell.IntegerValue = int_val
                    except Exception:
                        try:
                            cell.Value = int_val
                        except Exception:
                            pass
            except Exception:
                pass

        # RSCE / RWCE col layout (0-indexed from GetOperandCell):
        # col 1 = Type, col 2 = Int1(surf), col 3 = Int2(wave),
        # col 4 = Hx, col 5 = Hy, col 6 = Px, col 7 = Py
        # 归一化基准必须取「全部视场 |y| 的最大值」，不能取最后一个视场。
        # 曾踩坑：视场按降序排列时（如 16/14/12/8/4/0°）最后一个视场是 0°，
        # max_fy 变成 0 → 所有视场的 Hy 都被算成 0 → 每个视场都读成轴上点的值
        # （表现为各视场 RMS 完全相同，是静默错误）。
        max_fy = 0.0
        max_fx = 0.0
        try:
            for _fi in range(1, num_fields + 1):
                _fx_tmp, _fy_tmp, _ = self.conn.get_field_data(sys_data.Fields.GetField(_fi))
                if _fy_tmp is not None and abs(_fy_tmp) > max_fy:
                    max_fy = abs(_fy_tmp)
                if _fx_tmp is not None and abs(_fx_tmp) > max_fx:
                    max_fx = abs(_fx_tmp)
        except Exception:
            pass
        if max_fy == 0.0:
            max_fy = max_fx if max_fx > 0 else 1.0  # 全轴上视场时用 x，再退回 1.0

        rsce_rows = []
        rwce_rows = []
        for fi in range(1, num_fields + 1):
            f_obj = sys_data.Fields.GetField(fi)
            _, fy, _ = self.conn.get_field_data(f_obj)
            hy_norm = (fy / max_fy) if max_fy != 0 else 0.0

            # RSCE row
            type_val_rsce = _resolve_operand_type("RSCE")
            if type_val_rsce is not None:
                pos = _safe(mfe, "NumberOfOperands", 0) + 1
                row = None
                try:
                    row = mfe.InsertNewOperandAt(pos)
                except Exception:
                    try:
                        row = mfe.AddOperand()
                    except Exception:
                        pass
                if row is not None:
                    _set_row_operand_type(row, type_val_rsce)
                    # ChangeType 后重新获取引用，防止旧引用失效
                    row = _refetch_last_row(mfe) or row
                    _safe_set_attr(row, "Weight", 0.0)
                    _safe_set_attr(row, "Target", 0.0)
                    _set_operand_int_param(row, 1, last_surf)   # Param1=surf
                    _set_operand_int_param(row, 2, wave_param)  # Param2=wave
                    # Hx=Param3(col4)=0, Hy=Param4(col5)=hy_norm
                    _set_operand_double_param(row, 3, 0.0)           # Hx
                    _set_operand_double_param(row, 4, float(hy_norm)) # Hy
                    rsce_rows.append((fi, fy, _safe(mfe, "NumberOfOperands", 0)))

            # RWCE row
            type_val_rwce = _resolve_operand_type("RWCE")
            if type_val_rwce is not None:
                pos = _safe(mfe, "NumberOfOperands", 0) + 1
                row = None
                try:
                    row = mfe.InsertNewOperandAt(pos)
                except Exception:
                    try:
                        row = mfe.AddOperand()
                    except Exception:
                        pass
                if row is not None:
                    _set_row_operand_type(row, type_val_rwce)
                    row = _refetch_last_row(mfe) or row
                    _safe_set_attr(row, "Weight", 0.0)
                    _safe_set_attr(row, "Target", 0.0)
                    _set_operand_int_param(row, 1, last_surf)   # Param1=surf
                    _set_operand_int_param(row, 2, wave_param)  # Param2=wave
                    # Hx=Param3(col4)=0, Hy=Param4(col5)=hy_norm
                    _set_operand_double_param(row, 3, 0.0)           # Hx
                    _set_operand_double_param(row, 4, float(hy_norm)) # Hy
                    rwce_rows.append((fi, fy, _safe(mfe, "NumberOfOperands", 0)))

        # --- 计算 ---
        try:
            mfe.CalculateMeritFunction()
        except Exception:
            pass

        # --- 读取 ISNA ---
        image_na = None
        if isna_row is not None:
            try:
                image_na = _safe(mfe.GetOperandAt(isna_row), "Value", None)
            except Exception:
                pass

        # 艾里斑半径 = 1.22 * λ / (2 * NA_image)，单位 μm
        # λ 已是 μm，结果直接是 μm，不需要再乘 1000
        airy_radius_um = None
        if image_na and image_na > 0 and primary_wave_um:
            airy_radius_um = round(1.22 * primary_wave_um / (2 * image_na), 4)

        # Marechal 准则: 衍射极限阈值 = λ/14 (in waves)
        marechal_threshold = 1 / 14.0  # ≈ 0.0714 waves

        # --- 读取 RSCE / RWCE ---
        fields_data = []
        rsce_dict = {}
        for fi, fy, rnum in rsce_rows:
            try:
                val = _safe(mfe.GetOperandAt(rnum), "Value", None)
                rsce_dict[fi] = val
            except Exception:
                rsce_dict[fi] = None

        rwce_dict = {}
        for fi, fy, rnum in rwce_rows:
            try:
                val = _safe(mfe.GetOperandAt(rnum), "Value", None)
                rwce_dict[fi] = val
            except Exception:
                rwce_dict[fi] = None

        for fi in range(1, num_fields + 1):
            f_obj = sys_data.Fields.GetField(fi)
            _, fy, _ = self.conn.get_field_data(f_obj)
            rms_spot_raw = rsce_dict.get(fi)  # 镜头单位 (mm)
            rms_spot = (rms_spot_raw * lens_unit_to_um) if rms_spot_raw is not None else None  # → μm
            rms_wfe = rwce_dict.get(fi)
            diffraction_limited = None
            if rms_wfe is not None:
                diffraction_limited = bool(rms_wfe < marechal_threshold)
            entry = {
                "field": fi,
                "field_y": fy,
                "rms_spot_um": round(rms_spot, 2) if rms_spot is not None else None,
                "rms_wavefront_waves": round(rms_wfe, 5) if rms_wfe is not None else None,
                "diffraction_limited": diffraction_limited,
            }
            if airy_radius_um is not None and rms_spot is not None:
                entry["vs_airy"] = round(rms_spot / airy_radius_um, 3)
            fields_data.append(entry)

        # --- 清除所有临时操作数 (逆序) ---
        all_tmp_rows = (
            [isna_row] if isna_row else []
        ) + [r for _, _, r in rsce_rows] + [r for _, _, r in rwce_rows]
        for rnum in sorted(set(all_tmp_rows), reverse=True):
            try:
                mfe.DeleteOperandAt(rnum)
            except Exception:
                try:
                    mfe.RemoveOperandAt(rnum)
                except Exception:
                    pass

        result = {
            "primary_wavelength_um": primary_wave_um,
            "image_na": image_na,
            "airy_radius_um": airy_radius_um,
            "marechal_threshold_waves": round(marechal_threshold, 4),
            "fields": fields_data,
        }

        # 汇总
        rms_spots = [f["rms_spot_um"] for f in fields_data if f["rms_spot_um"] is not None]
        if rms_spots:
            result["max_rms_spot_um"] = round(max(rms_spots), 4)
            result["all_diffraction_limited"] = all(
                f.get("diffraction_limited", False) for f in fields_data
                if f.get("diffraction_limited") is not None
            )

        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_aberrations(self) -> str:
        """获取三阶 Seidel 像差系数和色差 (临时 MFE 操作数方式)。

        操作数:
          SPHA → 三阶球差系数 W040 (waves)
          COMA → 三阶慧差 W131 (waves)
          ASTI → 三阶像散 W222 (waves)
          FCUR → 三阶场曲 W220 (waves)
          DIST → 三阶畸变 W311 (waves)
          AXCL → 轴向色差 (mm)
          LACL → 横向色差 (μm)

        所有操作数 Int1=0 表示对整个系统求和。
        """
        mfe = self.conn.mfe

        seidel_ops = [
            ("SPHA", "三阶球差 W040 (waves)"),
            ("COMA", "三阶慧差 W131 (waves)"),
            ("ASTI", "三阶像散 W222 (waves)"),
            ("FCUR", "三阶场曲 W220 (waves)"),
            ("DIST", "三阶畸变 W311 (waves)"),
            ("AXCL", "轴向色差 (mm)"),
            ("LACL", "横向色差 (μm)"),
        ]

        added = []
        for op_name, _ in seidel_ops:
            type_val = _resolve_operand_type(op_name)
            if type_val is None:
                continue
            pos = _safe(mfe, "NumberOfOperands", 0) + 1
            row = None
            try:
                row = mfe.InsertNewOperandAt(pos)
            except Exception:
                try:
                    row = mfe.AddOperand()
                except Exception:
                    continue
            if row is None:
                continue
            _set_row_operand_type(row, type_val)
            _safe_set_attr(row, "Weight", 0.0)
            _safe_set_attr(row, "Target", 0.0)
            _set_operand_int_param(row, 1, 0)  # surf=0: 全系统
            added.append((op_name, _safe(mfe, "NumberOfOperands", 0)))

        try:
            mfe.CalculateMeritFunction()
        except Exception:
            pass

        data = {}
        for op_name, rnum in added:
            try:
                data[op_name] = _safe(mfe.GetOperandAt(rnum), "Value", None)
            except Exception:
                data[op_name] = None

        # 清除
        for _, rnum in sorted(added, key=lambda x: x[1], reverse=True):
            try:
                mfe.DeleteOperandAt(rnum)
            except Exception:
                try:
                    mfe.RemoveOperandAt(rnum)
                except Exception:
                    pass

        # 构造结果
        aberrations = {}
        for op_name, label in seidel_ops:
            aberrations[op_name] = {
                "label": label,
                "value": round(data[op_name], 6) if data.get(op_name) is not None else None,
            }

        # 判断主导像差 (取绝对值最大的 Seidel 项)
        seidel_keys = ["SPHA", "COMA", "ASTI", "FCUR", "DIST"]
        dominant = None
        max_abs = 0.0
        for k in seidel_keys:
            v = data.get(k)
            if v is not None and abs(v) > max_abs:
                max_abs = abs(v)
                dominant = k

        result = {
            "aberrations": aberrations,
            "dominant_aberration": dominant,
            "dominant_value": round(max_abs, 6) if dominant else None,
            "tip": {
                "SPHA": "球差主导 → 检查正负透镜曲率分配，或释放更多曲率变量",
                "COMA": "慧差主导 → 检查孔径光阑位置，或调整弯月形状",
                "ASTI": "像散主导 → 调整透镜间距或视场采样",
                "FCUR": "场曲主导 → 引入平场元件或反向弯月透镜",
                "DIST": "畸变主导 → 对称结构可自消畸变，或在 MFE 加 DIST 约束",
            }.get(dominant, ""),
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_distortion(self, num_points: int = 5) -> str:
        """获取多视场归一化高度处的几何畸变 (%)。

        使用 MFE 操作数 DISC (distortion percentage):
          DISC(Int1=field, Int2=wave) → 该视场畸变百分比
        若 DISC 不可用，回退到 DIST (rays) 计算。
        """
        mfe = self.conn.mfe
        sys_data = self.conn.system_data
        num_fields = sys_data.Fields.NumberOfFields
        num_waves = sys_data.Wavelengths.NumberOfWavelengths
        primary_wave_idx = (num_waves + 1) // 2

        num_points = max(3, min(11, num_points))

        # 尝试逐视场畸变操作数：优先 DIMX（Int1=视场号，实测可靠），缺失时退回 DISC
        type_val_disc = _resolve_operand_type("DIMX") or _resolve_operand_type("DISC")
        type_val_dimx = _resolve_operand_type("DIMX")  # 最大畸变

        added = []

        if type_val_disc is not None:
            # 视场选择：默认逐个遍历全部视场（畸变本身就是逐视场量，无需抽样）。
            # 曾踩坑：固定 num_points=5 抽样 + round() 会跳过实际视场
            # （6 视场时映射为 1,2,4,5,6，12° 视场被漏掉），导致报告缺项。
            if num_fields <= 12:
                field_indices = list(range(1, num_fields + 1))
            else:
                field_indices = sorted({
                    max(1, min(num_fields, round(1 + (i - 1) * (num_fields - 1) / max(1, num_points - 1))))
                    for i in range(1, num_points + 1)
                })
            for field_idx in field_indices:
                pos = _safe(mfe, "NumberOfOperands", 0) + 1
                row = None
                try:
                    row = mfe.InsertNewOperandAt(pos)
                except Exception:
                    try:
                        row = mfe.AddOperand()
                    except Exception:
                        continue
                if row is None:
                    continue
                _set_row_operand_type(row, type_val_disc)
                # ChangeType 后重新获取引用
                row = _refetch_last_row(mfe) or row
                _safe_set_attr(row, "Weight", 0.0)
                _safe_set_attr(row, "Target", 0.0)
                # 用 DIMX(Int1=视场号, Int2=主波长, 第三参=0 相对畸变) 读逐视场畸变。
                # 曾用 DISC：写 col3=视场号读回成功，但实算值不随视场变化
                # （16° 实为 2.16% 却报 0.35%），不可用，已弃用。
                _set_operand_int_param(row, 1, field_idx)         # Int1 = 视场号
                _set_operand_int_param(row, 2, primary_wave_idx)  # Int2 = 主波长
                _set_operand_double_param(row, 3, 0.0)            # 0 = 相对畸变
                added.append(("DIMX", field_idx, _safe(mfe, "NumberOfOperands", 0)))

        # DIMX (最大畸变，wave=primary)
        dimx_row = None
        if type_val_dimx is not None:
            pos = _safe(mfe, "NumberOfOperands", 0) + 1
            row = None
            try:
                row = mfe.InsertNewOperandAt(pos)
            except Exception:
                try:
                    row = mfe.AddOperand()
                except Exception:
                    pass
            if row is not None:
                _set_row_operand_type(row, type_val_dimx)
                row = _refetch_last_row(mfe) or row
                _safe_set_attr(row, "Weight", 0.0)
                _safe_set_attr(row, "Target", 0.0)
                # Int1 = 0 → 全视场中的最大畸变；Int2 = 主波长
                # （曾把波长写进 Int1，等价于只算「视场2 = 14°」，把最大值报小了）
                _set_operand_int_param(row, 1, 0)
                _set_operand_int_param(row, 2, primary_wave_idx)
                _set_operand_double_param(row, 3, 0.0)   # 0 = 相对畸变
                dimx_row = _safe(mfe, "NumberOfOperands", 0)

        try:
            mfe.CalculateMeritFunction()
        except Exception:
            pass

        # 读取 DISC
        samples = []
        seen_fields = set()
        for op_name, field_idx, rnum in added:
            if field_idx in seen_fields:
                continue
            seen_fields.add(field_idx)
            val = None
            try:
                val = _safe(mfe.GetOperandAt(rnum), "Value", None)
            except Exception:
                pass
            # 获取该视场的实际坐标
            f_obj = sys_data.Fields.GetField(field_idx)
            _, fy, _ = self.conn.get_field_data(f_obj)
            samples.append({
                "field": field_idx,
                "field_y": fy,
                "distortion_pct": round(val, 5) if val is not None else None,
            })

        dimx_val = None
        if dimx_row is not None:
            try:
                dimx_val = _safe(mfe.GetOperandAt(dimx_row), "Value", None)
            except Exception:
                pass

        # 清除
        all_rows = [r for _, _, r in added] + ([dimx_row] if dimx_row else [])
        for rnum in sorted(set(all_rows), reverse=True):
            try:
                mfe.DeleteOperandAt(rnum)
            except Exception:
                try:
                    mfe.RemoveOperandAt(rnum)
                except Exception:
                    pass

        abs_vals = [s["distortion_pct"] for s in samples if s["distortion_pct"] is not None]
        max_abs_dist = round(max(abs(v) for v in abs_vals), 5) if abs_vals else None

        result = {
            "max_distortion_pct": dimx_val if dimx_val is not None else max_abs_dist,
            "samples": samples,
            "guidelines": {
                "visual_instrument": "< 5%",
                "microscope": "< 1%",
                "measurement_instrument": "< 0.1%",
            },
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_mtf(self, frequency: float, wave: int = 0) -> str:
        """获取指定空间频率处各视场的 MTF 值 (切向/弧矢)，并与衍射极限比较。

        操作数:
                    MTFT(Int1=wave, Param4=freq, Param6=normalized_field) → 切向 MTF
                    MTFS(Int1=wave, Param4=freq, Param6=normalized_field) → 弧矢 MTF

                注意：MF 文件中 MTFT/MTFS 的常见写法是 Int2=0, Param3=采样, Param4=频率,
                Param6=归一化视场高度。旧工具曾误用 MTHS，这会导致 MFE 与工具结果不一致。
        """
        mfe = self.conn.mfe
        sys_data = self.conn.system_data
        num_fields = sys_data.Fields.NumberOfFields
        num_waves = sys_data.Wavelengths.NumberOfWavelengths

        # 主波长
        primary_wave_idx = (num_waves + 1) // 2
        primary_wave_um = 0.5876
        try:
            w_obj = sys_data.Wavelengths.GetWavelength(primary_wave_idx)
            primary_wave_um, _ = self.conn.get_wavelength_data(w_obj)
        except Exception:
            pass

        wave_param = wave  # 0=多色

        type_val_mtft = _resolve_operand_type("MTFT")
        type_val_mtfs = _resolve_operand_type("MTFS")
        type_val_mths = _resolve_operand_type("MTHS")  # legacy fallback only

        if type_val_mtft is None and type_val_mtfs is None and type_val_mths is None:
            return json.dumps({"error": "当前 Zemax 版本不支持 MTFT/MTFS 操作数"}, ensure_ascii=False)

        field_norms = _normalized_field_heights(sys_data, self.conn)

        added = []  # (label, field_idx, row_num)

        def _add_mtf_row(type_val, label, field_idx, operand_name):
            pos = _safe(mfe, "NumberOfOperands", 0) + 1
            row = None
            try:
                row = mfe.InsertNewOperandAt(pos)
            except Exception:
                try:
                    row = mfe.AddOperand()
                except Exception:
                    return
            if row is None:
                return
            _set_row_operand_type(row, type_val)
            # ChangeType 后重新获取引用
            row = _refetch_last_row(mfe) or row
            _safe_set_attr(row, "Weight", 0.0)
            _safe_set_attr(row, "Target", 0.0)
            _wave_actual = max(1, wave_param) if wave_param > 0 else primary_wave_idx
            field_norm = field_norms.get(field_idx, 0.0)
            _write_mtf_operand_params(row, _wave_actual, float(frequency), field_norm)
            added.append((label, field_idx, _safe(mfe, "NumberOfOperands", 0), operand_name, field_norm))

        for fi in range(1, num_fields + 1):
            if type_val_mtft is not None:
                _add_mtf_row(type_val_mtft, "T", fi, "MTFT")
            if type_val_mtfs is not None:
                _add_mtf_row(type_val_mtfs, "S", fi, "MTFS")
            elif type_val_mths is not None:
                _add_mtf_row(type_val_mths, "S", fi, "MTHS")

        try:
            mfe.CalculateMeritFunction()
        except Exception:
            pass

        # 读取
        raw = {}
        for label, fi, rnum, _, _ in added:
            key = (fi, label)
            try:
                raw[key] = _safe(mfe.GetOperandAt(rnum), "Value", None)
            except Exception:
                raw[key] = None

        # 清除
        all_rows = [r for _, _, r, _, _ in added]
        for rnum in sorted(set(all_rows), reverse=True):
            try:
                mfe.DeleteOperandAt(rnum)
            except Exception:
                try:
                    mfe.RemoveOperandAt(rnum)
                except Exception:
                    pass

        # 理论衍射极限 MTF（单色，使用主波长）
        # 截止频率 f_c = 2*NA / λ (cycles/mm)
        image_na = None
        try:
            type_val_isna = _resolve_operand_type("ISNA")
            if type_val_isna is not None:
                pos = _safe(mfe, "NumberOfOperands", 0) + 1
                row = None
                try:
                    row = mfe.InsertNewOperandAt(pos)
                except Exception:
                    try:
                        row = mfe.AddOperand()
                    except Exception:
                        pass
                if row is not None:
                    _set_row_operand_type(row, type_val_isna)
                    _safe_set_attr(row, "Weight", 0.0)
                    mfe.CalculateMeritFunction()
                    isna_rnum = _safe(mfe, "NumberOfOperands", 0)
                    image_na = _safe(mfe.GetOperandAt(isna_rnum), "Value", None)
                    try:
                        mfe.DeleteOperandAt(isna_rnum)
                    except Exception:
                        try:
                            mfe.RemoveOperandAt(isna_rnum)
                        except Exception:
                            pass
        except Exception:
            pass

        cutoff_freq = None
        diffraction_limit_mtf = None
        if image_na and image_na > 0 and primary_wave_um:
            cutoff_freq = round(2 * image_na / (primary_wave_um * 1e-3), 1)  # λ in mm
            # 圆孔 OTF: MTF = (2/π) * [arccos(s) - s*sqrt(1-s²)], s = f/f_c
            s = frequency / cutoff_freq if cutoff_freq > 0 else 1.0
            if s >= 1.0:
                diffraction_limit_mtf = 0.0
            else:
                import math
                diffraction_limit_mtf = round((2 / math.pi) * (math.acos(s) - s * math.sqrt(1 - s ** 2)), 4)

        # 组装输出
        fields_data = []
        for fi in range(1, num_fields + 1):
            f_obj = sys_data.Fields.GetField(fi)
            _, fy, _ = self.conn.get_field_data(f_obj)
            entry = {
                "field": fi,
                "field_y": fy,
                "normalized_field": field_norms.get(fi, 0.0),
                "mtf_tangential": round(raw.get((fi, "T"), None) or 0, 4) if raw.get((fi, "T")) is not None else None,
                "mtf_sagittal": round(raw.get((fi, "S"), None) or 0, 4) if raw.get((fi, "S")) is not None else None,
            }
            if diffraction_limit_mtf is not None:
                entry["vs_diffraction_limit"] = {
                    "T": round(entry["mtf_tangential"] / diffraction_limit_mtf, 3) if entry["mtf_tangential"] is not None and diffraction_limit_mtf > 0 else None,
                    "S": round(entry["mtf_sagittal"] / diffraction_limit_mtf, 3) if entry["mtf_sagittal"] is not None and diffraction_limit_mtf > 0 else None,
                }
            fields_data.append(entry)

        result = {
            "frequency_cycles_per_mm": frequency,
            "operand_mapping": "MTFT/MTFS reference-style: Int1=wave, Int2=0, Param3=sampling, Param4=frequency, Param6=normalized_field",
            "image_na": image_na,
            "cutoff_frequency": cutoff_freq,
            "diffraction_limit_mtf": diffraction_limit_mtf,
            "fields": fields_data,
        }
        warnings = _mtf_result_warnings(fields_data)
        if type_val_mtfs is None and type_val_mths is not None:
            warnings.append("当前版本未解析到 MTFS，已回退到 legacy MTHS；结果需和 Zemax MFE/图窗交叉验证。")
        if warnings:
            result["warnings"] = warnings

        return json.dumps(result, ensure_ascii=False, indent=2)

    def check_field_illumination(self, wave: int = 0, threshold: float = 0.05) -> str:
        """检查各视场相对照度，捕捉 0 光强/严重渐晕视场。"""
        mfe = self.conn.mfe
        sys_data = self.conn.system_data
        num_fields = sys_data.Fields.NumberOfFields
        num_waves = sys_data.Wavelengths.NumberOfWavelengths
        primary_wave_idx = (num_waves + 1) // 2
        wave_idx = max(1, int(wave)) if wave and wave > 0 else primary_wave_idx
        threshold = max(0.0, float(threshold))

        type_val_reli = _resolve_operand_type("RELI")
        if type_val_reli is None:
            return json.dumps(
                {
                    "error": "当前 Zemax 版本不支持 RELI 操作数，无法自动检查相对照度。",
                    "recommendation": "请在分析图中检查 Relative Illumination/Vignetting，并不要把 0 光强视场的点列图/MTF 当作有效验收。",
                },
                ensure_ascii=False,
            )

        added = []
        for fi in range(1, num_fields + 1):
            pos = _safe(mfe, "NumberOfOperands", 0) + 1
            row = None
            try:
                row = mfe.InsertNewOperandAt(pos)
            except Exception:
                try:
                    row = mfe.AddOperand()
                except Exception:
                    row = None
            if row is None:
                continue
            _set_row_operand_type(row, type_val_reli)
            row = _refetch_last_row(mfe) or row
            _safe_set_attr(row, "Target", 0.0)
            _safe_set_attr(row, "Weight", 0.0)
            # MFRefer1.MF uses RELI field wave Hx=1.0. Keep that convention.
            _write_operand_param(row, 1, fi)
            _write_operand_param(row, 2, wave_idx)
            _write_operand_param(row, 3, 1.0)
            added.append((fi, _safe(mfe, "NumberOfOperands", 0)))

        try:
            mfe.CalculateMeritFunction()
        except Exception:
            pass

        fields = []
        for fi, rnum in added:
            try:
                value = _safe(mfe.GetOperandAt(rnum), "Value", None)
            except Exception:
                value = None
            f_obj = sys_data.Fields.GetField(fi)
            _, fy, _ = self.conn.get_field_data(f_obj)
            numeric = value if isinstance(value, (int, float)) and math.isfinite(value) else None
            status = "unknown"
            if numeric is not None:
                if numeric <= 1e-6:
                    status = "zero"
                elif numeric < threshold:
                    status = "low"
                else:
                    status = "ok"
            fields.append({
                "field": fi,
                "field_y": fy,
                "wave": wave_idx,
                "relative_illumination": round(numeric, 6) if numeric is not None else value,
                "status": status,
            })

        finite_values = [
            f["relative_illumination"] for f in fields
            if isinstance(f.get("relative_illumination"), (int, float)) and math.isfinite(f["relative_illumination"])
        ]
        non_axis_fields = [f for f in fields if isinstance(f.get("field_y"), (int, float)) and abs(f["field_y"]) > 1e-9]
        relis_are_degenerate = False
        if len(finite_values) >= 2 and non_axis_fields:
            relis_are_degenerate = max(finite_values) - min(finite_values) <= 1e-9 and abs(finite_values[0] - 1.0) <= 1e-9
        if relis_are_degenerate:
            for field in non_axis_fields:
                field["status"] = "unknown"

        for _, rnum in sorted(added, key=lambda item: item[1], reverse=True):
            try:
                mfe.DeleteOperandAt(rnum)
            except Exception:
                try:
                    mfe.RemoveOperandAt(rnum)
                except Exception:
                    pass

        problematic = [f for f in fields if f["status"] in ("zero", "low", "unknown")]
        result = {
            "wave": wave_idx,
            "threshold": threshold,
            "all_fields_illuminated": len(problematic) == 0,
            "method": "RELI temporary operands",
            "method_confidence": "low" if relis_are_degenerate else "normal",
            "fields": fields,
        }
        if problematic:
            result["warnings"] = [
                "存在 0 光强、低相对照度或无法判定的视场；这些视场的 SPT/MTF/点列图不可直接作为有效验收。",
                "优先检查视场设置、渐晕因子、Ray Aiming、孔径/光阑、面口径和是否有光线被遮拦。",
            ]
        if relis_are_degenerate:
            result.setdefault("warnings", []).insert(
                0,
                "RELI 对所有视场返回完全相同的 1.0，疑似参数映射或当前系统设置使 RELI 退化；工具不能证明离轴视场已通光，需结合相对照度图、Spot Diagram 强度或光线瞄准/渐晕诊断。",
            )
        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_mtf_curve(self, num_points: int = 5, max_frequency: float = 0, wave: int = 0) -> str:
        """在多个空间频率点计算 MTF，返回完整曲线数据以及衍射极限理论曲线用于对比。"""
        import math
        mfe = self.conn.mfe
        sys_data = self.conn.system_data
        num_fields = sys_data.Fields.NumberOfFields
        num_waves = sys_data.Wavelengths.NumberOfWavelengths

        primary_wave_idx = (num_waves + 1) // 2
        primary_wave_um = 0.5876
        try:
            w_obj = sys_data.Wavelengths.GetWavelength(primary_wave_idx)
            primary_wave_um, _ = self.conn.get_wavelength_data(w_obj)
        except Exception:
            pass

        # 先获取 ISNA 以确定截止频率
        image_na = None
        type_val_isna = _resolve_operand_type("ISNA")
        if type_val_isna is not None:
            pos = _safe(mfe, "NumberOfOperands", 0) + 1
            row = None
            try:
                row = mfe.InsertNewOperandAt(pos)
            except Exception:
                try:
                    row = mfe.AddOperand()
                except Exception:
                    pass
            if row is not None:
                _set_row_operand_type(row, type_val_isna)
                _safe_set_attr(row, "Weight", 0.0)
                mfe.CalculateMeritFunction()
                isna_rnum = _safe(mfe, "NumberOfOperands", 0)
                image_na = _safe(mfe.GetOperandAt(isna_rnum), "Value", None)
                try:
                    mfe.DeleteOperandAt(isna_rnum)
                except Exception:
                    try:
                        mfe.RemoveOperandAt(isna_rnum)
                    except Exception:
                        pass

        cutoff_freq = None
        if image_na and image_na > 0 and primary_wave_um:
            cutoff_freq = round(2 * image_na / (primary_wave_um * 1e-3), 1)

        # 确定频率范围
        num_points = max(3, min(10, num_points))
        if max_frequency <= 0:
            if cutoff_freq:
                max_frequency = cutoff_freq
            else:
                max_frequency = 100.0
        frequencies = [round(max_frequency * i / (num_points - 1), 2) for i in range(1, num_points)]
        # 首点从 1/num_points 开始，避免 0 频率无意义
        # 末点取截止频率 * 0.95（或 max_frequency）
        if cutoff_freq and max_frequency >= cutoff_freq:
            frequencies[-1] = round(cutoff_freq * 0.95, 2)

        type_val_mtft = _resolve_operand_type("MTFT")
        type_val_mtfs = _resolve_operand_type("MTFS")
        type_val_mths = _resolve_operand_type("MTHS")  # legacy fallback only

        if type_val_mtft is None and type_val_mtfs is None and type_val_mths is None:
            return json.dumps({"error": "当前 Zemax 版本不支持 MTFT/MTFS 操作数"}, ensure_ascii=False)

        wave_param = max(1, wave) if wave > 0 else primary_wave_idx
        field_norms = _normalized_field_heights(sys_data, self.conn)

        # 逐频率点调用 get_mtf 逻辑（重用核心逻辑，避免代码重复）
        curve_data = []
        for freq in frequencies:
            # 衍射极限理论值
            dl_mtf = None
            if cutoff_freq and cutoff_freq > 0:
                s = freq / cutoff_freq
                if s >= 1.0:
                    dl_mtf = 0.0
                else:
                    dl_mtf = round((2 / math.pi) * (math.acos(s) - s * math.sqrt(1 - s ** 2)), 4)

            # 添加每个视场的 MTFT + MTHS
            added = []

            def _add_row(type_val, label, fi):
                pos = _safe(mfe, "NumberOfOperands", 0) + 1
                row = None
                try:
                    row = mfe.InsertNewOperandAt(pos)
                except Exception:
                    try:
                        row = mfe.AddOperand()
                    except Exception:
                        return
                if row is None:
                    return
                _set_row_operand_type(row, type_val)
                row = _refetch_last_row(mfe) or row
                _safe_set_attr(row, "Weight", 0.0)
                _safe_set_attr(row, "Target", 0.0)
                _set_operand_int_param(row, 1, wave_param)
                _write_mtf_operand_params(row, wave_param, float(freq), field_norms.get(fi, 0.0))
                added.append((label, fi, _safe(mfe, "NumberOfOperands", 0)))

            for fi in range(1, num_fields + 1):
                if type_val_mtft is not None:
                    _add_row(type_val_mtft, "T", fi)
                if type_val_mtfs is not None:
                    _add_row(type_val_mtfs, "S", fi)
                elif type_val_mths is not None:
                    _add_row(type_val_mths, "S", fi)

            try:
                mfe.CalculateMeritFunction()
            except Exception:
                pass

            raw = {}
            for label, fi, rnum in added:
                try:
                    raw[(fi, label)] = _safe(mfe.GetOperandAt(rnum), "Value", None)
                except Exception:
                    raw[(fi, label)] = None

            all_rows = [r for _, _, r in added]
            for rnum in sorted(set(all_rows), reverse=True):
                try:
                    mfe.DeleteOperandAt(rnum)
                except Exception:
                    try:
                        mfe.RemoveOperandAt(rnum)
                    except Exception:
                        pass

            fields_at_freq = []
            for fi in range(1, num_fields + 1):
                f_obj = sys_data.Fields.GetField(fi)
                _, fy, _ = self.conn.get_field_data(f_obj)
                entry = {
                    "field": fi,
                    "field_y": fy,
                    "normalized_field": field_norms.get(fi, 0.0),
                    "T": round(raw.get((fi, "T")) or 0, 4) if raw.get((fi, "T")) is not None else None,
                    "S": round(raw.get((fi, "S")) or 0, 4) if raw.get((fi, "S")) is not None else None,
                }
                if dl_mtf is not None and dl_mtf > 0:
                    entry["T_vs_DL"] = round((entry["T"] or 0) / dl_mtf, 3)
                    entry["S_vs_DL"] = round((entry["S"] or 0) / dl_mtf, 3)
                fields_at_freq.append(entry)

            curve_data.append({
                "frequency": freq,
                "diffraction_limit": dl_mtf,
                "fields": fields_at_freq,
            })

        # 汇总：找出最差视场（全频率平均 T/S 最低）
        worst_field = None
        min_avg = 1.0
        for fi in range(1, num_fields + 1):
            vals = []
            for pt in curve_data:
                for fe in pt["fields"]:
                    if fe["field"] == fi:
                        if fe["T"] is not None:
                            vals.append(fe["T"])
                        if fe["S"] is not None:
                            vals.append(fe["S"])
            if vals:
                avg = sum(vals) / len(vals)
                if avg < min_avg:
                    min_avg = avg
                    worst_field = fi

        result = {
            "image_na": image_na,
            "cutoff_frequency": cutoff_freq,
            "primary_wavelength_um": primary_wave_um,
            "operand_mapping": "MTFT/MTFS reference-style: Int1=wave, Int2=0, Param3=sampling, Param4=frequency, Param6=normalized_field",
            "num_fields": num_fields,
            "worst_field": worst_field,
            "curve": curve_data,
        }
        warnings = []
        if type_val_mtfs is None and type_val_mths is not None:
            warnings.append("当前版本未解析到 MTFS，已回退到 legacy MTHS；结果需和 Zemax MFE/图窗交叉验证。")
        for pt in curve_data:
            warnings.extend(_mtf_result_warnings([
                {
                    "field": f["field"],
                    "mtf_tangential": f.get("T"),
                    "mtf_sagittal": f.get("S"),
                }
                for f in pt.get("fields", [])
            ]))
        if warnings:
            result["warnings"] = sorted(set(warnings))
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ---- ZOS-API Analysis 图窗数据 ----

    def export_analysis_data(self, analysis: str, settings: dict | None = None,
                             keep_window: bool = False, export_image: bool = True,
                             export_text: bool = True) -> str:
        """运行指定 Analysis 并返回结构化结果与导出文件。"""
        result = self._run_analysis_capture(
            analysis,
            settings_overrides=settings or {},
            keep_window=bool(keep_window),
            export_image=bool(export_image),
            export_text=bool(export_text),
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_relative_illumination_data(self, wave: int = 0, threshold: float = 0.05) -> str:
        """通过 Relative Illumination Analysis 获取通光状态。"""
        wave_idx = self._analysis_wave_index(wave)
        result = self._run_analysis_capture(
            "relative_illumination",
            settings_overrides={"wave": wave_idx},
            export_basename="relative_illumination",
        )
        result["wave"] = wave_idx
        result["threshold"] = max(0.0, float(threshold or 0.05))

        parsed = _parse_relative_illumination_from_capture(result)
        if parsed:
            result.update(parsed)
        else:
            series_rows = _series_rows_from_capture(result)
            if series_rows:
                fields = []
                for row in series_rows:
                    y_value = row.get("x")
                    rel_value = _first_numeric(row.get("values", []))
                    if rel_value is None:
                        continue
                    fields.append({
                        "field_y": y_value,
                        "relative_illumination": rel_value,
                        "status": _illumination_status(rel_value, result["threshold"]),
                    })
                if fields:
                    result["fields"] = fields

        fields = result.get("fields", [])
        finite = [f.get("relative_illumination") for f in fields if isinstance(f.get("relative_illumination"), (int, float))]
        blocked = [f for f in fields if f.get("status") in ("zero", "low", "blocked")]
        result["all_fields_illuminated"] = bool(fields) and not blocked
        result["blocked_fields"] = blocked
        if finite:
            result["min_relative_illumination"] = min(finite)
            result["max_relative_illumination"] = max(finite)
            result["method_confidence"] = "low" if max(finite) - min(finite) <= 1e-9 else "normal"
        else:
            result["method_confidence"] = "low"
        result["drop_events"] = _illumination_drop_events(fields)
        if blocked or result.get("drop_events"):
            result["warnings"] = sorted(set(result.get("warnings", []) + [
                "存在 0 光强、低相对照度或边缘相对照度骤降；这些视场的点列图/MTF 不能作为有效像质验收。"
            ]))
        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_vignetting_diagram_data(self) -> str:
        """运行 Vignetting Diagram，用于定位遮拦/渐晕。"""
        result = self._run_analysis_capture("vignetting_diagram", export_basename="vignetting_diagram")
        result["interpretation"] = {
            "purpose": "定位 19-20° 视场的首个遮拦面、渐晕因子或孔径限制。",
            "next_step": "若文本或图像显示某面边缘截断，优先只调整该面 clear/semi-diameter 或相关渐晕设置。",
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_spot_diagram_data(self, field: int = 0, wave: int = 0,
                              ray_density: int | None = None,
                              show_airy_disk: bool = True) -> str:
        """通过 Standard Spot Diagram Analysis 获取点列图数据。"""
        settings = {
            "field": int(field or 0),
            "wave": int(wave or 0),
            "ShowAiryDisk": bool(show_airy_disk),
        }
        if ray_density is not None:
            settings["RayDensity"] = int(ray_density)
        result = self._run_analysis_capture("standard_spot", settings_overrides=settings, export_basename="spot_diagram")
        spot_fields = _spot_data_from_capture(result, self.conn.system_data, self.conn)
        if spot_fields:
            result["fields"] = spot_fields
        else:
            parsed = _parse_spot_text_from_capture(result)
            if parsed:
                result["fields"] = parsed
        for item in result.get("fields", []):
            rms = item.get("rms_radius_um") or item.get("rms_radius_lens_units")
            geo = item.get("geo_radius_um") or item.get("geo_radius_lens_units")
            item["is_empty"] = _is_zero_number(rms) and _is_zero_number(geo)
            if item["is_empty"]:
                item["warning"] = "spot 数据全 0，需结合相对照度判断是否为空视场/无光线。"
        if any(item.get("is_empty") for item in result.get("fields", [])):
            result["warnings"] = sorted(set(result.get("warnings", []) + [
                "存在 RMS/GEO 全 0 的点列图视场；若相对照度也为 0，应判定为空视场而非优秀像质。"
            ]))
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _airy_radius_um(self) -> float | None:
        """艾里斑半径 (μm) = 0.61·λ/NA，与 Zemax 图中标注的 Airy 半径一致。

        近轴关系 NA = sin(atan(EPD / (2·EFFL)))。注意用 sin 而非 tan：
        常见的 1.22·λ·(EFFL/EPD) 写法等价于用 tan，会比 Zemax 的 NA 偏大，
        导致艾里半径偏小（实测 1.667 vs 1.705 μm）。
        """
        try:
            wls = self.conn.system_data.Wavelengths
            lam = None
            best_weight = -1.0
            for i in range(1, int(wls.NumberOfWavelengths) + 1):
                w = wls.GetWavelength(i)
                weight = float(getattr(w, "Weight", 1.0) or 1.0)
                if weight > best_weight:
                    best_weight = weight
                    lam = float(w.Wavelength)
            epd = float(self.conn.system.SystemData.Aperture.ApertureValue)
            first_order = json.loads(self.get_first_order_data())
            effl = float(first_order["first_order_data"]["EFFL"]["value"])
            if not (lam and epd > 0 and effl > 0):
                return None
            na = math.sin(math.atan(epd / (2.0 * effl)))
            if na <= 0:
                return None
            return round(0.61 * lam / na, 4)
        except Exception:
            return None

    def export_spot_diagram_image(self, file_path: str | None = None,
                                  show_airy: bool = True, wave: int = 0) -> str:
        """把点列图渲染成 PNG（固定文件名、覆盖保存），并叠加艾里斑参考圆。

        ZOS-API 的分析类没有位图导出接口，因此按真实光线落点自行渲染；
        艾里斑半径按 0.61·λ/NA 计算，与 Zemax 图中 Airy Disk 圈一致。
        """
        settings = {
            "field": 0,
            "wave": int(wave or 0),
            "ShowAiryDisk": bool(show_airy),
        }
        capture = self._run_analysis_capture(
            "standard_spot", settings_overrides=settings, export_basename="spot_diagram"
        )
        results = capture.get("results") or {}
        spot_data = results.get("spot_data") or {}
        if not spot_data.get("fields"):
            spot_data = {"fields": _parse_spot_text_from_capture(capture) or []}
        fields = spot_data.get("fields") or []
        if not fields:
            return json.dumps(
                {
                    "ok": False,
                    "error": "无法取得点列图数据（可能光线追迹失败或数据为空）",
                    "exports": capture.get("exports"),
                },
                ensure_ascii=False,
            )

        airy_um = self._airy_radius_um() if show_airy else None
        airy_mm = (airy_um / 1000.0) if airy_um else None

        # 每视场 RMS / GEO（µm）都取自点列图分析自身的 spot_data，
        # 这样图上数值与 Zemax 原生点列图逐值一致（实测 field1 RMS=9.767、GEO=21.46 完全吻合）。
        # 注意：不要用 get_image_quality 的 rms_spot_um —— 它的采样口径不同，
        # 同一系统离线视场会给出 17.70 而点列图是 25.64，混用会误导。
        rms_um_by_field: dict[int, float] = {}
        geo_um_by_field: dict[int, float] = {}
        try:
            factor = _spot_radius_unit_factor(spot_data, results.get("spot_ray_points"))
            for item in fields:
                fid = int(item.get("field") or 0)
                waves_ = item.get("waves") or []
                rms_vals = [
                    abs(float(w.get("rms_radius_lens_units")))
                    for w in waves_
                    if isinstance(w.get("rms_radius_lens_units"), (int, float))
                ]
                geo_vals = [
                    abs(float(w.get("geo_radius_lens_units")))
                    for w in waves_
                    if isinstance(w.get("geo_radius_lens_units"), (int, float))
                ]
                if rms_vals:
                    rms_um_by_field[fid] = max(rms_vals) * factor
                if geo_vals:
                    geo_um_by_field[fid] = max(geo_vals) * factor
        except Exception:
            pass

        current_file = self._current_system_file()
        base_dir = current_file.parent if current_file else _WORKSPACE_ROOT
        out_dir = base_dir / "layouts"
        out_dir.mkdir(parents=True, exist_ok=True)
        target = Path(file_path) if file_path else out_dir / "spot_diagram.png"
        _delete_file_quietly(target)
        _render_spot_summary_png(
            spot_data, target, results.get("spot_ray_points"), airy_mm,
            rms_um_by_field=rms_um_by_field, geo_um_by_field=geo_um_by_field,
        )

        # 清掉本次运行产生的中间预览图（与最终 PNG 内容重复），原生 txt 保留供核对
        try:
            tmp_img = (capture.get("exports") or {}).get("image_path")
            if tmp_img and Path(tmp_img).resolve() != target.resolve():
                _delete_file_quietly(Path(tmp_img))
        except Exception:
            pass

        summary = []
        for item in fields:
            # 原始 spot_data 的每一项只有 field 与 waves，没有顶层 rms/field_y。
            # RMS 优先用 get_image_quality 的值（已验证），退而求其次从 waves 取最大。
            fid = int(item.get("field") or 0)
            waves_ = item.get("waves") or []
            rms_vals = [
                float(w.get("rms_radius_lens_units"))
                for w in waves_
                if isinstance(w.get("rms_radius_lens_units"), (int, float))
            ]
            rms = rms_um_by_field.get(fid) or (
                item.get("rms_radius_um")
                or item.get("rms_radius_lens_units")
                or (max(rms_vals) if rms_vals else None)
            )
            fy = _finite_float(item.get("field_y"))
            if fy is None:
                try:
                    fobj = self.conn.system_data.Fields.GetField(fid)
                    _fx, fy, _wt = self.conn.get_field_data(fobj)
                    fy = _finite_float(fy)
                except Exception:
                    fy = None
            summary.append(
                {
                    "field": item.get("field"),
                    "field_y": fy,
                    "rms_um": _finite_float(rms),
                    "geo_um": _finite_float(geo_um_by_field.get(fid)),
                }
            )
        kind = _classify_export_file(target)
        return json.dumps(
            {
                "ok": kind == "png",
                "image_path": str(target) if kind == "png" else None,
                "kind": kind,
                "bytes": target.stat().st_size if target.exists() else 0,
                "show_airy": bool(show_airy),
                "airy_radius_um": airy_um,
                "settings_report": capture.get("settings_report"),
                "fields": summary,
                "note": (
                    "ZOS-API 无分析位图导出，图像由真实光线落点渲染；"
                    "每格下方列出 RMS / GEO 半径（µm）与标尺；艾里斑按 0.61·λ/NA 绘制（与 Zemax 一致）。"
                ),
            },
            ensure_ascii=False,
        )

    def get_fft_mtf_vs_field(self, frequencies: list | None = None, wave: int = 0,
                             sample_size: int | None = None, remove_vignetting: bool = False) -> str:
        """通过 FFT MTF vs Field Analysis 获取 MTF 随视场变化。"""
        freqs = [float(f) for f in (frequencies or [50, 100, 200, 300]) if f is not None][:6]
        settings = {
            "wave": int(wave or 0),
            "frequencies": freqs,
            "RemoveVignetting": bool(remove_vignetting),
        }
        if sample_size is not None:
            settings["SampleSize"] = int(sample_size)
        result = self._run_analysis_capture("fft_mtf_vs_field", settings_overrides=settings, export_basename="fft_mtf_vs_field")
        result["frequencies"] = freqs
        result["remove_vignetting"] = bool(remove_vignetting)
        result["mtf_vs_field_summary"] = _mtf_vs_field_summary_from_text(
            result,
            freqs,
            self.conn.system_data,
            self.conn,
        )
        warnings = _mtf_series_warnings(result)
        if warnings:
            result["warnings"] = sorted(set(result.get("warnings", []) + warnings))
        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_ray_fan_data(self, field: int = 0, wave: int = 0, number_of_rays: int | None = None) -> str:
        """通过 Ray Fan Analysis 获取光扇数据。"""
        return self._fan_analysis_json("ray_fan", field, wave, number_of_rays)

    def get_opd_fan_data(self, field: int = 0, wave: int = 0, number_of_rays: int | None = None) -> str:
        """通过 OPD Fan Analysis 获取光程差光扇数据。"""
        return self._fan_analysis_json("opd_fan", field, wave, number_of_rays)

    def get_longitudinal_aberration_data(self) -> str:
        """获取轴向相差/球色差分析数据。"""
        result = self._run_analysis_capture("longitudinal_aberration", export_basename="longitudinal_aberration")
        result.update(_longitudinal_summary_from_capture(result))
        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_lateral_color_data(self, use_real_rays: bool = True, show_airy_disk: bool = True) -> str:
        """获取垂轴色差分析数据。"""
        result = self._run_analysis_capture(
            "lateral_color",
            settings_overrides={"UseRealRays": bool(use_real_rays), "ShowAiryDisk": bool(show_airy_disk), "AllWavelengths": True},
            export_basename="lateral_color",
        )
        result["color_warning"] = _color_series_warning(result)
        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_field_curvature_distortion_data(self, wave: int = 0, ignore_vignette: bool = False) -> str:
        """获取场曲/畸变曲线。"""
        result = self._run_analysis_capture(
            "field_curvature_distortion",
            settings_overrides={"wave": int(wave or 0), "IgnoreVignette": bool(ignore_vignette)},
            export_basename="field_curvature_distortion",
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_wavefront_map_data(self, field: int = 0, wave: int = 0, sampling: int | None = None) -> str:
        """获取波前图 DataGrid。"""
        settings = {"field": int(field or 0), "wave": int(wave or 0)}
        if sampling is not None:
            settings["Sampling"] = int(sampling)
        result = self._run_analysis_capture("wavefront_map", settings_overrides=settings, export_basename="wavefront_map")
        return json.dumps(result, ensure_ascii=False, indent=2)

    def generate_validation_report(self, frequencies: list | None = None, include_heavy: bool = False) -> str:
        """批量运行常用分析，形成验收报告。"""
        report = {
            "ok": True,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "system_file": str(self._current_system_file()) if self._current_system_file() else None,
            "analyses": {},
            "summary": [],
        }
        calls = [
            ("relative_illumination", lambda: json.loads(self.get_relative_illumination_data())),
            ("spot_diagram", lambda: json.loads(self.get_spot_diagram_data())),
            ("fft_mtf_vs_field", lambda: json.loads(self.get_fft_mtf_vs_field(frequencies=frequencies))),
            ("ray_fan", lambda: json.loads(self.get_ray_fan_data())),
            ("longitudinal_aberration", lambda: json.loads(self.get_longitudinal_aberration_data())),
            ("lateral_color", lambda: json.loads(self.get_lateral_color_data())),
            ("field_curvature_distortion", lambda: json.loads(self.get_field_curvature_distortion_data())),
        ]
        if include_heavy:
            calls.append(("wavefront_map", lambda: json.loads(self.get_wavefront_map_data())))
        for name, fn in calls:
            try:
                report["analyses"][name] = fn()
            except Exception as e:
                report["analyses"][name] = {"error": str(e)}
                report["ok"] = False
        rel = report["analyses"].get("relative_illumination", {})
        if rel.get("blocked_fields"):
            report["summary"].append("存在 0/低相对照度视场；先修通光，再评价 spot/MTF。")
        spot = report["analyses"].get("spot_diagram", {})
        if any(item.get("is_empty") for item in spot.get("fields", [])):
            report["summary"].append("点列图存在空视场，需结合相对照度判定。")
        if not report["summary"]:
            report["summary"].append("未发现自动化硬失败；仍需结合图像和设计指标判断是否收敛。")
        return json.dumps(report, ensure_ascii=False, indent=2)

    def _fan_analysis_json(self, analysis_key: str, field: int, wave: int, number_of_rays: int | None) -> str:
        settings = {"field": int(field or 0), "wave": int(wave or 0)}
        if number_of_rays is not None:
            settings["NumberOfRays"] = int(number_of_rays)
        result = self._run_analysis_capture(analysis_key, settings_overrides=settings, export_basename=analysis_key)
        result["valid_sample_fraction"] = _fan_valid_fraction_from_capture(result)
        if result["valid_sample_fraction"] is not None and result["valid_sample_fraction"] < 0.8:
            result["warnings"] = sorted(set(result.get("warnings", []) + [
                "光扇文本中缺失采样比例较高，可能存在遮拦、渐晕或追迹失败。"
            ]))
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _analysis_wave_index(self, wave: int = 0) -> int:
        num_waves = _safe(self.conn.system_data.Wavelengths, "NumberOfWavelengths", 1) or 1
        return max(1, min(int(wave), num_waves)) if wave and wave > 0 else (num_waves + 1) // 2

    def _run_analysis_capture(self, analysis_key: str, settings_overrides: dict | None = None,
                              export_basename: str | None = None, keep_window: bool = False,
                              export_image: bool = True, export_text: bool = True,
                              max_points: int = 2000) -> dict:
        """Create/apply an Analysis and capture structured results, text, and export files."""
        system = self.conn.system
        analyses = getattr(system, "Analyses", None)
        if analyses is None:
            return {"error": "system.Analyses 不可用，无法运行 Analysis 图窗。"}

        canonical = _canonical_analysis_key(analysis_key)
        analysis = None
        try:
            analysis = _new_analysis(analyses, canonical)
            if analysis is None:
                return {"error": f"无法创建 Analysis: {analysis_key}"}
            settings = None
            settings_report = {}
            try:
                settings = analysis.GetSettings()
                settings = _cast_analysis_settings(settings, canonical)
                settings_report = _apply_analysis_settings(settings, settings_overrides or {})
            except Exception as e:
                settings_report = {"error": str(e)}

            try:
                analysis.ApplyAndWaitForCompletion()
            except Exception:
                try:
                    analysis.Apply()
                    analysis.WaitForCompletion()
                except Exception as e:
                    return {"error": f"Analysis 执行失败: {e}", "analysis": canonical, "settings_report": settings_report}

            results = None
            try:
                results = analysis.GetResults()
            except Exception:
                results = None

            export_paths = self._export_analysis_outputs(analysis, results, export_basename or canonical, export_image, export_text)
            payload = {
                "ok": True,
                "analysis": canonical,
                "analysis_name": _jsonable_number(_safe(analysis, "GetAnalysisName", None) or _safe(analysis, "Title", None)),
                "settings_used": _settings_snapshot(settings) if settings is not None else {},
                "settings_report": settings_report,
                "exports": export_paths,
            }
            if results is not None:
                payload["results"] = _analysis_results_to_dict(results, max_points=max_points)
            if canonical == "standard_spot":
                self._attach_spot_ray_trace_points(payload)
            text = _read_exported_text(export_paths.get("text_path"))
            if text:
                payload["text_preview"] = text[:4000]
                payload["text_stats"] = _text_result_stats(text)
            if export_image:
                _attach_rendered_fallback_image(payload, canonical)
            warnings = _analysis_capture_warnings(payload)
            if warnings:
                payload["warnings"] = warnings
            return payload
        finally:
            if analysis is not None and not keep_window:
                try:
                    analysis.Close()
                except Exception:
                    pass

    def _export_analysis_outputs(self, analysis, results, basename: str,
                                 export_image: bool, export_text: bool) -> dict:
        current_file = self._current_system_file()
        base_dir = current_file.parent if current_file else _WORKSPACE_ROOT
        export_dir = base_dir / "layouts" / "analysis"
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in basename)
        export_info: dict[str, object] = {"directory": str(export_dir)}

        if export_text and results is not None:
            text_path = export_dir / f"{safe_name}_{timestamp}.txt"
            try:
                ok = results.GetTextFile(str(text_path))
                export_info["text_path"] = str(text_path)
                export_info["text_export_ok"] = bool(ok) if ok is not None else text_path.exists()
            except Exception as e:
                export_info["text_export_error"] = str(e)

        if export_image:
            export_info.update(_export_verified_analysis_image(analysis, export_dir, f"{safe_name}_{timestamp}"))
        return export_info

    def _attach_spot_ray_trace_points(self, payload: dict, rings: int = 4) -> None:
        """Add real REAX/REAY sampled spot points for fallback plotting.

        OpticStudio 2018 often exposes only RMS/GEO SpotData through Analysis
        results, while the GUI spot diagram itself is drawn from traced ray
        intercepts. Sampling REAX/REAY through GetOperandValue gives the fallback
        PNG physically meaningful point locations instead of synthetic RMS blobs.
        """
        results = payload.get("results")
        if not isinstance(results, dict):
            return
        spot_data = results.get("spot_data")
        if not isinstance(spot_data, dict):
            return
        try:
            mfe = self.conn.mfe
            sys_data = self.conn.system_data
            fields_data = sys_data.Fields
            wavelengths_data = sys_data.Wavelengths
            num_fields = int(fields_data.NumberOfFields)
            num_waves = int(wavelengths_data.NumberOfWavelengths)
            last_surface = int(self.conn.lde.NumberOfSurfaces) - 1
            reax = getattr(self.conn.constants, "MeritOperandType_REAX", 124)
            reay = getattr(self.conn.constants, "MeritOperandType_REAY", 125)
        except Exception as e:
            results["spot_ray_points_error"] = str(e)
            return

        field_norm = _normalized_field_coordinates(sys_data, self.conn)
        field_raw = _raw_field_coordinates(sys_data, self.conn)
        pupil_points = _spot_pupil_sample_points(max(1, int(rings)))
        traced_fields = []
        total_points = 0
        missing = 0
        for field_idx in range(1, num_fields + 1):
            hx, hy = field_norm.get(field_idx, (0.0, 0.0))
            fx_raw, fy_raw = field_raw.get(field_idx, (0.0, 0.0))
            waves = []
            for wave_idx in range(1, num_waves + 1):
                points = []
                for px, py in pupil_points:
                    try:
                        x = _jsonable_number(mfe.GetOperandValue(reax, last_surface, wave_idx, hx, hy, px, py, 0.0, 0.0))
                        y = _jsonable_number(mfe.GetOperandValue(reay, last_surface, wave_idx, hx, hy, px, py, 0.0, 0.0))
                    except Exception:
                        missing += 1
                        continue
                    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not math.isfinite(x) or not math.isfinite(y):
                        missing += 1
                        continue
                    points.append({"px": px, "py": py, "x": x, "y": y})
                    total_points += 1
                waves.append({"wave": wave_idx, "points": points})
            traced_fields.append({"field": field_idx, "hx": hx, "hy": hy, "field_x": fx_raw, "field_y": fy_raw, "waves": waves})
        results["spot_ray_points"] = {
            "surface": last_surface,
            "operand_x": "REAX",
            "operand_y": "REAY",
            "coordinate_units": "lens_units",
            "pupil_sample_points": len(pupil_points),
            "point_count": total_points,
            "missing_count": missing,
            "fields": traced_fields,
        }

    def check_manufacturability(self) -> str:
        """对当前系统每个透镜进行可制造性检查：边缘厚度、CT/ET比值、弯曲因子、最小曲率半径等。"""
        import math
        lde = self.conn.lde
        num_surfs = lde.NumberOfSurfaces  # 包含物面(0)和像面(last)
        last_surf = num_surfs - 1

        # 读取所有表面数据
        surfaces = []
        for i in range(num_surfs):
            s = lde.GetSurfaceAt(i)
            r = _safe(s, "Radius", 1e18)
            t = _safe(s, "Thickness", 0.0)
            mat = _safe(s, "Material", "") or ""
            comment = _safe(s, "Comment", "") or ""
            sd = _safe(s, "SemiDiameter", 0.0) or 0.0
            surfaces.append({
                "surf": i,
                "radius": r if r is not None else 1e18,
                "thickness": t if t is not None else 0.0,
                "material": mat.strip(),
                "comment": str(comment).strip(),
                "semi_diameter": abs(sd),
            })

        # 识别透镜元件：连续材料非空表面组
        # 一个透镜组 = 从第一个有材料的面到该组最后一个面（材料变为空气）
        lenses = []
        i = 1  # 跳过物面
        while i < last_surf:
            s = surfaces[i]
            if s["material"] and s["material"].upper() not in ("", "MIRROR"):
                # 开始一个透镜元件（可能是胶合组）
                group_surfs = [i]
                j = i + 1
                while j < last_surf and surfaces[j]["material"] and surfaces[j]["material"].upper() not in ("", "MIRROR"):
                    group_surfs.append(j)
                    j += 1
                # 最后一个表面是出射面（无材料）
                exit_surf = j if j < last_surf else j
                group_surfs.append(exit_surf)  # 出射面
                lenses.append(group_surfs)
                i = j + 1
            else:
                i += 1

        warnings = []
        elements = []

        for group in lenses:
            entry_surf_idx = group[0]
            exit_surf_idx = group[-1]
            entry = surfaces[entry_surf_idx]
            exit_ = surfaces[exit_surf_idx]

            R1 = entry["radius"]
            R2 = exit_["radius"]
            # 半口径取组内最大
            sd = max(surfaces[k]["semi_diameter"] for k in group)
            if sd == 0:
                sd = 1.0

            # 中心厚度 = 组内所有材料面的厚度之和
            ct = sum(surfaces[k]["thickness"] for k in group[:-1])

            # sag 计算：sag = R - sqrt(R² - h²)，h = semi_diameter
            def sag(R, h):
                if abs(R) > 1e15:  # 平面
                    return 0.0
                R2_minus_h2 = R ** 2 - h ** 2
                if R2_minus_h2 < 0:
                    return abs(R)  # 超出边缘（非物理），保守估计
                return R - math.copysign(math.sqrt(R2_minus_h2), R)

            sag1 = sag(R1, sd)
            sag2 = sag(R2, sd)
            # ET = CT - sag(入射面) + sag(出射面)
            # 注意符号：Zemax 定义下入射面正 sag 使边缘变薄，出射面正 sag 使边缘变厚
            et = ct - sag1 + sag2

            # 弯曲因子 B = (R2+R1)/(R2-R1)，平面令 R=∞→1e18
            R1_eff = R1 if abs(R1) < 1e15 else 1e18
            R2_eff = R2 if abs(R2) < 1e15 else 1e18
            try:
                B = (R2_eff + R1_eff) / (R2_eff - R1_eff) if abs(R2_eff - R1_eff) > 1e-6 else 999.0
            except Exception:
                B = None

            # 最小有效曲率半径
            min_r = min(
                (abs(surfaces[k]["radius"]) for k in group if abs(surfaces[k]["radius"]) < 1e15),
                default=None
            )

            # CT/ET 比值
            ct_et_ratio = round(ct / et, 3) if et != 0 else None
            # 半口径/CT 比（细长比）
            sd_ct_ratio = round(sd / ct, 3) if ct > 0 else None

            issues = []
            severity = "pass"
            material_text = " ".join(surfaces[k]["material"] for k in group).lower()
            comment_text = " ".join(surfaces[k].get("comment", "") for k in group).lower()
            is_plane_plate = abs(R1) > 1e15 and abs(R2) > 1e15
            is_cover_glass = (
                is_plane_plate
                and 0.12 <= ct <= 0.22
                and (
                    "cover" in material_text
                    or "cover" in comment_text
                    or "盖玻" in comment_text
                    or 0.16 <= ct <= 0.18
                )
            )

            if is_cover_glass:
                issues.append(f"✅ 标准显微盖玻片例外: CT={ct:.3f}mm，按 cover glass 接受")
            elif et < 0.3:
                issues.append(f"⚠️ 边缘厚度 ET={et:.3f}mm < 0.3mm，极薄无法加工")
                severity = "fail"
            elif et < 1.0:
                issues.append(f"⚠️ 边缘厚度 ET={et:.3f}mm < 1.0mm，装配风险")
                if severity != "fail":
                    severity = "warn"

            if not is_cover_glass and ct < 1.0:
                issues.append(f"⚠️ 中心厚度 CT={ct:.3f}mm < 1.0mm，过薄")
                if severity != "fail":
                    severity = "warn"

            if not is_cover_glass and ct_et_ratio is not None and ct_et_ratio > 10:
                issues.append(f"⚠️ CT/ET={ct_et_ratio:.1f}，正透镜边缘过薄，镀膜困难")
                if severity != "fail":
                    severity = "warn"
            if not is_cover_glass and ct_et_ratio is not None and ct_et_ratio < 0.1:
                issues.append(f"⚠️ CT/ET={ct_et_ratio:.3f}，负透镜中心过薄")
                if severity != "fail":
                    severity = "warn"

            if min_r is not None and min_r < 3.0:
                issues.append(f"⚠️ 最小曲率半径 R={min_r:.2f}mm < 3mm，难以抛光")
                if severity != "fail":
                    severity = "warn"

            if not is_cover_glass and sd_ct_ratio is not None and sd_ct_ratio > 8:
                issues.append(f"⚠️ 半口径/CT={sd_ct_ratio:.1f}，透镜过于扁平，加工变形风险")
                if severity != "fail":
                    severity = "warn"

            if not is_cover_glass and B is not None and abs(B) > 5:
                issues.append(f"⚠️ 弯曲因子 B={B:.2f}，极端弯月形，慧差校正困难")
                if severity != "fail":
                    severity = "warn"

            element = {
                "surfs": group,
                "R1": round(R1, 4) if abs(R1) < 1e15 else "∞",
                "R2": round(R2, 4) if abs(R2) < 1e15 else "∞",
                "center_thickness_mm": round(ct, 4),
                "edge_thickness_mm": round(et, 4),
                "semi_diameter_mm": round(sd, 4),
                "ct_et_ratio": ct_et_ratio,
                "sd_ct_ratio": sd_ct_ratio,
                "bend_factor_B": round(B, 3) if B is not None else None,
                "min_radius_mm": round(min_r, 4) if min_r is not None else None,
                "accepted_exception": "standard_cover_glass" if is_cover_glass else None,
                "severity": severity,
                "issues": issues,
            }
            elements.append(element)
            warnings.extend(issues)

        overall = "pass"
        if any(e["severity"] == "fail" for e in elements):
            overall = "fail"
        elif any(e["severity"] == "warn" for e in elements):
            overall = "warn"

        result = {
            "overall": overall,
            "num_elements": len(elements),
            "elements": elements,
            "summary": warnings if warnings else ["✅ 所有透镜元件通过可制造性检查"],
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ---- 实体干涉 / 净空检查 ----
    def check_interference(self, min_clearance: float = 0.1, save_image: bool = True,
                           image_path: str = None, stop_clearance: float = 2.0) -> str:
        """检查所有相邻实体（透镜元件 / 光阑）之间的轴向边缘净空。

        几何原理：面 i 的边缘位置 z_edge = z_vertex + sag(R, h)，
        两实体净空 = z_front(B) + sag_B - (z_rear(A) + sag_A)。负值 = 实体相交。

        与 check_manufacturability 的分工：后者只看单个元件的边厚与弯曲因子，
        **不检查元件之间、元件与光阑之间是否插在一起**——这里是那个盲区。
        """
        import math
        lde = self.conn.lde
        num_surfs = lde.NumberOfSurfaces
        last_surf = num_surfs - 1

        surfaces = []
        for i in range(num_surfs):
            s = lde.GetSurfaceAt(i)
            r = _safe(s, "Radius", 1e18)
            t = _safe(s, "Thickness", 0.0)
            mat = (_safe(s, "Material", "") or "").strip()
            sd = abs(_safe(s, "SemiDiameter", 0.0) or 0.0)
            surfaces.append({
                "surf": i,
                "radius": r if r is not None else 1e18,
                "thickness": t if t is not None else 0.0,
                "material": mat,
                "semi_diameter": sd,
                "is_stop": bool(_safe(s, "IsStop", False)),
            })

        # 顶点 z 坐标（面 1 为 0）
        zv = {1: 0.0}
        for i in range(1, last_surf):
            zv[i + 1] = zv[i] + surfaces[i]["thickness"]

        def _sag(R, h):
            """矢高；返回 None 表示超半球无解。平面返回 0。"""
            if R is None or abs(R) > 1e15:
                return 0.0
            if not h or h <= 0:
                return 0.0
            t = R * R - h * h
            if t < 0:
                return None
            return R - math.copysign(math.sqrt(t), R)

        notes = []

        # ---- 识别实体：透镜组（连续非空材料）+ 光阑 ----
        entities = []
        idx = 1
        elem_no = 0
        while idx < last_surf:
            s = surfaces[idx]
            if s["material"] and s["material"].upper() not in ("", "MIRROR"):
                group = [idx]
                j = idx + 1
                while j < last_surf and surfaces[j]["material"] and surfaces[j]["material"].upper() not in ("", "MIRROR"):
                    group.append(j)
                    j += 1
                exit_surf = j
                group.append(exit_surf)
                elem_no += 1
                entities.append({
                    "kind": "element",
                    "name": f"元件{_CIRCLED.get(elem_no, elem_no)}",
                    "front_surf": group[0],
                    "rear_surf": exit_surf,
                    "surfs": group,
                })
                idx = j + 1
            else:
                idx += 1
        for s in surfaces:
            if s["is_stop"]:
                entities.append({
                    "kind": "stop",
                    "name": "光阑(STOP)",
                    "front_surf": s["surf"],
                    "rear_surf": s["surf"],
                    "surfs": [s["surf"]],
                })
        entities.sort(key=lambda e: (zv.get(e["front_surf"], 0.0), 0 if e["kind"] == "stop" else 1))

        # ---- 逐对计算净空 ----
        pairs = []
        for a, b in zip(entities, entities[1:]):
            sa = surfaces[a["rear_surf"]]
            sb = surfaces[b["front_surf"]]
            z_a, z_b = zv.get(a["rear_surf"], 0.0), zv.get(b["front_surf"], 0.0)
            sd_a, sd_b = sa["semi_diameter"], sb["semi_diameter"]

            hc = min(sd_a, sd_b)          # 同高度比较（面-面标准口径）
            sag_a_c, sag_b_c = _sag(sa["radius"], hc), _sag(sb["radius"], hc)
            # 各自口径比较（对光阑/机械件更保守）
            sag_a_o, sag_b_o = _sag(sa["radius"], sd_a), _sag(sb["radius"], sd_b)

            invalid = []
            if sag_a_c is None or sag_b_c is None or sag_a_o is None or sag_b_o is None:
                for nm, r_, h_ in ((a["name"], sa["radius"], sd_a), (b["name"], sb["radius"], sd_b)):
                    if _sag(r_, h_) is None:
                        invalid.append(f"{nm} 半口径 {h_:.3f} > |R| {abs(r_):.3f}（超半球，sag 无解）")

            gap_common = None if (sag_a_c is None or sag_b_c is None) else (z_b + sag_b_c) - (z_a + sag_a_c)
            gap_own = None if (sag_a_o is None or sag_b_o is None) else (z_b + sag_b_o) - (z_a + sag_a_o)
            # 真实最小实体间隔：球面 sag 对 r 单调，极值只可能在 r=0 或 r=hc，故取三者最小
            center_gap = (z_b + 0.0) - (z_a + 0.0)
            cands = {}
            cands["axis"] = center_gap
            if gap_common is not None:
                cands["edge_common"] = gap_common
            if gap_own is not None:
                cands["edge_own_sd"] = gap_own
            where = min(cands, key=lambda k: cands[k])
            gap = cands[where]
            if where == "axis":
                ez_rear, ez_front = z_a, z_b
            elif where == "edge_common":
                ez_rear, ez_front = z_a + sag_a_c, z_b + sag_b_c
            else:
                ez_rear, ez_front = z_a + sag_a_o, z_b + sag_b_o

            thr = stop_clearance if (a["kind"] == "stop" or b["kind"] == "stop") else min_clearance
            if gap < 0:
                sev = "fail"
            elif gap < thr:
                sev = "warn"
            else:
                sev = "pass"

            entry = {
                "from": a["name"],
                "to": b["name"],
                "rear_surf": a["rear_surf"],
                "front_surf": b["front_surf"],
                "center_gap_mm": round(center_gap, 4),
                "sag_rear_mm": None if sag_a_c is None else round(sag_a_c, 4),
                "sag_front_mm": None if sag_b_c is None else round(sag_b_c, 4),
                "clearance_mm": round(gap, 4),
                "clearance_at": where,
                "edge_z_rear": round(ez_rear, 6),
                "edge_z_front": round(ez_front, 6),
                "clearance_common_mm": None if gap_common is None else round(gap_common, 4),
                "clearance_own_sd_mm": None if gap_own is None else round(gap_own, 4),
                "threshold_mm": thr,
                "severity": sev,
                "is_stop_pair": a["kind"] == "stop" or b["kind"] == "stop",
            }
            if invalid:
                entry["notes"] = invalid
            pairs.append(entry)

        # ---- 汇总 ----
        vals = [p["clearance_mm"] for p in pairs if p["clearance_mm"] is not None]
        min_gap = min(vals) if vals else None
        if any(p["severity"] == "fail" for p in pairs):
            overall = "fail"
        elif any(p["severity"] in ("warn", "unknown") for p in pairs):
            overall = "warn"
        else:
            overall = "pass"

        summary = []
        for p in pairs:
            if p["severity"] == "fail":
                summary.append(
                    f"❌ {p['from']} → {p['to']}：净空 {p['clearance_mm']:.3f} mm（负值＝实体相交，位置在 {p['clearance_at']}）"
                )
            elif p["severity"] == "warn":
                summary.append(
                    f"⚠️ {p['from']} → {p['to']}：净空 {p['clearance_mm']:.3f} mm < {p['threshold_mm']:.2f} mm"
                    f"（最紧处在 {p['clearance_at']}）"
                )
        if not summary:
            summary.append("✅ 所有相邻实体净空充足")

        # ---- 可选：生成不依赖像素标定的几何示意图 ----
        img_out = None
        if save_image:
            try:
                img_out = self._render_clearance_schematic(surfaces, entities, pairs, zv, image_path)
            except Exception as exc:  # 出图失败不影响数值结论
                notes.append(f"示意图生成失败（数值结论不受影响）：{exc}")

        result = {
            "overall": overall,
            "min_clearance_mm": None if min_gap is None else round(min_gap, 4),
            "thresholds": {"element_pair_mm": min_clearance, "stop_pair_mm": stop_clearance},
            "pairs": pairs,
            "summary": summary,
            "schematic": img_out,
            "notes": notes,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _render_clearance_schematic(self, surfaces, entities, pairs, zv, image_path=None) -> str:
        """按 LDE 真实几何画出轴向剖面示意图，并把每对实体的净空标在图上。

        关键设计：**不依赖 Zemax 位图的像素标定**——图完全由 z 坐标与 sag 数据生成，
        因此可确定性复现，不会出现"标定错就画错"的问题。
        """
        import math
        from PIL import Image, ImageDraw, ImageFont

        last_surf = len(surfaces) - 1
        total_z = zv.get(last_surf, 0.0)

        # 视场半径上限
        max_sd = max((s["semi_diameter"] for s in surfaces[1:last_surf] if s["semi_diameter"]), default=10.0)

        W = 1400
        ML, MR, MT, MB = 90, 130, 60, 90
        z_span = total_z if total_z > 0 else 1.0
        sx = (W - ML - MR) / z_span
        # 等比例：横向纵向同比例，否则弯月面会被压扁成平板
        sy = sx
        headroom = 34 * max(1, len(pairs)) + 44          # 顶部标注区高度
        axis_y = MT + headroom + max_sd * sy
        H = int(axis_y + max_sd * sy + MB)
        r_span = max(max_sd * 1.15, 1e-6)

        def X(z):
            return ML + z * sx

        def Y(r):
            return axis_y + r * sy

        def sag(R, h):
            if R is None or abs(R) > 1e15:
                return 0.0
            t = R * R - h * h
            if t < 0:
                return None
            return R - math.copysign(math.sqrt(t), R)

        img = Image.new("RGB", (W, H), (255, 255, 255))
        dr = ImageDraw.Draw(img)

        def font(sz):
            for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
                try:
                    return ImageFont.truetype(p, sz)
                except Exception:
                    continue
            return ImageFont.load_default()

        f_lbl, f_sm, f_gap = font(19), font(15), font(17)

        # 光轴
        dr.line([(X(0), axis_y), (X(total_z), axis_y)], fill=(160, 160, 160), width=1)

        # 透镜实体：上下两半填充
        lens_fill = (222, 235, 248)
        lens_line = (30, 60, 110)
        N = 90
        for e in entities:
            if e["kind"] != "element":
                continue
            fi, ri = e["front_surf"], e["rear_surf"]
            s_f, s_r = surfaces[fi], surfaces[ri]

            def surf_pts(s, n=N):
                pts, ok = [], True
                for k in range(n + 1):
                    h = s["semi_diameter"] * k / n
                    sg = sag(s["radius"], h)
                    if sg is None:
                        ok = False
                        break
                    pts.append((X(zv[s["surf"]] + sg), h))
                return (pts if ok else None)

            pf = surf_pts(s_f)
            pr = surf_pts(s_r)
            if pf is None or pr is None:
                # 超半球：退化为直线轮廓，并标注
                pf = [(X(zv[fi]), 0.0), (X(zv[fi]), s_f["semi_diameter"])]
                pr = [(X(zv[ri]), s_r["semi_diameter"]), (X(zv[ri]), 0.0)]
            top = pf + pr[::-1]
            bot = [(x, -r) for x, r in top]
            dr.polygon([(x, Y(r)) for x, r in top], fill=lens_fill, outline=lens_line)
            dr.polygon([(x, Y(r)) for x, r in bot], fill=lens_fill, outline=lens_line)
            dr.line([(x, Y(r)) for x, r in top], fill=lens_line, width=2)
            dr.line([(x, Y(r)) for x, r in bot], fill=lens_line, width=2)

            mid = (zv[fi] + zv[ri]) / 2.0
            dr.text((X(mid) - 26, Y(max(s_f["semi_diameter"], s_r["semi_diameter"])) - 26),
                    e["name"], font=f_lbl, fill=lens_line)

        # 光阑：两根短竖线 + 开口标注
        for e in entities:
            if e["kind"] != "stop":
                continue
            s = surfaces[e["front_surf"]]
            x = X(zv[s["surf"]])
            h = s["semi_diameter"]
            dr.line([(x, Y(h) - 26), (x, Y(h))], fill=(20, 90, 220), width=4)
            dr.line([(x, Y(-h)), (x, Y(-h) + 26)], fill=(20, 90, 220), width=4)
            dr.line([(x - 22, Y(h) - 26), (x + 22, Y(h) - 26)], fill=(20, 90, 220), width=3)
            dr.line([(x - 22, Y(-h) + 26), (x + 22, Y(-h) + 26)], fill=(20, 90, 220), width=3)
            dr.text((x - 34, Y(-h) + 34), "STOP", font=f_sm, fill=(20, 90, 220))

        # 净空标注：从透镜最高边缘往上依次排开，互不重叠、也不压标题
        top_edge_y = axis_y - max_sd * sy
        lane0 = min(top_edge_y - 34, axis_y - 40)
        for k, p in enumerate(pairs):
            gap = p["clearance_mm"]
            if gap is None:
                continue
            xa = X(p.get("edge_z_rear", zv[p["rear_surf"]]))
            xb = X(p.get("edge_z_front", zv[p["front_surf"]]))
            y = lane0 - k * 32
            if y < MT + 34:
                y = MT + 34
            sev = p["severity"]
            col = (200, 30, 30) if sev == "fail" else ((215, 120, 0) if sev == "warn" else (20, 130, 70))
            dr.line([(xa, y), (xb, y)], fill=col, width=2)
            for xx in (xa, xb):
                dr.line([(xx, y - 8), (xx, y + 8)], fill=col, width=2)
                dr.line([(xx, y + 8), (xx, min(y + 8 + 26, axis_y))], fill=col, width=1)
            txt = f"{_short_name(p['from'])} → {_short_name(p['to'])}   {gap:.2f} mm"
            tw = dr.textlength(txt, font=f_gap) if hasattr(dr, "textlength") else 200
            tx = min(max(ML, (xa + xb) / 2 - tw / 2), W - MR - tw)
            dr.text((tx, y - 24), txt, font=f_gap, fill=col)

        # 底部：z 标尺与标题
        yz = H - 30
        dr.line([(X(0), yz - 6), (X(total_z), yz - 6)], fill=(120, 120, 120), width=1)
        dr.text((X(0), yz), "z = 0（面1）", font=f_sm, fill=(120, 120, 120))
        dr.text((X(total_z) - 96, yz), f"像面 z={total_z:.2f}", font=f_sm, fill=(120, 120, 120))
        dr.text((ML, 16), "实体净空剖面（按 LDE 真实几何生成，非位图标定）", font=f_lbl, fill=(40, 40, 40))

        if image_path:
            out = Path(image_path)
        else:
            current_file = self._current_system_file()
            base_dir = current_file.parent if current_file else _WORKSPACE_ROOT
            out = Path(base_dir) / "layouts" / "_clearance_check.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
        return str(out)

    # ---- 玻璃库管理 ----
    def get_glass_catalogs(self, catalog: str = None) -> str:
        """获取玻璃库信息：当前使用的目录、可用目录、指定目录中的材料。"""
        mat_cat = self.conn.system_data.MaterialCatalogs

        in_use = list(_call_or_value(_safe(mat_cat, "GetCatalogsInUse", ())) or ())
        available = list(_call_or_value(_safe(mat_cat, "GetAvailableCatalogs", ())) or ())

        result = {
            "catalogs_in_use": in_use,
            "available_catalogs": available,
        }

        if catalog:
            materials = list(mat_cat.GetMaterialsInCatalog(catalog) or ())
            result["query_catalog"] = catalog
            result["materials"] = materials
            result["material_count"] = len(materials)

        return json.dumps(result, ensure_ascii=False, indent=2)

    def set_glass_catalogs(self, add: list = None, remove: list = None) -> str:
        """添加或移除玻璃库目录。"""
        mat_cat = self.conn.system_data.MaterialCatalogs

        results = {"added": [], "removed": [], "errors": []}

        if remove:
            for cat_name in remove:
                try:
                    ok = mat_cat.RemoveCatalog(cat_name)
                    if ok:
                        results["removed"].append(cat_name)
                    else:
                        results["errors"].append(f"移除 '{cat_name}' 失败 (可能不在使用列表中)")
                except Exception as e:
                    results["errors"].append(f"移除 '{cat_name}' 异常: {e}")

        if add:
            for cat_name in add:
                try:
                    ok = mat_cat.AddCatalog(cat_name)
                    if ok:
                        results["added"].append(cat_name)
                    else:
                        results["errors"].append(f"添加 '{cat_name}' 失败 (可能名称不正确或已在使用)")
                except Exception as e:
                    results["errors"].append(f"添加 '{cat_name}' 异常: {e}")

        # 返回更新后的状态
        results["catalogs_in_use"] = list(_call_or_value(_safe(mat_cat, "GetCatalogsInUse", ())) or ())
        results["ok"] = len(results["errors"]) == 0

        return json.dumps(results, ensure_ascii=False, indent=2)

    # ---- UI 刷新与布局 ----
    def update_ui(self) -> str:
        """刷新 OpticStudio GUI，并刷新所有已打开的分析窗口。"""
        system = self.conn.system

        # 1. 先重算 MFE，确保评价函数编辑器显示最新值
        merit_function_value = None
        try:
            merit_function_value = self.conn.mfe.CalculateMeritFunction()
        except Exception:
            pass

        # 2. 强制全窗口刷新模式
        update_mode_set = _safe_set_attr(system, "UpdateMode", 2)  # LensUpdateMode_AllWindows

        # 3. UpdateStatus 刷新主窗口 (LDE / 编辑器)
        status_msg = None
        try:
            status_msg = getattr(system, "UpdateStatus")()
        except Exception as e:
            status_msg = f"UpdateStatus 异常: {e}"

        # 4. 显示 MFE 窗口，让用户看到最新评价函数状态
        mfe_shown = False
        try:
            mfe_shown = bool(self.conn.mfe.ShowMFE())
        except Exception:
            pass

        # 5. 遍历已打开的分析窗口并刷新
        refreshed = 0
        try:
            analyses = getattr(system, "Analyses", None)
            n = _safe(analyses, "NumberOfAnalyses", 0)
            for i in range(1, n + 1):
                try:
                    a = analyses.Get_AnalysisAtIndex(i)
                    if a is not None:
                        a.ApplyAndWaitForCompletion()
                        refreshed += 1
                except Exception:
                    continue
        except Exception:
            pass

        return json.dumps(
            {
                "ok": True,
                "status": status_msg,
                "merit_function_value": merit_function_value,
                "update_mode_all_windows": update_mode_set,
                "mfe_shown": mfe_shown,
                "analyses_refreshed": refreshed,
            },
            ensure_ascii=False,
        )

    def open_layout(self, layout_type: str = "2D", export_path: str | None = None) -> str:
        """在 OpticStudio GUI 中打开 2D/3D 布局图窗口，并导出图像文件。"""
        system = self.conn.system

        # AnalysisIDM 枚举值
        layout_map = {"2D": 56, "3D": 57}  # Draw2D=56, Draw3D=57
        analysis_type = layout_map.get(layout_type.upper(), 56)

        analyses = getattr(system, "Analyses", None)
        if analyses is None:
            return json.dumps(
                {"error": f"无法打开 {layout_type} 布局窗口: system.Analyses 不可用"},
                ensure_ascii=False,
            )
        analysis = None
        try:
            analysis = analyses.New_Analysis(analysis_type)
        except Exception as e:
            return json.dumps(
                {"error": f"无法打开 {layout_type} 布局窗口: {e}"},
                ensure_ascii=False,
            )

        if analysis is None:
            return json.dumps(
                {"error": f"无法打开 {layout_type} 布局窗口 (返回 None)"},
                ensure_ascii=False,
            )

        # 等待计算完成
        try:
            analysis.ApplyAndWaitForCompletion()
        except Exception:
            try:
                analysis.WaitForCompletion()
            except Exception:
                pass

        auto_export = export_path is None
        current_file = self._current_system_file()
        base_dir = current_file.parent if current_file else _WORKSPACE_ROOT
        layouts_dir = base_dir / "layouts"
        layouts_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_type = "".join(ch if ch.isalnum() else "_" for ch in layout_type.upper())
        if export_path is None:
            export_path = str(layouts_dir / f"layout_{safe_type}_{timestamp}.bmp")

        result = {
            "ok": True,
            "layout_type": layout_type,
            "message": f"{layout_type} 布局图已在 OpticStudio GUI 中打开",
            "auto_export": auto_export,
        }

        # 导出到文件，供 Agent 检查结构；仅返回真实图片路径。
        if export_path:
            image_info = _export_verified_analysis_image(
                analysis,
                Path(export_path).parent,
                Path(export_path).stem,
                preferred_path=Path(export_path),
            )
            result.update(image_info)
            if image_info.get("image_path"):
                result["export_path"] = image_info["image_path"]
                result["exported_to"] = image_info["image_path"]
            else:
                # Analysis.ToFile 对图形窗口只能写文本 → 回退到 Layouts 图形导出接口
                try:
                    fallback = json.loads(
                        self.export_layout_image(layout_type=layout_type, file_path=export_path)
                    )
                except Exception as e:  # pragma: no cover - 防御
                    fallback = {"ok": False, "error": str(e)}
                if fallback.get("ok"):
                    result["image_path"] = fallback.get("image_path")
                    result["export_path"] = fallback.get("image_path")
                    result["exported_to"] = fallback.get("image_path")
                    result["image_export_ok"] = True
                    result["image_export_kind"] = fallback.get("kind")
                    result["image_export_is_viewable_by_agent"] = True
                    result["image_export_note"] = "Analysis.ToFile 无效，已改用 system.Tools.Layouts 图形导出接口"
                else:
                    result["export_path"] = None
                    result["export_error"] = "布局图导出失败（ToFile 与 Layouts 接口均未产出图片）"
                    result["export_error_detail"] = fallback

        # 注意：不要 Close()，让窗口保留在 GUI 中供用户查看

        return json.dumps(result, ensure_ascii=False)

    # ---- 布局图位图导出（正确接口：system.Tools.Layouts，不是 Analysis.ToFile）----
    def export_layout_image(
        self,
        layout_type: str = "3D",
        width: int = 1600,
        height: int = 1000,
        file_path: str | None = None,
        hide_lens_edges: bool = True,
        view: str = "current",
        angle_x: float = 0.0,
        angle_y: float = 0.0,
        angle_z: float = 0.0,
    ) -> str:
        """导出布局图真实位图.

        Analysis.ToFile 对图形窗口只能写出文本摘要；真正能出图的是
        ``system.Tools.Layouts.Open3DViewerExport()`` / ``OpenCrossSectionExport()``，
        其 ``OutputFilename`` + ``OutputPixelWidth/Height`` 设好后读取
        ``SaveImageAsFile`` 即触发保存。
        """
        system = self.conn.system
        lt = (layout_type or "3D").upper()

        # 复用已打开的布局窗口；只有找不到同类型窗口时才新建一个
        analysis_id = 57 if lt == "3D" else 56
        analyses = getattr(system, "Analyses", None)
        window_action = "skipped"
        if analyses is not None:
            existing = None
            try:
                count = int(analyses.NumberOfAnalyses)
            except Exception:
                count = 0
            for idx in range(1, count + 1):
                try:
                    candidate = analyses.Get_AnalysisAtIndex(idx)
                except Exception:
                    continue
                if int(_safe(candidate, "AnalysisType", -1) or -1) == analysis_id:
                    existing = candidate
                    break
            try:
                if existing is not None:
                    existing.ApplyAndWaitForCompletion()
                    window_action = "reused"
                else:
                    analyses.New_Analysis(analysis_id).ApplyAndWaitForCompletion()
                    window_action = "created"
            except Exception as e:
                window_action = f"failed: {e}"
                logger.warning(f"布局窗口刷新/创建失败（不影响图片导出）: {e}")

        current_file = self._current_system_file()
        base_dir = current_file.parent if current_file else _WORKSPACE_ROOT
        out_dir = base_dir / "layouts"
        out_dir.mkdir(parents=True, exist_ok=True)
        # 固定文件名（不带日期），每次导出直接覆盖，便于反复对比
        if file_path:
            target = Path(file_path)
        else:
            suffix = "" if (lt == "2D" or hide_lens_edges) else "_edges"
            target = out_dir / f"layout_{lt}{suffix}.png"
        target.parent.mkdir(parents=True, exist_ok=True)

        layouts = None
        for holder_name in ("Tools", None):
            holder = getattr(system, holder_name, None) if holder_name else system
            if holder is None:
                continue
            candidate = getattr(holder, "Layouts", None)
            if candidate is not None:
                layouts = candidate
                break
        if layouts is None:
            return json.dumps(
                {
                    "ok": False,
                    "error": "Layouts 接口不可用（system.Tools.Layouts 与 system.Layouts 都取不到），无法导出布局图",
                },
                ensure_ascii=False,
            )

        openers = (
            ["Open3DViewerExport"]
            if lt == "3D"
            else ["OpenCrossSectionExport", "Open3DViewerExport"]
        )
        attempts: list[dict] = []
        for opener in openers:
            fn = getattr(layouts, opener, None)
            if fn is None:
                attempts.append({"opener": opener, "error": "接口不存在"})
                continue
            try:
                exporter = fn()
            except Exception as e:
                attempts.append({"opener": opener, "error": f"调用失败: {e}"})
                continue
            if exporter is None:
                attempts.append({"opener": opener, "error": "返回 None"})
                continue
            # 3D 视角控制（两种模式，互斥）：
            #   1) view = isometric / xy / yz / xz → 调 SetCameraViewpoint 预设，忽略角度参数
            #   2) view = current（默认）        → 不调预设，直接写 CameraViewpointAngleX/Y/Z
            #      默认就是 0/0/0，即 Zemax 3D 布局的原始标准视角，与 GUI 里看到的一致
            camera_report: dict[str, object] = {}
            if lt == "3D":
                preset = {"isometric": 0, "xy": 1, "yz": 2, "xz": 3}.get((view or "").lower())
                if preset is not None:
                    try:
                        exporter.SetCameraViewpoint(preset)
                        camera_report["preset"] = view.lower()
                    except Exception as e:
                        camera_report["preset_error"] = f"设置失败: {e}"
                else:
                    for attr, val in (
                        ("CameraViewpointAngleX", float(angle_x)),
                        ("CameraViewpointAngleY", float(angle_y)),
                        ("CameraViewpointAngleZ", float(angle_z)),
                    ):
                        try:
                            setattr(exporter, attr, val)
                            camera_report[attr] = "ok"
                        except Exception as e:
                            camera_report[attr] = f"失败: {e}"
                # 无论走哪条分支，都读回真实角度，便于核对出图到底用的什么视角
                try:
                    camera_report["readback_deg"] = {
                        "x": round(float(exporter.CameraViewpointAngleX), 3),
                        "y": round(float(exporter.CameraViewpointAngleY), 3),
                        "z": round(float(exporter.CameraViewpointAngleZ), 3),
                    }
                except Exception as e:
                    camera_report["readback_error"] = str(e)
            try:
                _delete_file_quietly(target)
                num_surfaces = 0
                try:
                    num_surfaces = int(self.conn.lde.NumberOfSurfaces)
                except Exception:
                    pass

                set_report: dict[str, str] = {}
                for attr, val in (
                    ("OutputFilename", str(target)),
                    ("OutputFileName", str(target)),
                    ("OutputPixelWidth", int(width)),
                    ("OutputPixelHeight", int(height)),
                    ("StartSurface", 1),
                    ("EndSurface", max(2, num_surfaces - 1)),
                    ("NumberOfRays", 7),
                    ("Wavelength", -1),
                    ("Field", -1),
                    ("DeleteVignetted", True),
                ):
                    try:
                        setattr(exporter, attr, val)
                        set_report[attr] = "ok"
                    except Exception as e:
                        set_report[attr] = f"失败: {e}"

                # 3D 专属：隐藏透镜边 / X 条，出图更干净（只留面形与光线）
                # 2D 专属：加粗面线，便于判读
                extra_props = (
                    (
                        ("HideLensEdges", bool(hide_lens_edges)),
                        ("HideXBars", True),
                    )
                    if opener == "Open3DViewerExport"
                    else (
                        ("SurfaceLineThickness", 2),
                        ("RaysLineThickness", 1),
                    )
                )
                for attr, val in extra_props:
                    try:
                        setattr(exporter, attr, val)
                        set_report[attr] = "ok"
                    except Exception as e:
                        set_report[attr] = f"失败: {e}"

                triggers: list[str] = []
                try:
                    exporter.SaveImageAsFile = True
                    triggers.append("SaveImageAsFile=True → ok")
                except Exception as e:
                    triggers.append(f"SaveImageAsFile=True → 失败: {e}")

                # 关键：官方用法必须 RunAndWaitForCompletion 才会真正渲染并写盘
                tool_base = None
                try:
                    tool_base = _cast_to_system_tool(exporter)
                    tool_base.RunAndWaitForCompletion()
                    triggers.append("RunAndWaitForCompletion → ok")
                except Exception as e:
                    triggers.append(f"RunAndWaitForCompletion → 失败: {e}")

                # 等文件落盘（最多 3 秒）
                for _ in range(30):
                    if target.exists() and target.stat().st_size > 1024:
                        break
                    time.sleep(0.1)

                readback: dict[str, object] = {}
                for attr in ("OutputFilename", "OutputPixelWidth", "OutputPixelHeight"):
                    try:
                        readback[attr] = getattr(exporter, attr)
                    except Exception as e:
                        readback[attr] = f"读取失败: {e}"

                if tool_base is not None:
                    try:
                        tool_base.Close()
                        triggers.append("Close → ok")
                    except Exception as e:
                        triggers.append(f"Close → 失败: {e}")

                kind = _classify_export_file(target)
                size = target.stat().st_size if target.exists() else 0
                is_image = kind in _VALID_ANALYSIS_IMAGE_KINDS
                attempts.append(
                    {
                        "opener": opener,
                        "path": str(target),
                        "kind": kind,
                        "bytes": size,
                        "set_report": set_report,
                        "readback": readback,
                        "camera": camera_report,
                        "triggers": triggers,
                        "valid_image": is_image,
                    }
                )
                if is_image:
                    return json.dumps(
                        {
                            "ok": True,
                            "layout_type": lt,
                            "image_path": str(target),
                            "kind": kind,
                            "bytes": size,
                            "pixels": f"{width}x{height}",
                            "opener": opener,
                            "window": window_action,
                            "camera": camera_report,
                            "attempts": attempts,
                        },
                        ensure_ascii=False,
                    )
                _delete_file_quietly(target)
            except Exception as e:
                attempts.append({"opener": opener, "error": str(e)})
                _delete_file_quietly(target)

        return json.dumps(
            {
                "ok": False,
                "error": "布局图位图导出失败：ZOS-API 导出接口未产出有效图片",
                "attempts": attempts,
            },
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
#  辅助
# ---------------------------------------------------------------------------

_ANALYSIS_ALIASES = {
    "spot": "standard_spot",
    "spot_diagram": "standard_spot",
    "standard_spot": "standard_spot",
    "relative_illumination": "relative_illumination",
    "relillum": "relative_illumination",
    "vignetting": "vignetting_diagram",
    "vignetting_diagram": "vignetting_diagram",
    "ray_fan": "ray_fan",
    "opd_fan": "opd_fan",
    "optical_path_fan": "opd_fan",
    "longitudinal_aberration": "longitudinal_aberration",
    "axial_color": "longitudinal_aberration",
    "lateral_color": "lateral_color",
    "fft_mtf": "fft_mtf",
    "fft_mtf_vs_field": "fft_mtf_vs_field",
    "huygens_mtf": "huygens_mtf",
    "field_curvature_distortion": "field_curvature_distortion",
    "wavefront_map": "wavefront_map",
}

_ANALYSIS_METHODS = {
    "standard_spot": "New_StandardSpot",
    "ray_fan": "New_RayFan",
    "opd_fan": "New_OpticalPathFan",
    "longitudinal_aberration": "New_LongitudinalAberration",
    "lateral_color": "New_LateralColor",
    "fft_mtf": "New_FftMtf",
    "fft_mtf_vs_field": "New_FftMtfvsField",
    "huygens_mtf": "New_HuygensMtf",
    "field_curvature_distortion": "New_FieldCurvatureAndDistortion",
    "wavefront_map": "New_WavefrontMap",
}

_ANALYSIS_IDS = {
    "relative_illumination": 68,
    "vignetting_diagram": 69,
    "standard_spot": 43,
    "ray_fan": 0,
    "opd_fan": 1,
    "longitudinal_aberration": 7,
    "lateral_color": 6,
    "fft_mtf": 15,
    "fft_mtf_vs_field": 22,
    "huygens_mtf": 25,
    "field_curvature_distortion": 3,
    "wavefront_map": 54,
}

_ANALYSIS_SETTING_INTERFACES = {
    "fft_mtf_vs_field": "IAS_FftMtfvsField",
    "huygens_mtf": "IAS_HuygensMtf",
}


def _canonical_analysis_key(key: str) -> str:
    canonical = _ANALYSIS_ALIASES.get(str(key or "").strip().lower())
    if not canonical:
        raise ValueError(f"不支持的 Analysis 类型: {key}")
    return canonical


def _cast_analysis_settings(settings, canonical_key: str):
    """Cast generic IAS_ settings to the concrete analysis settings interface when available."""
    iface = _ANALYSIS_SETTING_INTERFACES.get(canonical_key)
    if not iface or settings is None:
        return settings
    try:
        from win32com.client import CastTo
        return CastTo(settings, iface)
    except Exception:
        return settings


def _new_analysis(analyses, canonical_key: str):
    method_name = _ANALYSIS_METHODS.get(canonical_key)
    if method_name and hasattr(analyses, method_name):
        try:
            return getattr(analyses, method_name)()
        except Exception:
            pass
    analysis_id = _ANALYSIS_IDS.get(canonical_key)
    if analysis_id is None:
        return None
    return analyses.New_Analysis(analysis_id)


def _apply_analysis_settings(settings, overrides: dict) -> dict:
    report = {"requested": overrides or {}, "applied": [], "failed": []}
    if settings is None:
        report["failed"].append({"setting": "settings", "error": "GetSettings returned None"})
        return report
    overrides = dict(overrides or {})

    field_value = overrides.pop("field", None)
    if field_value is not None and hasattr(settings, "Field"):
        ok, err = _set_analysis_selector(settings.Field, int(field_value), "UseAllFields", "SetFieldNumber")
        (report["applied"] if ok else report["failed"]).append({"setting": "Field", "value": field_value, "error": err})

    wave_value = overrides.pop("wave", None)
    if wave_value is not None and hasattr(settings, "Wavelength"):
        ok, err = _set_analysis_selector(settings.Wavelength, int(wave_value), "UseAllWavelengths", "SetWavelengthNumber")
        (report["applied"] if ok else report["failed"]).append({"setting": "Wavelength", "value": wave_value, "error": err})

    frequencies = overrides.pop("frequencies", None)
    if frequencies is not None:
        for idx, freq in enumerate(list(frequencies)[:6], start=1):
            key = f"Freq_{idx}"
            if _safe_set_attr(settings, key, float(freq)):
                report["applied"].append({"setting": key, "value": float(freq)})
            else:
                report["failed"].append({"setting": key, "value": freq, "error": "not writable"})

    alias_map = {
        "sample_size": "SampleSize",
        "remove_vignetting": "RemoveVignetting",
        "ignore_vignette": "IgnoreVignette",
        "ray_density": "RayDensity",
        "number_of_rays": "NumberOfRays",
        "show_airy_disk": "ShowAiryDisk",
        "use_real_rays": "UseRealRays",
        "sampling": "Sampling",
    }
    for key, value in list(overrides.items()):
        target = alias_map.get(key, key)
        if _safe_set_attr(settings, target, value):
            report["applied"].append({"setting": target, "value": _jsonable_number(value)})
        else:
            report["failed"].append({"setting": target, "value": _jsonable_number(value), "error": "not writable"})
    return report


def _set_analysis_selector(selector, value: int, all_method: str, set_method: str):
    try:
        if value <= 0:
            getattr(selector, all_method)()
            return True, None
        getattr(selector, set_method)(int(value))
        return True, None
    except Exception as e:
        return False, str(e)


def _settings_snapshot(settings) -> dict:
    if settings is None:
        return {}
    snapshot = {"class": settings.__class__.__name__}
    for name in sorted((getattr(settings, "_prop_map_get_", {}) or {}).keys()):
        if name in ("Field", "Wavelength", "Surface"):
            selector = _safe(settings, name, None)
            if selector is not None:
                value = None
                for method_name in ("GetFieldNumber", "GetWavelengthNumber", "GetSurfaceNumber"):
                    if hasattr(selector, method_name):
                        try:
                            value = getattr(selector, method_name)()
                        except Exception:
                            value = None
                        break
                snapshot[name] = value
            continue
        try:
            snapshot[name] = _jsonable_number(getattr(settings, name))
        except Exception:
            continue
    return snapshot


def _analysis_results_to_dict(results, max_points: int = 2000) -> dict:
    payload = {
        "counts": {
            "data_series": _safe(results, "NumberOfDataSeries", 0) or 0,
            "data_grids": _safe(results, "NumberOfDataGrids", 0) or 0,
            "scatter_points": _safe(results, "NumberOfDataScatterPoints", 0) or 0,
            "scatter_points_rgb": _safe(results, "NumberOfDataScatterPointsRgb", 0) or 0,
            "ray_data": _safe(results, "NumberOfRayData", 0) or 0,
            "messages": _safe(results, "NumberOfMessages", 0) or 0,
        },
        "header": _header_data_to_list(_safe(results, "HeaderData", None)),
    }
    series = []
    for idx in range(int(payload["counts"]["data_series"] or 0)):
        obj = _get_indexed_result(results, "GetDataSeries", idx)
        if obj is not None:
            series.append(_data_series_to_dict(obj, max_points=max_points))
    if series:
        payload["data_series"] = series

    grids = []
    for idx in range(int(payload["counts"]["data_grids"] or 0)):
        obj = _get_indexed_result(results, "GetDataGrid", idx)
        if obj is not None:
            grids.append(_data_grid_to_dict(obj, max_points=max_points))
    if grids:
        payload["data_grids"] = grids

    scatter = _scatter_points_to_list(results, "GetDataScatterPoint", int(payload["counts"]["scatter_points"] or 0), max_points)
    if scatter:
        payload["scatter_points"] = scatter
    scatter_rgb = _scatter_points_to_list(results, "GetDataScatterPointRgb", int(payload["counts"]["scatter_points_rgb"] or 0), max_points)
    if scatter_rgb:
        payload["scatter_points_rgb"] = scatter_rgb

    spot_data = _safe(results, "SpotData", None)
    if spot_data is not None:
        payload["spot_data"] = _spot_matrix_to_dict(spot_data)

    messages = []
    for idx in range(int(payload["counts"]["messages"] or 0)):
        msg = _get_indexed_result(results, "GetMessageAt", idx)
        if msg is not None:
            messages.append(_message_to_dict(msg))
    if messages:
        payload["messages"] = messages
    return payload


def _get_indexed_result(results, method_name: str, index: int):
    method = getattr(results, method_name, None)
    if method is None:
        return None
    for candidate in (index, index + 1):
        try:
            return method(candidate)
        except Exception:
            continue
    return None


def _header_data_to_list(header) -> list:
    if header is None:
        return []
    return _array_to_list(_safe(header, "Lines", []), 200)


def _data_series_to_dict(series, max_points: int = 2000) -> dict:
    x_data = _vector_to_list(_safe(series, "XData", None), max_points)
    y_data = _matrix_to_list(_safe(series, "YData", None), max_points)
    return {
        "description": _jsonable_number(_safe(series, "Description", None)),
        "x_label": _jsonable_number(_safe(series, "XLabel", None)),
        "series_labels": _array_to_list(_safe(series, "SeriesLabels", []), 100),
        "num_series": _safe(series, "NumSeries", None),
        "x_data": x_data,
        "y_data": y_data,
        "truncated": _is_truncated_data(x_data, y_data, max_points),
    }


def _data_grid_to_dict(grid, max_points: int = 2000) -> dict:
    nx = int(_safe(grid, "Nx", 0) or 0)
    ny = int(_safe(grid, "Ny", 0) or 0)
    values = []
    limit = min(nx * ny, max_points)
    count = 0
    for row in range(nx):
        row_values = []
        for col in range(ny):
            if count >= limit:
                break
            try:
                row_values.append(_jsonable_number(grid.Z(row, col)))
            except Exception:
                try:
                    row_values.append(_jsonable_number(grid.Z(row + 1, col + 1)))
                except Exception:
                    row_values.append(None)
            count += 1
        if row_values:
            values.append(row_values)
        if count >= limit:
            break
    return {
        "description": _jsonable_number(_safe(grid, "Description", None)),
        "x_label": _jsonable_number(_safe(grid, "XLabel", None)),
        "y_label": _jsonable_number(_safe(grid, "YLabel", None)),
        "value_label": _jsonable_number(_safe(grid, "ValueLabel", None)),
        "nx": nx,
        "ny": ny,
        "min_x": _jsonable_number(_safe(grid, "MinX", None)),
        "min_y": _jsonable_number(_safe(grid, "MinY", None)),
        "dx": _jsonable_number(_safe(grid, "Dx", None)),
        "dy": _jsonable_number(_safe(grid, "Dy", None)),
        "values": values,
        "truncated": nx * ny > max_points,
    }


def _spot_matrix_to_dict(matrix) -> dict:
    num_fields = int(_safe(matrix, "NumberOfFields", 0) or 0)
    num_waves = int(_safe(matrix, "NumberOfWavelengths", 0) or 0)
    fields = []
    for field_idx in range(1, num_fields + 1):
        waves = []
        for wave_idx in range(1, num_waves + 1):
            waves.append({
                "wave": wave_idx,
                "rms_radius_lens_units": _call_matrix_method(matrix, "GetRMSSpotSizeFor", field_idx, wave_idx),
                "rms_x_lens_units": _call_matrix_method(matrix, "GetRMSSpot_X_For", field_idx, wave_idx),
                "rms_y_lens_units": _call_matrix_method(matrix, "GetRMSSpot_Y_For", field_idx, wave_idx),
                "geo_radius_lens_units": _call_matrix_method(matrix, "GetGeoSpotSizeFor", field_idx, wave_idx),
                "ref_x": _call_matrix_method(matrix, "GetReferenceCoordinate_X_For", field_idx, wave_idx),
                "ref_y": _call_matrix_method(matrix, "GetReferenceCoordinate_Y_For", field_idx, wave_idx),
            })
        fields.append({"field": field_idx, "waves": waves})
    return {
        "number_of_fields": num_fields,
        "number_of_wavelengths": num_waves,
        "half_width_x": _jsonable_number(_safe(matrix, "HalfWidth_X", None)),
        "half_width_y": _jsonable_number(_safe(matrix, "HalfWidth_Y", None)),
        "max_radius": _jsonable_number(_safe(matrix, "MaxRadius", None)),
        "mean_radius": _jsonable_number(_safe(matrix, "MeanRadius", None)),
        "fields": fields,
    }


def _call_matrix_method(matrix, method_name: str, field_idx: int, wave_idx: int):
    try:
        return _jsonable_number(getattr(matrix, method_name)(field_idx, wave_idx))
    except Exception:
        return None


def _message_to_dict(message) -> dict:
    result = {"class": message.__class__.__name__}
    for attr in ("Text", "Code", "Type", "Severity"):
        value = _safe(message, attr, None)
        if value is not None:
            result[attr.lower()] = _jsonable_number(value)
    if len(result) == 1:
        result["text"] = str(message)
    return result


def _vector_to_list(vector, max_points: int) -> list:
    if vector is None:
        return []
    data = _array_to_list(_safe(vector, "Data", []), max_points)
    if data:
        return data
    length = int(_safe(vector, "Length", 0) or 0)
    out = []
    for idx in range(min(length, max_points)):
        for candidate in (idx, idx + 1):
            try:
                out.append(_jsonable_number(vector.GetValueAt(candidate)))
                break
            except Exception:
                continue
    return out


def _scatter_points_to_list(results, method_name: str, count: int, max_points: int) -> list[dict]:
    method = getattr(results, method_name, None)
    if method is None or count <= 0:
        return []
    points = []
    for idx in range(min(count, max_points)):
        point = None
        for candidate in (idx, idx + 1):
            try:
                point = method(candidate)
                break
            except Exception:
                continue
        if point is None:
            continue
        item = _scatter_point_to_dict(point)
        if item:
            points.append(item)
    return points


def _scatter_point_to_dict(point) -> dict:
    value = _safe(point, "Value", None)
    item: dict = {
        "x": _jsonable_number(_safe(point, "X", None)),
        "y": _jsonable_number(_safe(point, "Y", None)),
    }
    rgb = _rgb_to_dict(value)
    if rgb:
        item["rgb"] = rgb
    else:
        item["value"] = _jsonable_number(value)
    return item


def _rgb_to_dict(value) -> dict | None:
    try:
        red = _safe(value, "R", None)
        green = _safe(value, "G", None)
        blue = _safe(value, "B", None)
    except Exception:
        return None
    if red is None and green is None and blue is None:
        return None
    return {"r": _jsonable_number(red), "g": _jsonable_number(green), "b": _jsonable_number(blue)}


def _matrix_to_list(matrix, max_points: int) -> list:
    if matrix is None:
        return []
    data = _array_to_list(_safe(matrix, "Data", []), max_points)
    rows = int(_safe(matrix, "Rows", 0) or 0)
    cols = int(_safe(matrix, "Cols", 0) or 0)
    if data and rows and cols:
        return [data[i * cols:(i + 1) * cols] for i in range(min(rows, max(1, max_points // max(cols, 1))))]
    out = []
    count = 0
    for row in range(rows):
        row_values = []
        for col in range(cols):
            if count >= max_points:
                break
            for r, c in ((row, col), (row + 1, col + 1)):
                try:
                    row_values.append(_jsonable_number(matrix.GetValueAt(r, c)))
                    break
                except Exception:
                    continue
            count += 1
        if row_values:
            out.append(row_values)
    return out


def _array_to_list(value, max_items: int) -> list:
    if value is None:
        return []
    try:
        items = list(value)
    except Exception:
        return []
    return [_jsonable_number(item) for item in items[:max_items]]


def _is_truncated_data(x_data, y_data, max_points: int) -> bool:
    try:
        return len(x_data) >= max_points or sum(len(row) if isinstance(row, list) else 1 for row in y_data) >= max_points
    except Exception:
        return False


_VALID_ANALYSIS_IMAGE_KINDS = {"png", "bmp", "jpeg", "wmf"}
_VIEWABLE_ANALYSIS_IMAGE_KINDS = {"png", "bmp", "jpeg"}
_ANALYSIS_IMAGE_SUFFIXES = ("png", "bmp", "jpg", "jpeg", "wmf")


def _export_verified_analysis_image(analysis, export_dir: Path, stem: str, preferred_path: Path | None = None) -> dict:
    """Export an Analysis image only if the file header proves it is an image.

    Some OpticStudio versions write a text summary through Analysis.ToFile even when
    the requested extension is .png/.bmp. Returning those paths makes downstream
    image viewers crash or fail, so invalid attempts are deleted immediately.
    """
    export_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[Path] = []
    if preferred_path is not None:
        candidates.append(preferred_path)
        for suffix in _ANALYSIS_IMAGE_SUFFIXES:
            fallback = preferred_path.with_suffix(f".{suffix}")
            if fallback not in candidates:
                candidates.append(fallback)
    else:
        candidates = [export_dir / f"{stem}.{suffix}" for suffix in _ANALYSIS_IMAGE_SUFFIXES]

    attempts = []
    errors = []
    for image_path in candidates:
        suffix = image_path.suffix.lower().lstrip(".") or "unknown"
        try:
            image_path.parent.mkdir(parents=True, exist_ok=True)
            _delete_file_quietly(image_path)
            analysis.ToFile(str(image_path), False, False)
            kind = _classify_export_file(image_path)
            size = image_path.stat().st_size if image_path.exists() else 0
            is_image = kind in _VALID_ANALYSIS_IMAGE_KINDS
            attempt = {
                "suffix": suffix,
                "path": str(image_path),
                "kind": kind,
                "bytes": size,
                "valid_image": is_image,
                "viewable_by_agent": kind in _VIEWABLE_ANALYSIS_IMAGE_KINDS,
            }
            attempts.append(attempt)
            if is_image:
                return {
                    "image_path": str(image_path),
                    "image_export_ok": True,
                    "image_export_kind": kind,
                    "image_export_is_bitmap": kind in _VIEWABLE_ANALYSIS_IMAGE_KINDS,
                    "image_export_is_image": True,
                    "image_export_is_viewable_by_agent": kind in _VIEWABLE_ANALYSIS_IMAGE_KINDS,
                    "image_export_attempts": attempts,
                }
            _delete_file_quietly(image_path)
        except Exception as e:
            errors.append({"suffix": suffix, "path": str(image_path), "error": str(e)})
            _delete_file_quietly(image_path)

    result: dict[str, object] = {
        "image_export_ok": False,
        "image_export_kind": "none",
        "image_export_is_bitmap": False,
        "image_export_is_image": False,
        "image_export_is_viewable_by_agent": False,
        "image_export_attempts": attempts,
        "image_export_note": "Analysis.ToFile 未生成可验证的图片文件；非图片导出已删除。",
    }
    if errors:
        result["image_export_errors"] = errors
    return result


def _delete_file_quietly(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def _classify_export_file(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except Exception:
        return "missing"
    if not raw:
        return "empty"
    header = raw[:64]
    if header.startswith(b"\x89PNG"):
        return "png"
    if header.startswith(b"BM"):
        return "bmp"
    if header.startswith(b"\xff\xd8"):
        return "jpeg"
    if header[:4] in (b"\xd7\xcd\xc6\x9a", b"\x01\x00\x09\x00"):
        return "wmf"

    text = _decode_export_header_text(raw[:512])
    if text:
        normalized = text.strip().lower()
        if normalized.startswith(("results", "zemax", "file:", "文件", "数据", "相对", "渐晕", "复色", "点列", "纵向")):
            return "text"
        printable = sum(1 for ch in normalized if ch.isprintable() or ch.isspace())
        if printable / max(1, len(normalized)) > 0.85:
            return "text"
    return "unknown"


def _decode_export_header_text(raw: bytes) -> str:
    encodings = ["utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp936", "latin-1"]
    for encoding in encodings:
        try:
            text = raw.decode(encoding, errors="ignore").replace("\x00", "").strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def _attach_rendered_fallback_image(payload: dict, analysis_key: str) -> None:
    exports = payload.get("exports")
    if not isinstance(exports, dict) or exports.get("image_export_ok") is not False:
        return
    results = payload.get("results") or {}
    export_dir = Path(str(exports.get("directory") or _WORKSPACE_ROOT))
    text_path = exports.get("text_path")
    stem = Path(str(text_path)).stem if text_path else f"{analysis_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    png_path = export_dir / f"{stem}_rendered.png"

    rendered = False
    try:
        spot_data = results.get("spot_data")
        if isinstance(spot_data, dict) and spot_data.get("fields"):
            _render_spot_summary_png(spot_data, png_path, results.get("spot_ray_points"))
            rendered = True
        elif results.get("data_series"):
            _render_data_series_summary_png(results.get("data_series") or [], png_path)
            rendered = True
    except Exception as e:
        errors = exports.get("image_export_errors")
        if not isinstance(errors, list):
            errors = []
            exports["image_export_errors"] = errors
        errors.append({"suffix": "rendered_png", "path": str(png_path), "error": str(e)})
        _delete_file_quietly(png_path)
        return

    if not rendered or _classify_export_file(png_path) != "png":
        _delete_file_quietly(png_path)
        return

    spot_ray_points = (results.get("spot_ray_points") or {}) if isinstance(results, dict) else {}
    if analysis_key == "standard_spot" and int(spot_ray_points.get("point_count") or 0) > 0:
        semantics = "spot_ray_intercepts_reax_reay"
        note = "Zemax Analysis.ToFile 未生成真图片；MCP 已用 REAX/REAY 真实光线截距采样渲染 PNG。"
    elif analysis_key == "standard_spot":
        semantics = "spot_rms_geo_summary_not_ray_scatter"
        note = "Zemax Analysis.ToFile 未生成真图片，且未取得真实光线截距；MCP 仅渲染 RMS/GEO 统计摘要，不代表真实点列分布。"
    else:
        semantics = "data_series_plot"
        note = "Zemax Analysis.ToFile 未生成真图片；MCP 已根据结构化分析数据渲染 PNG 曲线图。"

    exports.update({
        "image_path": str(png_path),
        "image_export_ok": True,
        "image_export_kind": "png",
        "image_export_is_bitmap": True,
        "image_export_is_image": True,
        "image_export_is_viewable_by_agent": True,
        "image_export_source": "rendered_fallback",
        "image_export_semantics": semantics,
        "image_export_note": note,
    })


def _render_spot_summary_png(spot_data: dict, path: Path, ray_points: dict | None = None,
                             airy_radius_mm: float | None = None,
                             rms_um_by_field: dict | None = None,
                             geo_um_by_field: dict | None = None) -> None:
    fields = spot_data.get("fields") or []
    n_fields = max(1, len(fields))
    if len(fields) <= 3:
        width = 746
        height = 520
    else:
        # 每格 250 内宽 + 左右各留 62 给轴刻度，避免首尾被裁掉
        width = 124 + 250 * n_fields
        height = 340
    canvas = _new_rgb_canvas(width, height, (255, 255, 255))

    all_geo = []
    all_rms = []
    for field in fields:
        for wave in field.get("waves") or []:
            geo = _finite_float(wave.get("geo_radius_lens_units"))
            rms = _finite_float(wave.get("rms_radius_lens_units"))
            if geo is not None:
                all_geo.append(abs(geo))
            if rms is not None:
                all_rms.append(abs(rms))
    max_radius = max(all_geo + all_rms + [1.0])
    colors = [(35, 85, 255), (0, 180, 0), (255, 40, 25)]

    if len(fields) <= 3:
        panels = [(60, 50, 220, 210), (370, 50, 530, 210), (215, 285, 375, 445)][:len(fields)]
        legend_x, legend_y = 615, 14
    else:
        # 固定步距 250（内宽 200），首格从 62 开始，给两侧轴刻度留白
        panels = []
        for idx in range(len(fields)):
            left = 62 + idx * 250
            panels.append((left, 70, left + 200, 260))
        legend_x, legend_y = width - 120, 14

    _draw_text(canvas, 18, 12, "STANDARD SPOT - REAX REAY" if ray_points else "STANDARD SPOT - RMS GEO SUMMARY", (30, 30, 30), scale=2)
    for wave_idx, color in enumerate(colors, start=1):
        y = legend_y + (wave_idx - 1) * 18
        _draw_marker(canvas, legend_x, y, color, wave_idx)
        _draw_text(canvas, legend_x + 16, y - 5, f"W{wave_idx}", (40, 40, 40), scale=1)

    ray_fields = _spot_ray_fields_by_index(ray_points)
    ray_scale = _spot_ray_plot_scale(ray_points, spot_data)
    geo_limits = _spot_geo_limits_by_field_wave(spot_data)

    for idx, field in enumerate(fields):
        left, top, right, bottom = panels[idx]
        cx = int((left + right) / 2)
        cy = int((top + bottom) / 2)
        radius_scale = min((right - left), (bottom - top)) * 0.42 / max_radius
        field_id = int(field.get("field") or idx + 1)
        _draw_grid_panel(canvas, left, top, right, bottom)
        ray_field = ray_fields.get(field_id)
        label_y = _finite_float(ray_field.get("field_y")) if isinstance(ray_field, dict) else None
        if label_y is not None:
            _draw_text(canvas, left, top - 22, f"OBJ {label_y:.2f} DEG", (35, 35, 35), scale=1)
        else:
            _draw_text(canvas, left, top - 22, f"FIELD {field_id}", (35, 35, 35), scale=1)
        _draw_text(canvas, right + 8, bottom - 10, "X", (35, 35, 35), scale=1)
        _draw_text(canvas, left + 8, top - 12, "Y", (35, 35, 35), scale=1)
        if field_id in ray_fields and ray_scale:
            scale_value, unit = ray_scale
            _draw_spot_axis_labels(canvas, left, top, right, bottom, scale_value, unit)
            _draw_spot_ray_points(canvas, ray_fields[field_id], left, top, right, bottom, colors, scale_value, geo_limits.get(field_id, {}))
            # 艾里斑参考圆（对应 Zemax 点列图里的 Airy Disk 圈）
            if airy_radius_mm and scale_value > 0:
                half_w = max(1, (right - left) * 0.44)
                half_h = max(1, (bottom - top) * 0.44)
                r_px = int(round((airy_radius_mm / scale_value) * (half_w + half_h) / 2.0))
                if r_px >= 1:
                    _draw_circle(canvas, cx, cy, r_px, (255, 140, 0))
                    _draw_text(canvas, left + 8, top + 6, "AIRY", (230, 110, 0), scale=1)
            image_y = _spot_field_image_coordinate(field, ray_fields[field_id])
            if image_y is not None:
                _draw_text(canvas, left, bottom + 24, f"IMG {image_y:.3f} MM", (70, 70, 70), scale=1)
            display_scale = scale_value * 2000.0 if unit == "UM" else scale_value * 2.0
            _draw_text(canvas, left, bottom + 38, f"SCALE {_format_axis_value(display_scale)} {unit}", (70, 70, 70), scale=1)
            # 每个视场的 RMS / GEO 数值（Zemax 原生点列图会在每格下方列这两项）
            rms_um = (rms_um_by_field or {}).get(field_id)
            geo_um = (geo_um_by_field or {}).get(field_id)
            if rms_um is not None or geo_um is not None:
                parts = [f"RMS {rms_um:.2f}" if rms_um is not None else "RMS -"]
                if geo_um is not None:
                    parts.append(f"GEO {geo_um:.2f}")
                parts.append("UM")
                _draw_text(canvas, left, bottom + 52, "  ".join(parts), (25, 25, 25), scale=1)
        else:
            _draw_text(canvas, left, bottom + 24, "RMS GEO", (70, 70, 70), scale=1)
            for wave_idx, wave in enumerate(field.get("waves") or []):
                color = colors[wave_idx % len(colors)]
                geo = _finite_float(wave.get("geo_radius_lens_units"))
                rms = _finite_float(wave.get("rms_radius_lens_units"))
                rms_x = abs(_finite_float(wave.get("rms_x_lens_units")) or rms or geo or 1.0)
                rms_y = abs(_finite_float(wave.get("rms_y_lens_units")) or rms or geo or 1.0)
                geo = abs(geo or rms or max_radius * 0.5)
                _draw_spot_cloud(canvas, cx, cy, rms_x * radius_scale, rms_y * radius_scale, geo * radius_scale, color, wave_idx + 1)
    _write_png(path, canvas)


def _render_data_series_summary_png(data_series: list, path: Path) -> None:
    series_list = [s for s in data_series if isinstance(s, dict) and s.get("x_data") and s.get("y_data")][:6]
    if not series_list:
        raise ValueError("no plottable data series")
    width = 1000
    height = 620
    canvas = _new_rgb_canvas(width, height, (255, 255, 255))
    cols = 2
    rows = math.ceil(len(series_list) / cols)
    panel_w = width // cols
    panel_h = height // rows
    colors = [(35, 116, 225), (226, 74, 60), (45, 150, 85), (150, 85, 190)]
    _draw_text(canvas, 24, 10, "ANALYSIS DATA SERIES", (30, 30, 30), scale=2)
    for idx, series in enumerate(series_list):
        col = idx % cols
        row = idx // cols
        left = col * panel_w + 38
        top = row * panel_h + 46
        right = (col + 1) * panel_w - 28
        bottom = (row + 1) * panel_h - 38
        curves = _series_numeric_curves(series)
        all_points = [point for curve in curves[:4] for point in curve]
        if not all_points:
            continue
        xs = [p[0] for p in all_points]
        ys = [p[1] for p in all_points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        if abs(max_x - min_x) < 1e-12:
            max_x = min_x + 1.0
        if abs(max_y - min_y) < 1e-12:
            max_y = min_y + 1.0
        y_pad = (max_y - min_y) * 0.08
        min_y -= y_pad
        max_y += y_pad
        _draw_plot_axes(canvas, left, top, right, bottom, min_x, max_x, min_y, max_y)
        _draw_text(canvas, left, top - 18, f"S{idx + 1}", (35, 35, 35), scale=1)
        for curve_idx, points in enumerate(curves[:4]):
            if len(points) < 2:
                continue
            last = None
            for x, y in points:
                px = int(left + (x - min_x) / (max_x - min_x) * max(1, right - left))
                py = int(bottom - (y - min_y) / (max_y - min_y) * max(1, bottom - top))
                if last is not None:
                    _draw_line(canvas, last[0], last[1], px, py, colors[curve_idx % len(colors)])
                last = (px, py)
            lx = right - 70
            ly = top + 12 + curve_idx * 13
            _draw_line(canvas, lx, ly, lx + 22, ly, colors[curve_idx % len(colors)])
            _draw_text(canvas, lx + 28, ly - 4, f"C{curve_idx + 1}", (40, 40, 40), scale=1)
    _write_png(path, canvas)


def _series_numeric_curves(series: dict) -> list[list[tuple[float, float]]]:
    x_data = series.get("x_data") or []
    y_data = series.get("y_data") or []
    curves: list[list[tuple[float, float]]] = []
    for idx, x in enumerate(x_data):
        x_value = _finite_float(x)
        if x_value is None:
            continue
        cells = []
        if len(y_data) == len(x_data) and idx < len(y_data):
            cells = y_data[idx] if isinstance(y_data[idx], list) else [y_data[idx]]
        else:
            cells = [row[idx] for row in y_data if isinstance(row, list) and idx < len(row)]
        values = []
        for cell in cells:
            values.extend(_numeric_values_from_series_cell(cell))
        for value_idx, value in enumerate(values[:4]):
            y_value = _finite_float(value)
            if y_value is None:
                continue
            while len(curves) <= value_idx:
                curves.append([])
            curves[value_idx].append((x_value, y_value))
    return curves


def _normalized_field_coordinates(sys_data, conn) -> dict[int, tuple[float, float]]:
    coords = {}
    try:
        fields = sys_data.Fields
        n = int(fields.NumberOfFields)
    except Exception:
        return coords
    raw = {}
    max_radius = 0.0
    for idx in range(1, n + 1):
        try:
            field = fields.GetField(idx)
            fx, fy, _ = conn.get_field_data(field)
            fx = float(fx or 0.0)
            fy = float(fy or 0.0)
        except Exception:
            fx, fy = 0.0, float(idx - 1)
        raw[idx] = (fx, fy)
        max_radius = max(max_radius, math.hypot(fx, fy))
    if max_radius <= 0:
        denom = max(1, n - 1)
        return {idx: (0.0, (idx - 1) / denom) for idx in range(1, n + 1)}
    return {idx: (fx / max_radius, fy / max_radius) for idx, (fx, fy) in raw.items()}


def _raw_field_coordinates(sys_data, conn) -> dict[int, tuple[float, float]]:
    coords = {}
    try:
        fields = sys_data.Fields
        n = int(fields.NumberOfFields)
    except Exception:
        return coords
    for idx in range(1, n + 1):
        try:
            field = fields.GetField(idx)
            fx, fy, _ = conn.get_field_data(field)
            coords[idx] = (float(fx or 0.0), float(fy or 0.0))
        except Exception:
            coords[idx] = (0.0, float(idx - 1))
    return coords


def _spot_pupil_sample_points(rings: int = 4) -> list[tuple[float, float]]:
    points = [(0.0, 0.0)]
    for ring in range(1, rings + 1):
        radius = ring / rings
        count = max(8, ring * 8)
        for idx in range(count):
            angle = 2 * math.pi * idx / count
            points.append((round(radius * math.cos(angle), 8), round(radius * math.sin(angle), 8)))
    return points


def _spot_ray_fields_by_index(ray_points: dict | None) -> dict[int, dict]:
    if not isinstance(ray_points, dict):
        return {}
    out = {}
    for field in ray_points.get("fields") or []:
        try:
            out[int(field.get("field"))] = field
        except Exception:
            continue
    return out


def _spot_field_image_coordinate(spot_field: dict, ray_field: dict | None = None) -> float | None:
    refs = []
    for wave in spot_field.get("waves") or []:
        value = _finite_float(wave.get("ref_y"))
        if value is not None:
            refs.append(value)
    if refs:
        return sum(refs) / len(refs)
    if isinstance(ray_field, dict):
        chiefs = []
        for wave in ray_field.get("waves") or []:
            points = wave.get("points") or []
            if points:
                value = _finite_float(points[0].get("y"))
                if value is not None:
                    chiefs.append(value)
        if chiefs:
            return sum(chiefs) / len(chiefs)
    return None


def _spot_geo_limits_by_field_wave(spot_data: dict) -> dict[int, dict[int, float]]:
    limits = {}
    for field in spot_data.get("fields") or []:
        try:
            field_id = int(field.get("field"))
        except Exception:
            continue
        wave_limits = {}
        for wave in field.get("waves") or []:
            try:
                wave_id = int(wave.get("wave"))
            except Exception:
                continue
            geo = _finite_float(wave.get("geo_radius_lens_units"))
            if geo is not None and geo > 0:
                wave_limits[wave_id] = geo
        limits[field_id] = wave_limits
    return limits


def _spot_radius_unit_factor(spot_data: dict, ray_points: dict | None) -> float:
    """判断 spot_data 里 geo/rms 半径的实际单位，返回换算到 µm 的系数。

    `*_lens_units` 这个键名并不可靠（可能已是 µm）。做法：用光线点算出的
    真实最大半径（点坐标确定是 mm）当标尺，与 geo 最大值比比值——同量级即 mm。

    Returns: 1.0 表示已是 µm；1000.0 表示是 mm。
    """
    try:
        ref_max = 0.0
        for field in (ray_points or {}).get("fields") or []:
            for wave in field.get("waves") or []:
                pts = wave.get("points") or []
                if not pts:
                    continue
                rx = _finite_float(pts[0].get("x")) or 0.0
                ry = _finite_float(pts[0].get("y")) or 0.0
                for p in pts:
                    x = _finite_float(p.get("x"))
                    y = _finite_float(p.get("y"))
                    if x is None or y is None:
                        continue
                    ref_max = max(ref_max, math.hypot(x - rx, y - ry))
        geo_max = 0.0
        for field in spot_data.get("fields") or []:
            for wave in field.get("waves") or []:
                g = _finite_float(wave.get("geo_radius_lens_units"))
                if g is not None:
                    geo_max = max(geo_max, abs(g))
        if ref_max <= 0 or geo_max <= 0:
            return 1.0
        ratio = geo_max / ref_max
        # geo 若与 mm 计的射线半径同量级 → 它是 mm，需要 ×1000 才是 µm
        return 1000.0 if ratio < 50 else 1.0
    except Exception:
        return 1.0


def _spot_ray_plot_scale(ray_points: dict | None, spot_data: dict | None = None):
    if not isinstance(ray_points, dict):
        return None
    if isinstance(spot_data, dict):
        half_width = max(abs(_finite_float(spot_data.get("half_width_x")) or 0.0),
                         abs(_finite_float(spot_data.get("half_width_y")) or 0.0))
        if half_width > 0:
            if half_width < 0.25:
                return half_width, "UM"
            return half_width, "LENS"
    values = []
    for field in ray_points.get("fields") or []:
        for wave in field.get("waves") or []:
            wave_points = wave.get("points") or []
            if not wave_points:
                continue
            ref_x = _finite_float(wave_points[0].get("x")) or 0.0
            ref_y = _finite_float(wave_points[0].get("y")) or 0.0
            for point in wave_points:
                x = _finite_float(point.get("x"))
                y = _finite_float(point.get("y"))
                if x is not None and y is not None:
                    values.extend([abs(x - ref_x), abs(y - ref_y)])
    if not values:
        return None
    max_abs = max(values)
    if max_abs < 0.25:
        nice_um = _nice_axis_limit(max_abs * 1000.0)
        return max(nice_um / 1000.0, 1e-12), "UM"
    return max(_nice_axis_limit(max_abs), 1e-9), "LENS"


def _draw_spot_ray_points(canvas, field_points: dict, left: int, top: int, right: int, bottom: int,
                          colors: list[tuple[int, int, int]], scale_value: float,
                          geo_limits: dict[int, float] | None = None) -> None:
    cx = (left + right) // 2
    cy = (top + bottom) // 2
    half_w = max(1, (right - left) * 0.44)
    half_h = max(1, (bottom - top) * 0.44)
    raw_scale = max(float(scale_value), 1e-12)
    for wave_idx, wave in enumerate(field_points.get("waves") or []):
        color = colors[wave_idx % len(colors)]
        marker = wave_idx + 1
        wave_points = wave.get("points") or []
        if not wave_points:
            continue
        ref_x = _finite_float(wave_points[0].get("x")) or 0.0
        ref_y = _finite_float(wave_points[0].get("y")) or 0.0
        geo_limit = None
        if isinstance(geo_limits, dict):
            try:
                geo_limit = _finite_float(geo_limits.get(int(wave.get("wave"))))
            except Exception:
                geo_limit = None
        for point in wave_points:
            x = _finite_float(point.get("x"))
            y = _finite_float(point.get("y"))
            if x is None or y is None:
                continue
            rel_x = x - ref_x
            rel_y = y - ref_y
            if geo_limit is not None and math.hypot(rel_x, rel_y) * 1000.0 > geo_limit * 1.08:
                continue
            px = cx + int((rel_x / raw_scale) * half_w)
            py = cy - int((rel_y / raw_scale) * half_h)
            _draw_marker(canvas, px, py, color, marker)


def _nice_axis_limit(value: float) -> float:
    value = abs(float(value))
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    fraction = value / (10 ** exponent)
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return nice * (10 ** exponent)


def _draw_spot_axis_labels(canvas, left: int, top: int, right: int, bottom: int, raw_scale: float, unit: str) -> None:
    display_scale = raw_scale * 1000.0 if unit == "UM" else raw_scale
    labels = [(-display_scale, left + 4), (0.0, (left + right) // 2 - 10), (display_scale, right - 40)]
    for value, x in labels:
        _draw_text(canvas, int(x), bottom + 8, _format_axis_value(value), (65, 65, 65), scale=1)
    y_labels = [(-display_scale, bottom - 8), (0.0, (top + bottom) // 2 - 4), (display_scale, top + 4)]
    for value, y in y_labels:
        _draw_text(canvas, left - 44, int(y), _format_axis_value(value), (65, 65, 65), scale=1)


def _new_rgb_canvas(width: int, height: int, color: tuple[int, int, int]) -> list[bytearray]:
    row = bytearray(color * width)
    return [bytearray(row) for _ in range(height)]


def _write_png(path: Path, canvas: list[bytearray]) -> None:
    height = len(canvas)
    width = len(canvas[0]) // 3 if height else 0
    if width <= 0 or height <= 0:
        raise ValueError("empty canvas")
    raw = b"".join(b"\x00" + bytes(row) for row in canvas)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.parent.mkdir(parents=True, exist_ok=True)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def _set_pixel(canvas: list[bytearray], x: int, y: int, color: tuple[int, int, int]) -> None:
    if y < 0 or y >= len(canvas) or x < 0 or x >= len(canvas[y]) // 3:
        return
    idx = x * 3
    canvas[y][idx:idx + 3] = bytes(color)


def _draw_rect(canvas, x1, y1, x2, y2, color, fill=False) -> None:
    x1, x2 = sorted((int(x1), int(x2)))
    y1, y2 = sorted((int(y1), int(y2)))
    if fill:
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                _set_pixel(canvas, x, y, color)
        return
    _draw_line(canvas, x1, y1, x2, y1, color)
    _draw_line(canvas, x2, y1, x2, y2, color)
    _draw_line(canvas, x2, y2, x1, y2, color)
    _draw_line(canvas, x1, y2, x1, y1, color)


def _draw_line(canvas, x1, y1, x2, y2, color) -> None:
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    dx = abs(x2 - x1)
    dy = -abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx + dy
    while True:
        _set_pixel(canvas, x1, y1, color)
        if x1 == x2 and y1 == y2:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x1 += sx
        if e2 <= dx:
            err += dx
            y1 += sy


def _draw_circle(canvas, cx, cy, radius, color, fill=False) -> None:
    radius = int(radius)
    if radius <= 0:
        return
    if fill:
        for y in range(-radius, radius + 1):
            max_x = int(math.sqrt(max(0, radius * radius - y * y)))
            for x in range(-max_x, max_x + 1):
                _set_pixel(canvas, int(cx) + x, int(cy) + y, color)
        return
    x = radius
    y = 0
    err = 0
    while x >= y:
        for px, py in ((x, y), (y, x), (-y, x), (-x, y), (-x, -y), (-y, -x), (y, -x), (x, -y)):
            _set_pixel(canvas, int(cx) + px, int(cy) + py, color)
        y += 1
        if err <= 0:
            err += 2 * y + 1
        if err > 0:
            x -= 1
            err -= 2 * x + 1


def _draw_grid_panel(canvas, left: int, top: int, right: int, bottom: int) -> None:
    for x in range(left, right + 1, 16):
        _draw_line(canvas, x, top, x, bottom, (224, 224, 224))
    for y in range(top, bottom + 1, 16):
        _draw_line(canvas, left, y, right, y, (224, 224, 224))
    cx = (left + right) // 2
    cy = (top + bottom) // 2
    _draw_line(canvas, left, cy, right, cy, (120, 120, 120))
    _draw_line(canvas, cx, top, cx, bottom, (120, 120, 120))
    for x in range(left, right + 1, 16):
        _draw_line(canvas, x, cy - 3, x, cy + 3, (100, 100, 100))
    for y in range(top, bottom + 1, 16):
        _draw_line(canvas, cx - 3, y, cx + 3, y, (100, 100, 100))
    _draw_rect(canvas, left, top, right, bottom, (205, 205, 205), fill=False)


def _draw_plot_axes(canvas, left: int, top: int, right: int, bottom: int,
                    min_x: float, max_x: float, min_y: float, max_y: float) -> None:
    for i in range(6):
        x = int(left + (right - left) * i / 5)
        y = int(top + (bottom - top) * i / 5)
        _draw_line(canvas, x, top, x, bottom, (232, 232, 232))
        _draw_line(canvas, left, y, right, y, (232, 232, 232))
    zero_x = None
    zero_y = None
    if min_x <= 0 <= max_x:
        zero_x = int(left + (0 - min_x) / (max_x - min_x) * (right - left))
    if min_y <= 0 <= max_y:
        zero_y = int(bottom - (0 - min_y) / (max_y - min_y) * (bottom - top))
    _draw_line(canvas, left, zero_y if zero_y is not None else bottom, right, zero_y if zero_y is not None else bottom, (80, 80, 80))
    _draw_line(canvas, zero_x if zero_x is not None else left, top, zero_x if zero_x is not None else left, bottom, (80, 80, 80))
    _draw_rect(canvas, left, top, right, bottom, (190, 190, 190), fill=False)
    for i in range(3):
        x_val = min_x + (max_x - min_x) * i / 2
        y_val = min_y + (max_y - min_y) * i / 2
        x = int(left + (right - left) * i / 2)
        y = int(bottom - (bottom - top) * i / 2)
        _draw_text(canvas, x - 18, bottom + 8, _format_axis_value(x_val), (55, 55, 55), scale=1)
        _draw_text(canvas, left - 34, y - 4, _format_axis_value(y_val), (55, 55, 55), scale=1)
    _draw_text(canvas, right + 8, bottom - 10, "X", (45, 45, 45), scale=1)
    _draw_text(canvas, left + 8, top - 12, "Y", (45, 45, 45), scale=1)


def _format_axis_value(value: float) -> str:
    value = float(value)
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _draw_marker(canvas, x: int, y: int, color: tuple[int, int, int], marker: int) -> None:
    if marker % 3 == 1:
        _draw_line(canvas, x - 3, y, x + 3, y, color)
        _draw_line(canvas, x, y - 3, x, y + 3, color)
    elif marker % 3 == 2:
        _draw_rect(canvas, x - 3, y - 3, x + 3, y + 3, color, fill=False)
    else:
        _draw_line(canvas, x, y - 4, x - 4, y + 3, color)
        _draw_line(canvas, x - 4, y + 3, x + 4, y + 3, color)
        _draw_line(canvas, x + 4, y + 3, x, y - 4, color)


def _draw_spot_cloud(canvas, cx: int, cy: int, rms_x: float, rms_y: float, geo_radius: float,
                     color: tuple[int, int, int], marker: int) -> None:
    rms_x = max(2.0, float(rms_x))
    rms_y = max(2.0, float(rms_y))
    geo_radius = max(rms_x, rms_y, float(geo_radius))
    for ring, count in ((0.35, 16), (0.65, 24), (1.0, 32)):
        for i in range(count):
            angle = (2 * math.pi * i / count) + ring * 0.37
            wobble = 1.0 + 0.12 * math.sin(i * 1.7 + marker)
            x = cx + int(math.cos(angle) * rms_x * ring * wobble)
            y = cy + int(math.sin(angle) * rms_y * ring * wobble)
            _draw_marker(canvas, x, y, color, marker)
    # A sparse outer contour hints at the geometric radius without drawing a heavy circle.
    for i in range(18):
        angle = 2 * math.pi * i / 18
        x = cx + int(math.cos(angle) * geo_radius * 0.82)
        y = cy + int(math.sin(angle) * geo_radius * 0.82)
        _draw_marker(canvas, x, y, color, marker)


_DIGITS_3X5 = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    ".": ("000", "000", "000", "000", "010"),
    "-": ("000", "000", "111", "000", "000"),
}


def _draw_digits(canvas, x: int, y: int, text: str, color: tuple[int, int, int], scale: int = 2) -> None:
    cursor = int(x)
    for ch in str(text):
        pattern = _DIGITS_3X5.get(ch)
        if pattern is None:
            cursor += 4 * scale
            continue
        for row_idx, row in enumerate(pattern):
            for col_idx, bit in enumerate(row):
                if bit == "1":
                    _draw_rect(canvas, cursor + col_idx * scale, y + row_idx * scale, cursor + (col_idx + 1) * scale - 1, y + (row_idx + 1) * scale - 1, color, fill=True)
        cursor += 4 * scale


_FONT_5X7 = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10011", "10001", "10001", "01110"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}


def _draw_text(canvas, x: int, y: int, text: str, color: tuple[int, int, int], scale: int = 1) -> None:
    cursor = int(x)
    for ch in str(text).upper():
        pattern = _FONT_5X7.get(ch, _FONT_5X7[" "])
        for row_idx, row in enumerate(pattern):
            for col_idx, bit in enumerate(row):
                if bit == "1":
                    _draw_rect(canvas, cursor + col_idx * scale, y + row_idx * scale,
                               cursor + (col_idx + 1) * scale - 1, y + (row_idx + 1) * scale - 1,
                               color, fill=True)
        cursor += 6 * scale


def _finite_float(value):
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _set_field_vignetting(field_obj, vcx=None, vcy=None):
    """在 IField 对象上设置渐晕压缩因子 VCX/VCY (0~1，1=无渐晕)。

    属性名已在连接层探测确认为 VCX / VCY（_prop_map_put_ 可写）。
    仅当传入值不为 None 时才写入，避免覆盖未指定的方向。
    """
    if field_obj is None:
        return
    if vcx is not None:
        try:
            setattr(field_obj, "VCX", float(vcx))
        except Exception:
            pass
    if vcy is not None:
        try:
            setattr(field_obj, "VCY", float(vcy))
        except Exception:
            pass


def _read_exported_text(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        raw = p.read_bytes()
    except Exception:
        return ""
    if not raw:
        return ""

    null_ratio = raw[:4096].count(b"\x00") / max(1, min(len(raw), 4096))
    encodings = ["utf-8-sig", "utf-16", "cp936", "latin-1"]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or null_ratio > 0.2:
        encodings = ["utf-16", "utf-16-le", "utf-16-be", "utf-8-sig", "cp936", "latin-1"]
    for encoding in encodings:
        try:
            text = raw.decode(encoding, errors="ignore")
            if text and text.count("\x00") / max(1, len(text)) < 0.05:
                return text.replace("\ufeff", "")
        except Exception:
            continue
    return ""


def _text_result_stats(text: str) -> dict:
    total = text.count("------------")
    numeric = len(_extract_floats(text))
    return {"dash_missing_count": total, "numeric_token_count": numeric, "line_count": len(text.splitlines())}


def _analysis_capture_warnings(payload: dict) -> list[str]:
    warnings = []
    exports = payload.get("exports", {})
    if exports.get("image_export_ok") is False:
        warnings.append("Analysis.ToFile 未生成可验证的图片文件；已删除非图片导出，请优先查看 text_path 或 Zemax 图窗。")
    elif exports.get("image_path") and not exports.get("image_export_is_viewable_by_agent", False):
        warnings.append("Analysis.ToFile 仅生成了有效矢量图/非位图图片；Agent 可能无法直接预览，请在 Zemax 或系统图片工具中查看。")
    text_stats = payload.get("text_stats", {})
    if text_stats.get("dash_missing_count", 0) > 0:
        warnings.append("文本结果包含 '------------'，表示部分采样光线缺失、被遮拦或追迹失败。")
    return warnings


def _extract_floats(text: str) -> list[float]:
    import re
    values = []
    for match in re.finditer(r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?", text or ""):
        try:
            values.append(float(match.group(0)))
        except Exception:
            pass
    return values


def _parse_relative_illumination_from_capture(capture: dict) -> dict:
    text = _read_exported_text(capture.get("exports", {}).get("text_path")) or capture.get("text_preview", "")
    if not text:
        return {}
    fields = []
    table_started = False
    for line in text.splitlines():
        normalized = line.strip()
        lower = normalized.lower()
        if "rel." in lower or "illum" in lower or "f/#" in lower or "相对照度" in normalized:
            table_started = True
            continue
        if not table_started:
            continue
        nums = _extract_floats(line)
        if len(nums) >= 3 and not any(token in line.lower() for token in ("wave", "波长")):
            y_val, rel, f_eff = nums[0], nums[1], nums[2]
            if 0.0 <= rel <= 1.5:
                fields.append({
                    "field_y": y_val,
                    "relative_illumination": rel,
                    "f_number_efficiency": f_eff,
                    "status": _illumination_status(rel, float(capture.get("threshold", 0.05))),
                })
    if not fields:
        return {}
    return {
        "field_type": "angle_or_analysis_axis",
        "fields": fields,
        "max_field_relative_illumination": fields[-1].get("relative_illumination"),
    }


def _illumination_status(value, threshold: float) -> str:
    if value is None:
        return "unknown"
    try:
        value = float(value)
    except Exception:
        return "unknown"
    if value <= 1e-6:
        return "zero"
    if value < threshold:
        return "low"
    return "ok"


def _illumination_drop_events(fields: list[dict]) -> list[dict]:
    events = []
    previous = None
    for item in fields:
        value = item.get("relative_illumination")
        if not isinstance(value, (int, float)):
            previous = item
            continue
        if previous and isinstance(previous.get("relative_illumination"), (int, float)):
            prev_value = previous["relative_illumination"]
            if prev_value > 0 and value / prev_value < 0.6:
                events.append({
                    "from_field_y": previous.get("field_y"),
                    "to_field_y": item.get("field_y"),
                    "from_relative_illumination": prev_value,
                    "to_relative_illumination": value,
                    "ratio": round(value / prev_value, 6),
                })
        previous = item
    return events


def _series_rows_from_capture(capture: dict) -> list[dict]:
    rows = []
    for series in capture.get("results", {}).get("data_series", []):
        x_data = series.get("x_data") or []
        y_data = series.get("y_data") or []
        labels = series.get("series_labels") or []
        for idx, x in enumerate(x_data):
            values = []
            if len(y_data) == len(x_data) and idx < len(y_data):
                values.extend(_numeric_values_from_series_cell(y_data[idx]))
            else:
                for row in y_data:
                    if isinstance(row, list) and idx < len(row):
                        values.extend(_numeric_values_from_series_cell(row[idx]))
            rows.append({"x": x, "labels": labels, "values": values})
    return rows


def _numeric_values_from_series_cell(value) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)) and math.isfinite(value):
        return [float(value)]
    if isinstance(value, str):
        return [v for v in _extract_floats(value) if math.isfinite(v)]
    if isinstance(value, (list, tuple)):
        values = []
        for item in value:
            values.extend(_numeric_values_from_series_cell(item))
        return values
    return []


def _first_numeric(values: list):
    for value in values:
        if isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
    return None


def _spot_data_from_capture(capture: dict, sys_data, conn) -> list[dict]:
    spot_data = capture.get("results", {}).get("spot_data", {})
    output = []
    for field_entry in spot_data.get("fields", []):
        field_idx = field_entry.get("field")
        try:
            field_obj = sys_data.Fields.GetField(int(field_idx))
            fx, fy, _ = conn.get_field_data(field_obj)
        except Exception:
            fx, fy = None, None
        waves = field_entry.get("waves", [])
        rms_vals = [w.get("rms_radius_lens_units") for w in waves if isinstance(w.get("rms_radius_lens_units"), (int, float))]
        geo_vals = [w.get("geo_radius_lens_units") for w in waves if isinstance(w.get("geo_radius_lens_units"), (int, float))]
        output.append({
            "field": field_idx,
            "field_x": fx,
            "field_y": fy,
            "rms_radius_lens_units": max(rms_vals) if rms_vals else None,
            "geo_radius_lens_units": max(geo_vals) if geo_vals else None,
            "waves": waves,
        })
    return output


def _parse_spot_text_from_capture(capture: dict) -> list[dict]:
    text = _read_exported_text(capture.get("exports", {}).get("text_path")) or capture.get("text_preview", "")
    if not text:
        return []
    fields = []
    current = None
    for line in text.splitlines():
        nums = _extract_floats(line)
        if "视场坐标" in line and len(nums) >= 2:
            current = {"field_x": nums[0], "field_y": nums[1]}
            fields.append(current)
        elif current is not None and "RMS" in line and "半径" in line and nums:
            current["rms_radius_um"] = nums[0]
        elif current is not None and ("最大光斑" in line or "Geo" in line) and nums:
            current["geo_radius_um"] = nums[0]
    return fields


def _is_zero_number(value) -> bool:
    return isinstance(value, (int, float)) and abs(value) <= 1e-12


def _mtf_series_warnings(capture: dict) -> list[str]:
    values = []
    for row in _series_rows_from_capture(capture):
        for value in row.get("values", []):
            if isinstance(value, (int, float)) and math.isfinite(value):
                values.append(float(value))
    if not values:
        return ["FFT MTF vs Field 未返回有效数值；应检查分析设置、通光状态和文本导出。"]
    warnings = []
    if all(abs(v) <= 1e-9 for v in values):
        warnings.append("MTF vs Field 所有采样为 0；优先检查频率、截止频率和最大视场通光。")
    if any(v < -1e-6 or v > 1.000001 for v in values):
        warnings.append("MTF vs Field 出现超出 [0,1] 的数值，需与 Zemax 图窗交叉验证。")
    return warnings


def _mtf_vs_field_summary_from_text(capture: dict, requested_freqs: list[float], sys_data, conn) -> dict:
    text = _read_exported_text(capture.get("exports", {}).get("text_path")) or capture.get("text_preview", "")
    field_targets = _mtf_field_targets(sys_data, conn)
    sections = _parse_mtf_vs_field_sections(text)
    summaries = []
    for requested in requested_freqs:
        section = _nearest_mtf_section(sections, requested)
        if not section:
            summaries.append({"requested_frequency": requested, "error": "frequency section not found"})
            continue
        fields = []
        for target in field_targets:
            sample = _nearest_mtf_sample(section["samples"], target["normalized_field"])
            if sample:
                fields.append({
                    "field": target["field"],
                    "field_y": target["field_y"],
                    "normalized_field": target["normalized_field"],
                    "sampled_normalized_field": sample["field"],
                    "T": sample["T"],
                    "S": sample["S"],
                    "min_TS": min(sample["T"], sample["S"]),
                })
        min_value = min((f["min_TS"] for f in fields), default=None)
        summaries.append({
            "requested_frequency": requested,
            "actual_frequency": section["frequency"],
            "fields": fields,
            "min_mtf": min_value,
            "passes_0p3": (min_value is not None and min_value > 0.3),
        })
    return {
        "method": "parsed_fft_mtf_vs_field_text",
        "field_targets": field_targets,
        "frequencies": summaries,
    }


def _mtf_field_targets(sys_data, conn) -> list[dict]:
    normalized = _normalized_field_coordinates(sys_data, conn)
    raw = _raw_field_coordinates(sys_data, conn)
    targets = []
    try:
        num_fields = int(sys_data.Fields.NumberOfFields)
    except Exception:
        num_fields = len(normalized)
    for idx in range(1, num_fields + 1):
        hx, hy = normalized.get(idx, (0.0, 0.0))
        fx, fy = raw.get(idx, (0.0, float(idx - 1)))
        targets.append({
            "field": idx,
            "field_y": fy,
            "normalized_field": round(math.hypot(hx, hy), 10),
        })
    return targets


def _parse_mtf_vs_field_sections(text: str) -> list[dict]:
    sections = []
    current = None
    for line in (text or "").splitlines():
        if "空间频率数据" in line:
            nums = _extract_floats(line)
            if nums:
                current = {"frequency": float(nums[0]), "samples": []}
                sections.append(current)
            continue
        if current is None:
            continue
        parts = [p for p in line.split() if p]
        if len(parts) < 3:
            continue
        try:
            field = float(parts[0])
            tangential = float(parts[1])
            sagittal = float(parts[2])
        except Exception:
            continue
        current["samples"].append({"field": field, "T": tangential, "S": sagittal})
    return sections


def _nearest_mtf_section(sections: list[dict], frequency: float) -> dict | None:
    if not sections:
        return None
    return min(sections, key=lambda item: abs(float(item.get("frequency", 0.0)) - float(frequency)))


def _nearest_mtf_sample(samples: list[dict], normalized_field: float) -> dict | None:
    if not samples:
        return None
    return min(samples, key=lambda item: abs(float(item.get("field", 0.0)) - float(normalized_field)))


def _fan_valid_fraction_from_capture(capture: dict):
    text = _read_exported_text(capture.get("exports", {}).get("text_path")) or capture.get("text_preview", "")
    if not text:
        return None
    missing = text.count("------------")
    numeric = len(_extract_floats(text))
    denom = missing + numeric
    if denom <= 0:
        return None
    return round(numeric / denom, 6)


def _longitudinal_summary_from_capture(capture: dict) -> dict:
    text = _read_exported_text(capture.get("exports", {}).get("text_path")) or capture.get("text_preview", "")
    rows = []
    for line in text.splitlines():
        nums = _extract_floats(line)
        if len(nums) >= 4 and 0.0 <= nums[0] <= 1.0:
            rows.append(nums[:4])
    if not rows:
        return {"method_confidence": "low"}
    para = rows[0][1:]
    edge = rows[-1][1:]
    summary = {
        "paraxial_color_spread_mm": round(max(para) - min(para), 8),
        "edge_color_spread_mm": round(max(edge) - min(edge), 8),
        "edge_values_mm": edge,
        "method_confidence": "normal",
    }
    if summary["edge_color_spread_mm"] > max(summary["paraxial_color_spread_mm"] * 2, 0.005):
        summary["spherochromatism_warning"] = True
        summary["warnings"] = ["边缘光瞳三波长轴向相差分离明显，不能仅用 AXCL 判定 APO。"]
    return summary


def _color_series_warning(capture: dict) -> str | None:
    values = []
    for row in _series_rows_from_capture(capture):
        values.extend(v for v in row.get("values", []) if isinstance(v, (int, float)))
    if not values:
        return "未获得结构化垂轴色差数值；请查看文本导出或 Zemax 图窗。"
    if max(values) - min(values) > 0.01:
        return "垂轴色差曲线幅值较大，离轴视场需要结合 spot/MTF 继续诊断。"
    return None

def _refetch_last_row(mfe):
    """ChangeType() 调用可能使原 row COM 引用失效（内部创建新对象），
    通过 NumberOfOperands 行号重新获取最新有效引用。
    在 _set_row_operand_type 后立即调用，确保后续参数写入有效。
    """
    try:
        num = _safe(mfe, "NumberOfOperands", 0)
        return mfe.GetOperandAt(num)
    except Exception:
        return None


def _safe(obj, attr, default):
    """安全获取 COM 对象属性 (多策略: 直接 → prop_map → 模糊匹配)."""
    # 策略 1: 直接 getattr
    try:
        return getattr(obj, attr)
    except Exception:
        pass
    # 策略 2: 从 _prop_map_get_ 字典查找 (参考 PyZOS)
    prop_map = getattr(obj, "_prop_map_get_", None)
    if prop_map:
        # 精确匹配
        if attr in prop_map:
            try:
                return getattr(obj, attr)
            except Exception:
                pass
        # 模糊匹配 (大小写不敏感)
        for key in prop_map:
            if key.lower() == attr.lower():
                try:
                    return getattr(obj, key)
                except Exception:
                    pass
    return default


def _call_or_value(value):
    """若 COM 访问返回的是无参方法，则调用一次并返回其结果。"""
    try:
        return value()
    except TypeError:
        return value
    except Exception:
        return value
    return value


def _cast_to_system_tool(tool_obj):
    """将 ILocalOptimization / IQuickFocus 等 COM 对象转型为 ISystemTool.

    参考 PyZOS inheritance_dict:
        ILocalOptimization -> ISystemTool
        IQuickFocus -> ISystemTool
    RunAndWaitForCompletion() 和 Close() 定义在 ISystemTool 基类上,
    早期绑定生成的派生类包装器不包含基类方法, 必须 CastTo。
    """
    from win32com.client import CastTo
    try:
        return CastTo(tool_obj, "ISystemTool")
    except Exception:
        # 如果 CastTo 失败 (如某些版本接口名不同), 尝试直接返回
        # 在后期绑定场景下对象可能已经有这些方法
        return tool_obj


def _safe_set_attr(obj, attr, value):
    """安全设置 COM 对象属性, 静默忽略失败. 返回是否成功."""
    try:
        setattr(obj, attr, value)
        return True
    except Exception:
        return False


def _format_mtime(path: Path | None) -> str | None:
    """格式化文件修改时间。"""
    if path is None:
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _attach_dispatch_metadata(result_str: str, backup_info: dict | None) -> str:
    """将 dispatch 级元数据附加到工具 JSON 返回值中。"""
    if not backup_info:
        return result_str
    try:
        payload = json.loads(result_str)
        if not isinstance(payload, dict):
            return result_str
        payload.update(backup_info)
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception:
        return result_str


_OPERAND_PARAM_ALIASES = {
    "int1": 1,
    "int2": 2,
    "hx": 3,
    "hy": 4,
    "px": 5,
    "py": 6,
    "ex": 7,
    "ey": 8,
    "param1": 1,
    "param2": 2,
    "param3": 3,
    "param4": 4,
    "param5": 5,
    "param6": 6,
    "param7": 7,
    "param8": 8,
}

_OPERAND_PARAM_NAMES = {
    1: "int1",
    2: "int2",
    3: "hx",
    4: "hy",
    5: "px",
    6: "py",
    7: "ex",
    8: "ey",
}


def _jsonable_number(value):
    """将 COM/API 返回值转换成 JSON 友好的值。"""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    try:
        return str(value)
    except Exception:
        return f"<{value.__class__.__name__}>"


def _apply_operand_cell_values(row, int1=None, int2=None, **cell_values):
    """按别名写入 MFE 参数单元格，返回逐项写入结果。"""
    requested = {"int1": int1, "int2": int2}
    requested.update(cell_values or {})

    param_values = {}
    for key in ("int1", "int2", "hx", "hy", "px", "py", "ex", "ey"):
        value = requested.get(key)
        if value is not None:
            param_values[_OPERAND_PARAM_ALIASES[key]] = value
    for param_num in range(1, 9):
        key = f"param{param_num}"
        value = requested.get(key)
        if value is not None:
            param_values[param_num] = value

    results = []
    for param_num in sorted(param_values):
        results.append(_write_operand_param(row, param_num, param_values[param_num]))
    return results


def _write_operand_param(row, param_num: int, value):
    """写入 MFE ParamN 单元格。Param1/2 优先整数，其余优先浮点。"""
    col_idx = param_num + 1
    result = {
        "param": param_num,
        "name": _OPERAND_PARAM_NAMES.get(param_num, f"param{param_num}"),
        "col": col_idx,
        "requested": value,
        "ok": False,
    }
    try:
        cell = row.GetOperandCell(col_idx)
    except Exception as e:
        result["error"] = str(e)
        return result

    if cell is None:
        result["error"] = "GetOperandCell returned None"
        return result

    order = ["int", "double", "value"] if param_num <= 2 else ["double", "value", "int"]
    last_error = None
    for mode in order:
        try:
            if mode == "int":
                cell.IntegerValue = int(round(float(value)))
                read_back = _jsonable_number(cell.IntegerValue)
            elif mode == "double":
                cell.DoubleValue = float(value)
                read_back = _jsonable_number(cell.DoubleValue)
            else:
                cell.Value = str(value)
                read_back = cell.Value
            result.update({"ok": True, "mode": mode, "read_back": read_back})
            return result
        except Exception as e:
            last_error = e

    result["error"] = str(last_error) if last_error else "unknown write failure"
    return result


def _write_mtf_operand_params(row, wave_idx: int, frequency: float, normalized_field: float, sampling: int = 1):
    """Write MTFT/MTFS cells using the convention seen in Zemax MF files.

    Layout: Param1=wave, Param2=0/all fields selector, Param3=sampling,
    Param4=frequency, Param5=0, Param6=normalized field height.
    """
    _write_operand_param(row, 1, wave_idx)
    _write_operand_param(row, 2, 0)
    _write_operand_param(row, 3, sampling)
    _write_operand_param(row, 4, float(frequency))
    _write_operand_param(row, 5, 0.0)
    _write_operand_param(row, 6, float(normalized_field))


def _normalized_field_heights(sys_data, conn) -> dict[int, float]:
    """Return normalized field heights keyed by 1-based field index."""
    heights = {}
    try:
        n = sys_data.Fields.NumberOfFields
    except Exception:
        return heights
    raw = {}
    max_abs = 0.0
    for fi in range(1, n + 1):
        try:
            field = sys_data.Fields.GetField(fi)
            _, fy, _ = conn.get_field_data(field)
            value = abs(float(fy))
        except Exception:
            value = float(fi - 1)
        raw[fi] = value
        if value > max_abs:
            max_abs = value
    if max_abs <= 0:
        denom = max(1, n - 1)
        return {fi: (fi - 1) / denom for fi in range(1, n + 1)}
    return {fi: raw[fi] / max_abs for fi in range(1, n + 1)}


def _mtf_result_warnings(fields_data: list[dict]) -> list[str]:
    """Generate sanity warnings for MTF results."""
    values = []
    for field in fields_data:
        for key in ("mtf_tangential", "mtf_sagittal", "T", "S"):
            value = field.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value):
                values.append(float(value))
    if not values:
        return ["未获得有效 MTF 数值；应检查操作数参数、采样和视场通光状态。"]
    warnings = []
    if all(abs(value) <= 1e-9 for value in values):
        warnings.append("所有 MTF 值均为 0；优先检查该频率是否超过截止频率、视场是否 0 光强，以及 MTFS/MTFT 参数是否正确。")
    if any(value < -1e-6 or value > 1.000001 for value in values):
        warnings.append("出现超出 [0, 1] 的 MTF 值；需与 Zemax 图窗或 MFE 行交叉验证。")
    field_values = []
    for field in fields_data:
        field_id = field.get("field")
        field_norm = field.get("normalized_field")
        t_value = field.get("mtf_tangential", field.get("T"))
        s_value = field.get("mtf_sagittal", field.get("S"))
        if isinstance(field_id, int) and isinstance(field_norm, (int, float)):
            field_values.append((field_id, float(field_norm), t_value, s_value))
    if len(field_values) >= 2 and any(abs(item[1]) > 1e-9 for item in field_values):
        t_numbers = [item[2] for item in field_values if isinstance(item[2], (int, float)) and math.isfinite(item[2])]
        s_numbers = [item[3] for item in field_values if isinstance(item[3], (int, float)) and math.isfinite(item[3])]
        t_flat = len(t_numbers) == len(field_values) and max(t_numbers) - min(t_numbers) <= 1e-9
        s_flat = len(s_numbers) == len(field_values) and max(s_numbers) - min(s_numbers) <= 1e-9
        if t_flat and s_flat:
            warnings.append("所有视场的 MTFT/MTFS 数值完全相同；疑似场参数未生效或工具参数映射仍需与 Zemax 图窗/MFE 交叉验证。")
    return warnings


def _operand_cells_dict(row):
    """读取 MFE 行的 Param1..8，并按 Zemax 常见列名返回。"""
    cells = {}
    for param_num in range(1, 9):
        col_idx = param_num + 1
        name = _OPERAND_PARAM_NAMES.get(param_num, f"param{param_num}")
        try:
            cell = row.GetOperandCell(col_idx)
        except Exception:
            continue
        if cell is None:
            continue

        value = None
        for attr in ("IntegerValue", "DoubleValue", "Value"):
            try:
                candidate = getattr(cell, attr)
                candidate = _jsonable_number(candidate)
                if candidate not in (None, ""):
                    value = candidate
                    break
            except Exception:
                continue
        if value is not None:
            cells[name] = value
            cells[f"param{param_num}"] = value
    return cells


def _read_mfe_row_cell_value(row, cell_method_name: str):
    """读取 MFE 行的指定单元格值，如 ContributionCell/ValueCell。"""
    try:
        cell_method = getattr(row, cell_method_name)
        cell = cell_method()
    except Exception:
        return None
    if cell is None:
        return None
    for attr in ("DoubleValue", "IntegerValue", "Value"):
        try:
            value = getattr(cell, attr)
            value = _jsonable_number(value)
            if value not in (None, ""):
                return value
        except Exception:
            continue
    return None


def _weighted_error_estimate(target, weight, value):
    """在无法读取真实 Contribution 时估算加权误差。"""
    try:
        if all(isinstance(x, (int, float)) and math.isfinite(x) for x in (target, weight, value)):
            return abs(float(weight) * (float(value) - float(target)))
    except Exception:
        pass
    return None


def _probe_ray_aiming_properties(system_data):
    """探测当前 ZOS-API 版本可能暴露的 Ray Aiming 属性。"""
    targets = [("SystemData", system_data)]
    try:
        targets.append(("SystemData.Aperture", system_data.Aperture))
    except Exception:
        pass
    try:
        targets.append(("SystemData.RayAiming", system_data.RayAiming))
    except Exception:
        pass

    candidate_props = [
        "RayAiming", "UseRayAiming", "RayAimingEnabled", "EnableRayAiming",
        "RayAimingType", "RayAimingMode", "RayAimingMethod",
        "RayAimingCache", "UseRayAimingCache", "RayAimingCacheEnabled",
        "PupilShift", "PupilAberrationCorrection",
    ]
    probes = []
    for target_name, target in targets:
        prop_map = getattr(target, "_prop_map_get_", {}) or {}
        put_map = getattr(target.__class__, "_prop_map_put_", {}) or {}
        known_props = sorted(set(candidate_props) | set(prop_map.keys()) | set(put_map.keys()))
        for prop in known_props:
            if "aim" not in prop.lower() and prop not in candidate_props:
                continue
            item = {"target": target_name, "property": prop, "readable": False, "writable": prop in put_map}
            try:
                item["value"] = _jsonable_number(getattr(target, prop))
                item["readable"] = True
            except Exception as e:
                item["read_error"] = str(e)[:120]
            probes.append(item)
    return probes


def _set_ray_aiming_properties(system_data, enabled: bool, mode: str, use_cache: bool):
    """多策略设置 Ray Aiming；不支持时返回明确错误。"""
    mode_map = {"off": 0, "paraxial": 1, "real": 2}
    mode_value = mode_map.get(str(mode).lower(), 1)
    probes_before = _probe_ray_aiming_properties(system_data)
    attempts = []

    targets = [("SystemData", system_data)]
    try:
        targets.append(("SystemData.Aperture", system_data.Aperture))
    except Exception:
        pass
    try:
        targets.append(("SystemData.RayAiming", system_data.RayAiming))
    except Exception:
        pass

    enabled_props = ["UseRayAiming", "RayAimingEnabled", "EnableRayAiming"]
    mode_props = ["RayAiming", "RayAimingType", "RayAimingMode", "RayAimingMethod"]
    cache_props = ["RayAimingCache", "UseRayAimingCache", "RayAimingCacheEnabled"]

    wrote_any = False
    for target_name, target in targets:
        for prop in enabled_props:
            ok, err = _try_set_and_verify(target, prop, bool(enabled))
            attempts.append({"target": target_name, "property": prop, "value": bool(enabled), "ok": ok, "error": err})
            wrote_any = wrote_any or ok
        for prop in mode_props:
            value = 0 if not enabled else mode_value
            ok, err = _try_set_and_verify(target, prop, value)
            attempts.append({"target": target_name, "property": prop, "value": value, "ok": ok, "error": err})
            wrote_any = wrote_any or ok
        for prop in cache_props:
            ok, err = _try_set_and_verify(target, prop, bool(use_cache))
            attempts.append({"target": target_name, "property": prop, "value": bool(use_cache), "ok": ok, "error": err})
            wrote_any = wrote_any or ok

    result = {
        "ok": wrote_any,
        "enabled_requested": enabled,
        "mode_requested": mode,
        "attempts": attempts,
        "before": probes_before,
        "after": _probe_ray_aiming_properties(system_data),
    }
    if not wrote_any:
        result["error"] = "当前 ZOS-API COM 包装未暴露可写 Ray Aiming 属性。请在 OpticStudio UI 中手动开启：System Explorer → Ray Aiming → Paraxial/Real。"
    return result


def _try_set_and_verify(target, prop: str, value):
    """尝试设置 COM 属性并读回验证。"""
    try:
        setattr(target, prop, value)
    except Exception as e:
        return False, str(e)[:120]
    try:
        read_back = getattr(target, prop)
        if isinstance(value, bool):
            return bool(read_back) == value, None
        if isinstance(read_back, (int, float)):
            return int(read_back) == int(value), None
        return True, None
    except Exception:
        return True, None


# 只读工具集 — 不触发自动 UI 刷新
_READ_ONLY_TOOLS: frozenset[str] = frozenset({
    "get_system_info",
    "get_project_context",
    "list_backups",
    "get_merit_function",
    "get_operands",
    "get_merit_breakdown",
    "get_ray_aiming_settings",
    "get_first_order_data",
    "get_image_quality",
    "get_aberrations",
    "get_distortion",
    "check_field_illumination",
    "get_mtf",
    "get_mtf_curve",
    "export_analysis_data",
    "get_relative_illumination_data",
    "get_vignetting_diagram_data",
    "get_spot_diagram_data",
    "get_fft_mtf_vs_field",
    "get_ray_fan_data",
    "get_opd_fan_data",
    "get_longitudinal_aberration_data",
    "get_lateral_color_data",
    "get_field_curvature_distortion_data",
    "get_wavefront_map_data",
    "generate_validation_report",
    "check_manufacturability",
    "get_glass_catalogs",
    "update_ui",      # 本身就是刷新工具，无需再次触发
    "open_layout",    # 打开窗口后自身已做 ApplyAndWaitForCompletion
})


# 高风险工具集 — 执行前自动备份当前 .zmx，返回 backup_path 供 Agent 自主恢复
_HIGH_RISK_TOOLS: frozenset[str] = frozenset({
    "run_optimization",
    "new_file",
    "open_file",
    "edit_operand",
    "build_operand_block",
    "set_default_merit_function",
    "set_default_merit_function_after_current_block",
    "remove_surface",
    "remove_operands",
    "clear_operands",
})


def _is_com_disconnect_error(err_str: str) -> bool:
    """判断异常是否属于 COM 连接断开类错误.

    注意: NoneType 属性错误不是连接断开, 而是 COM 方法返回了 None (如工具无法打开).
    """
    err_lower = err_str.lower()
    # 排除 NoneType 错误 — 这不是连接断开
    if "'nonetype'" in err_lower:
        return False
    # 真正的 COM 断连指标
    indicators = [
        "rpc", "disconnected", "call was rejected",
        "server threw an exception", "com_error",
        "0x800706ba",   # RPC server unavailable
        "0x80010108",   # Object invoked has disconnected
        "0x800706be",   # Remote procedure call failed
        "0x80010105",   # Server threw an exception
        "0x800401fd",   # ServerNotAvailable
    ]
    return any(ind in err_lower for ind in indicators)


def _resolve_operand_type(operand_name):
    """将操作数类型名 (如 'EFFL') 解析为 COM 枚举整数值.

    ZOS-API COM 常量注册在 win32com.client.constants 中,
    命名可能为 EFFL / MeritOperandType_EFFL 等。
    """
    from win32com.client import constants

    name = operand_name.upper().strip()

    # 策略 1: 直接常量访问
    for pattern in [name, f"MeritOperandType_{name}"]:
        try:
            return getattr(constants, pattern)
        except AttributeError:
            continue

    # 策略 2: 搜索常量字典
    try:
        const_dicts = getattr(constants, "__dicts__", None)
        if const_dicts:
            for d in const_dicts:
                for key, val in d.items():
                    key_upper = key.upper()
                    if key_upper == name or key_upper.endswith(f"_{name}"):
                        return val
    except Exception:
        pass

    return None


def _set_row_operand_type(row, type_val):
    """在 MFE 行上设置操作数类型 (多策略).

    ZOS-API 不同版本的接口存在差异:
    - 新版: row.GetOperandTypeSettings(enum) → settings → row.ChangeType(settings)
    - 旧版: row.ChangeType(enum) 或 row.Type = enum
    """
    # 策略 1: GetOperandTypeSettings + ChangeType
    try:
        settings = row.GetOperandTypeSettings(type_val)
        row.ChangeType(settings)
        return True
    except Exception:
        pass
    # 策略 2: 直接 ChangeType(enum)
    try:
        row.ChangeType(type_val)
        return True
    except Exception:
        pass
    # 策略 3: 设置 Type 属性
    if _safe_set_attr(row, "Type", type_val):
        return True
    return False


def _set_operand_int_param(row, param_num, value):
    """设置 MFE 行的整数参数 (Param1/Param2/...).

    IMFERow (早期绑定) 的 _prop_map_put_ 里没有 Param1/Param2,
    直接 setattr 只会添加 Python 实例属性而不触发 COM 调用 (静默假成功)。
    必须用 GetOperandCell(col).IntegerValue 作为首选路径。
    MeritColumn 枚举: Param1=col2, Param2=col3, Param3=col4, ...
    """
    col_idx = param_num + 1  # Param1→col2, Param2→col3, ...
    # 策略 1: GetOperandCell (IMFERow 的正确路径)
    try:
        cell = row.GetOperandCell(col_idx)
        if cell is not None:
            # 先读回确认写入有效
            cell.IntegerValue = int(value)
            return True
    except Exception:
        pass
    # 策略 2: 直接属性 Param1, Param2, ... (IMCERow 等其他接口)
    attr = f"Param{param_num}"
    try:
        # 只对有 _prop_map_put_ 记录的真实 COM 属性才写入
        prop_map = getattr(row.__class__, "_prop_map_put_", {})
        if attr in prop_map:
            setattr(row, attr, int(value))
            return True
    except Exception:
        pass
    # 策略 3: GetCellAt
    try:
        cell = row.GetCellAt(col_idx)
        if cell is not None:
            try:
                cell.IntegerValue = int(value)
            except AttributeError:
                cell.Value = str(value)
            return True
    except Exception:
        pass
    return False


def _set_operand_double_param(row, param_num, value):
    """设置 MFE 行的浮点参数 (Hx/Hy/Px/Py/frequency 等).

    MeritColumn 枚举: Param1=col2, Param2=col3, Param3(Hx)=col4, Param4(Hy)=col5, ...
    使用 GetOperandCell(col).DoubleValue 写入。
    """
    col_idx = param_num + 1
    # 策略 1: GetOperandCell.DoubleValue (首选)
    try:
        cell = row.GetOperandCell(col_idx)
        if cell is not None:
            cell.DoubleValue = float(value)
            return True
    except Exception as e:
        # 如果 DoubleValue 抛出 "Expected Double, got Integer" 等, 尝试字符串路径
        try:
            cell = row.GetOperandCell(col_idx)
            if cell is not None:
                cell.Value = str(float(value))
                return True
        except Exception:
            pass
    # 策略 2: GetCellAt.DoubleValue
    try:
        cell = row.GetCellAt(col_idx)
        if cell is not None:
            cell.DoubleValue = float(value)
            return True
    except Exception:
        pass
    return False
