"""从 MCP 点列图工具的落盘结果里提取 RMS/GEO 摘要，避免把 250KB 的完整 JSON 塞进上下文。

用法: python scripts/spot_summary.py            # 取最新的 get_spot_diagram_data 结果
      python scripts/spot_summary.py <file>     # 指定文件
"""
import json
import sys
from pathlib import Path

RESULTS_DIR = Path(
    r"C:\Users\15803\.workbuddy\projects\d-Zemax-mcp"
    r"\5c19ce71-07b2-4359-bf74-d16bfa1c9136\tool-results"
)


def pick_file() -> Path:
    if len(sys.argv) > 1 and sys.argv[1] not in ("", "-", "auto"):
        return Path(sys.argv[1])
    files = sorted(
        RESULTS_DIR.glob("mcp-zemax-opticstudio-get_spot_diagram_data-*.txt"),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        raise SystemExit("找不到点列图结果文件")
    return files[-1]


def airy_radius_um(fno: float, lam_um: float = 0.588) -> float:
    # Zemax 定义：r = 1.22·λ·F#（F# = EFFL/EPD，像方 F 数）
    return 0.61 * lam_um * 2.0 * fno


def main() -> None:
    path = pick_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    # 优先用工具算好的权威值（1.22·λ·F#，F#=EFFL/EPD，逐系统精确）；
    # 命令行给的 F 数只作兜底，避免两处口径不一致。
    airy = data.get("airy_radius_um")
    fno = float(sys.argv[2]) if len(sys.argv) > 2 else None
    src = "工具 airy_radius_um"
    if not airy:
        if not fno:
            raise SystemExit("结果里没有 airy_radius_um，请显式传入 F 数")
        airy = airy_radius_um(fno)
        src = f"命令行 F/{fno}"

    print(f"文件: {path.name}")
    print(f"{'视场(°)':>8} {'RMS(µm)':>9} {'GEO(µm)':>9} {'RMS/艾里':>9}")
    for f in data.get("fields", []):
        rms = f["rms_radius_lens_units"]
        geo = f["geo_radius_lens_units"]
        print(f"{f['field_y']:>8.1f} {rms:>9.2f} {geo:>9.2f} {rms / airy:>9.2f}")
    print(f"艾里半径 = {airy:.4f} µm（{src}）")


if __name__ == "__main__":
    main()
