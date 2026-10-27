#!/usr/bin/env python3
"""把项目内的 Zemax 技能从 .github/skills 同步到 .dsh/skills。

真源：  .github/skills/<name>/       入库技能源，Copilot 与队友读取
发布：  .dsh/skills/<name>/          DSH 项目级技能副本（rank 100）

用法：
    python scripts/sync_skills.py           # 应用同步
    python scripts/sync_skills.py --check   # 只检查漂移，有差异时退出码 1

注意：
  - 仅同步本项目的 Zemax 技能；lab-book-skill 与 neat-freak 不参与发布。
  - 同步是“镜像”语义：目标目录里源端没有的文件会被删除。
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".github" / "skills"

# 本项目的 Zemax 技能进入 DSH 项目级目录；其他技能不参与同步。
DSH_TARGETS = (
    "system-setup-by-type",
    "zemax-ADAS-skill",
    "zemax-optical-design",
    "zemax-zoom-lens-design",
)

TARGETS = ((ROOT / ".dsh" / "skills", DSH_TARGETS),)


def iter_files(base: Path) -> dict[str, Path]:
    """返回 {相对路径: 绝对路径}，跳过嵌套 .git。"""
    files: dict[str, Path] = {}
    for p in sorted(base.rglob("*")):
        if ".git" in p.relative_to(base).parts:
            continue
        if p.is_file():
            files[p.relative_to(base).as_posix()] = p
    return files


def plan(src: Path, dst: Path) -> tuple[list[str], list[str], list[str]]:
    """返回 (新增, 更新, 删除) 的相对路径列表。"""
    s, d = iter_files(src), (iter_files(dst) if dst.is_dir() else {})
    add = [k for k in s if k not in d]
    update = [k for k in s if k in d and not filecmp.cmp(s[k], d[k], shallow=False)]
    remove = [k for k in d if k not in s]
    return sorted(add), sorted(update), sorted(remove)


def apply(src: Path, dst: Path, add: list[str], update: list[str], remove: list[str]) -> None:
    for rel in remove:
        target = dst / rel
        if target.is_file():
            target.unlink()
    for rel in add + update:
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)
    # 清理镜像后留下的空目录
    for p in sorted(dst.rglob("*"), reverse=True):
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()


def main() -> int:
    ap = argparse.ArgumentParser(description="同步 .github/skills 中的 Zemax 技能到 .dsh/skills")
    ap.add_argument("--check", action="store_true", help="只检查漂移，不写文件")
    args = ap.parse_args()

    if not SRC.is_dir():
        print(f"[错误] 找不到项目技能目录：{SRC}", file=sys.stderr)
        return 2

    drift = 0
    for base, names in TARGETS:
        print(f"==> {base.relative_to(ROOT).as_posix()}")
        for name in names:
            src = SRC / name
            if not src.is_dir():
                print(f"  [错误] 项目技能缺少 {name}：{src}", file=sys.stderr)
                return 2
            dst = base / name
            add, update, remove = plan(src, dst)
            if not (add or update or remove):
                print(f"  = {name}")
                continue
            drift += len(add) + len(update) + len(remove)
            print(f"  * {name}: +{len(add)} ~{len(update)} -{len(remove)}")
            for rel in add:
                print(f"      + {rel}")
            for rel in update:
                print(f"      ~ {rel}")
            for rel in remove:
                print(f"      - {rel}")
            if not args.check:
                apply(src, dst, add, update, remove)

    if args.check:
        if drift:
            print(f"\n发现 {drift} 处漂移；运行 python scripts/sync_skills.py 修复。")
            return 1
        print("\n全部一致。")
    else:
        print(f"\n完成，处理 {drift} 处变更。" if drift else "\n无需变更。")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    raise SystemExit(main())
