#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
skill 结构自检：校验 zemax-ADAS-skill 的跨文件引用完整性。

用途：重构 / 增删章节后跑一次，确认没有断链。
用法：python scripts/lint_skill.py
退出码：0 = 全部通过；1 = 有问题（详见输出）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent / ".github" / "skills" / "zemax-ADAS-skill"
SKILL = SKILL_DIR / "SKILL.md"
REFS = SKILL_DIR / "references"

# 主文件允许的最大行数（超过会拖慢 agent 读取）
SKILL_MAX_LINES = 300

# 引用形如：§P1 / §P6.3 / §T11 / §C4.8 / §3.1（主文件内部章节）
RE_REF = re.compile(r"§(P\d+(?:\.\d+)?|T\d+(?:\.\d+)?|C\d+(?:\.\d+)?|[A-H]|\d+(?:\.\d+)?)")
# 定义形如：## P1.xxx / ### P6.3 xxx / ## T15. xxx / ## C4. xxx / ### 3.1 xxx
RE_DEF = re.compile(r"^#{2,3}\s+(P\d+(?:\.\d+)?|T\d+(?:\.\d+)?|C\d+(?:\.\d+)?|[A-H]|\d+(?:\.\d+)?)[\.\s]")


def defined_anchors(path: Path) -> set[str]:
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = RE_DEF.match(line)
        if m:
            out.add(m.group(1))
    return out


def referenced_anchors(text: str) -> set[str]:
    """收集文中所有 § 引用。纯数字（§3.2 等）指向 SKILL.md，P/T/C/字母指向各自专篇。"""
    refs: set[str] = set()
    for line in text.splitlines():
        for m in RE_REF.finditer(line):
            refs.add(m.group(1))
    return refs


def main() -> int:
    errors: list[str] = []
    warns: list[str] = []

    if not SKILL.exists():
        print(f"[FATAL] 找不到 {SKILL}")
        return 1

    files = [SKILL] + sorted(REFS.glob("*.md"))
    anchors: dict[str, set[str]] = {p.name: defined_anchors(p) for p in files}
    all_anchors: set[str] = set().union(*anchors.values())

    # 1. 主文件行数
    n = len(SKILL.read_text(encoding="utf-8").splitlines())
    if n > SKILL_MAX_LINES:
        errors.append(f"SKILL.md 有 {n} 行，超过上限 {SKILL_MAX_LINES}")
    else:
        print(f"[OK] SKILL.md {n} 行 (<= {SKILL_MAX_LINES})")

    # 2. 路由表里点名的文件必须存在
    routing = SKILL.read_text(encoding="utf-8")
    for m in re.finditer(r"`references/([a-z0-9\-]+\.md)`", routing):
        if not (REFS / m.group(1)).exists():
            errors.append(f"路由表指向不存在的文件: references/{m.group(1)}")

    # 3. 跨文件 § 引用必须能在全体文件中找到定义
    for p in files:
        text = p.read_text(encoding="utf-8")
        for tag in sorted(referenced_anchors(text)):
            scope = anchors["SKILL.md"] if tag[0].isdigit() else all_anchors
            if tag not in scope:
                errors.append(f"{p.name}: 引用了不存在的章节 §{tag}")

    # 4. 每个 reference 至少被主文件路由表或正文提到一次（防止孤儿文件）
    for p in sorted(REFS.glob("*.md")):
        if p.name not in routing:
            warns.append(f"references/{p.name} 未被 SKILL.md 引用（孤儿文件）")

    # 5. 各文件自身章节号连续性（仅 P/T/C + 数字前缀，字母类不参与）
    for p in files:
        tags = sorted(
            (a for a in anchors[p.name] if a[0] in "PTC" and "." not in a and a[1:].isdigit()),
            key=lambda s: int(s[1:]),
        )
        nums = [int(t[1:]) for t in tags]
        if nums and nums != list(range(nums[0], nums[0] + len(nums))):
            errors.append(f"{p.name}: 章节编号不连续 {tags}")

    for w in warns:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[FAIL] {e}")

    if errors:
        print(f"\n{len(errors)} 个问题待修")
        return 1
    print(f"\n全部通过：{len(files)} 个文件，{len(all_anchors)} 个锚点")
    return 0


if __name__ == "__main__":
    sys.exit(main())
