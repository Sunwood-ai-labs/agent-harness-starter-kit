#!/usr/bin/env python3
"""Move files into .agent-trash/<time>/ instead of deleting them.

    python3 .agent-guard/trash.py old-folder notes.txt
    python3 .agent-guard/trash.py --list
    python3 .agent-guard/trash.py --restore 20261106-181500

Only paths inside the workspace are accepted, and protected paths are refused.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_guard as g  # noqa: E402


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass


def main(argv: list[str]) -> int:
    policy = g.load_policy()
    root = g.workspace_root(policy, {"cwd": os.getcwd()})
    trash = os.path.join(root, ".agent-trash")
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    if argv[0] == "--list":
        if os.path.isdir(trash):
            for name in sorted(os.listdir(trash)):
                print(name)
        return 0
    if argv[0] == "--restore":
        if len(argv) != 2:
            print("使い方: trash.py --restore <フォルダ名>", file=sys.stderr)
            return 2
        src_root = os.path.join(trash, argv[1])
        moved = 0
        for dirpath, _dirs, files in os.walk(src_root):
            for f in files:
                src = os.path.join(dirpath, f)
                rel = os.path.relpath(src, src_root)
                dst = os.path.join(root, rel)
                if os.path.exists(dst):
                    print(f"そのままにしました（同じ名前のファイルがあります）: {rel}")
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                moved += 1
        print(f"{moved} 個のファイルを元の場所に戻しました")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_root = os.path.join(trash, stamp)
    status = 0
    for raw in argv:
        w = g.locate(raw, root, os.getcwd())
        if w.outside or w.rel in (None, ".", ""):
            print(f"移せません（作業フォルダの外です）: {raw}", file=sys.stderr)
            status = 1
            continue
        if g.matches(w.rel, policy["protected_paths"]) or w.rel.startswith(".agent-trash"):
            print(f"移せません（保護されています）: {raw}", file=sys.stderr)
            status = 1
            continue
        src = os.path.join(root, w.rel)
        if not os.path.exists(src):
            print(f"見つかりません: {raw}", file=sys.stderr)
            status = 1
            continue
        dst = os.path.join(dest_root, w.rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        print(f"退避しました: {w.rel} → .agent-trash/{stamp}/{w.rel}")
    if status == 0:
        print(f"戻すとき: python3 .agent-guard/trash.py --restore {stamp}")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
