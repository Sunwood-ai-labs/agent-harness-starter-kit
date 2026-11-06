#!/usr/bin/env python3
"""Copy the workspace to a backup folder before the agent starts (layer 3).

    python3 .agent-guard/checkpoint.py            # make a backup now
    python3 .agent-guard/checkpoint.py --list     # show backups
    python3 .agent-guard/checkpoint.py --restore <name> <file-or-folder>

Backups go to ~/.agent-guard-backups/<project>/<time>/ (outside the workspace,
so the agent's sandbox cannot touch them). Set "backup_dir" in policy.json to
use another place, such as a NAS the agent cannot write to.

Large or rebuildable folders are skipped (see "backup_exclude"). The newest
"backup_keep" backups are kept. A run that finds no change since the last
backup only updates its timestamp file.

Hooks call this at session start. It never blocks the agent: errors are
printed and the exit code is 0.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
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

DEFAULT_EXCLUDE = [".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", "build", "dist", ".agent-trash", ".agent-guard/logs", "tmp"]


def settings() -> tuple[str, str, list[str], int, int]:
    policy = g.load_policy()
    root = g.workspace_root(policy, {"cwd": os.getcwd()})
    name = os.path.basename(root.rstrip("/\\")) or "workspace"
    base = os.path.expanduser(policy.get("backup_dir") or "~/.agent-guard-backups")
    exclude = policy.get("backup_exclude") or DEFAULT_EXCLUDE
    keep = int(policy.get("backup_keep") or 10)
    max_mb = int(policy.get("backup_max_mb") or 500)
    return root, os.path.join(base, name), exclude, keep, max_mb


def walk(root: str, exclude: list[str]):
    for dirpath, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, p) or fnmatch.fnmatch(f"{rel_dir}/{d}".lstrip("./"), p) for p in exclude)]
        for f in files:
            yield os.path.join(dirpath, f)


def fingerprint(paths: list[str]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        try:
            st = os.stat(p)
        except OSError:
            continue
        h.update(f"{p}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8", "replace"))
    return h.hexdigest()


def make() -> int:
    root, dest_base, exclude, keep, max_mb = settings()
    files = list(walk(root, exclude))
    total = sum(os.path.getsize(f) for f in files if os.path.isfile(f))
    if total > max_mb * 1024 * 1024:
        print(f"[agent-guard] バックアップを省略しました：{total // (1024 * 1024)}MB が上限 {max_mb}MB を超えています（policy.json の backup_max_mb）")
        return 0
    fp = fingerprint(files)
    os.makedirs(dest_base, exist_ok=True)
    marker = os.path.join(dest_base, "latest.json")
    if os.path.isfile(marker):
        with open(marker, encoding="utf-8") as fh:
            last = json.load(fh)
        if last.get("fingerprint") == fp:
            print(f"[agent-guard] 前回のバックアップから変更はありません（{last.get('name')}）")
            return 0
    name = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(dest_base, name)
    for src in files:
        rel = os.path.relpath(src, root)
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            shutil.copy2(src, target)
        except OSError as exc:
            print(f"[agent-guard] コピーできませんでした: {rel} ({exc})")
    with open(marker, "w", encoding="utf-8") as fh:
        json.dump({"name": name, "fingerprint": fp, "files": len(files)}, fh)
    snaps = sorted(d for d in os.listdir(dest_base) if os.path.isdir(os.path.join(dest_base, d)))
    for old in snaps[:-keep]:
        shutil.rmtree(os.path.join(dest_base, old), ignore_errors=True)
    print(f"[agent-guard] 作業前バックアップを作りました：{dest}（{len(files)} ファイル）")
    return 0


def main(argv: list[str]) -> int:
    root, dest_base, *_ = settings()
    if argv[:1] == ["--list"]:
        if os.path.isdir(dest_base):
            for d in sorted(os.listdir(dest_base)):
                if os.path.isdir(os.path.join(dest_base, d)):
                    print(d)
        return 0
    if argv[:1] == ["--restore"]:
        if len(argv) != 3:
            print("使い方: checkpoint.py --restore <バックアップ名> <戻したいファイルかフォルダ>", file=sys.stderr)
            return 2
        src = os.path.join(dest_base, argv[1], argv[2])
        dst = os.path.join(root, argv[2])
        if not os.path.exists(src):
            print(f"バックアップの中に見つかりません: {src}", file=sys.stderr)
            return 1
        if os.path.exists(dst):
            aside = dst + ".before-restore-" + dt.datetime.now().strftime("%H%M%S")
            shutil.move(dst, aside)
            print(f"今のファイルは {aside} に残しました")
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        print(f"戻しました: {argv[2]}")
        return 0
    try:
        return make()
    except Exception as exc:  # never block the session
        print(f"[agent-guard] バックアップに失敗しました：{exc}")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
