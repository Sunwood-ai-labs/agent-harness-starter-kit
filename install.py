#!/usr/bin/env python3
"""Install the starter kit into a project folder.

    python3 install.py --project ~/work/my-project --tool claude
    python3 install.py --project ~/work/my-project --tool all
    python3 install.py --project ~/work/my-project --tool codex --dry-run

What it does:
  1. Copies guard/ to <project>/.agent-guard/ (the shared safety check).
  2. Writes the chosen tools' settings into the project, with the absolute
     paths of this Python and of .agent-guard/ filled in.
  3. Never overwrites an existing file unless --force is given; with --force
     the old file is kept as <name>.bak-<time>.

It changes nothing outside the project folder. Global settings (~/.claude,
~/.codex, ~/.gemini, ~/.config/opencode) are left alone.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import shutil
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

KIT = os.path.dirname(os.path.abspath(__file__))
TOOLS = {
    "claude": ("claude-code/template", [".claude/settings.json"]),
    "codex": ("codex/template", [".codex/config.toml", ".codex/hooks.json"]),
    "antigravity": ("antigravity/template", [".agents/hooks.json"]),
    "opencode": ("opencode/template", ["opencode.json", ".opencode/plugins/agent-guard.js"]),
}
GUARD_FILES = ["agent_guard.py", "trash.py", "checkpoint.py", "policy.json"]


def quote(path: str) -> str:
    if os.name == "nt":
        return f'"{path}"'
    return shlex.quote(path)


def render(text: str, project: str, python: str) -> str:
    guard_dir = os.path.join(project, ".agent-guard")
    guard = os.path.join(guard_dir, "agent_guard.py")
    checkpoint = os.path.join(guard_dir, "checkpoint.py")
    values = {
        "{{GUARD}}": f"{quote(python)} {quote(guard)}",
        "{{CHECKPOINT}}": f"{quote(python)} {quote(checkpoint)}",
        "{{PYTHON_NAME}}": "python" if os.name == "nt" else "python3",
        "{{PYTHON_JSON}}": json.dumps(python),
        "{{GUARD_PATH_JSON}}": json.dumps(guard),
    }
    return text, values


def fill(text: str, values: dict[str, str], is_json: bool) -> str:
    if not is_json:
        for k, v in values.items():
            text = text.replace(k, v)
        return text
    data = json.loads(text)

    def walk(node):
        if isinstance(node, str):
            for k, v in values.items():
                node = node.replace(k, v)
            return node
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            return {walk(k): walk(v) for k, v in node.items()}
        return node

    return json.dumps(walk(data), ensure_ascii=False, indent=2) + "\n"


def write(path: str, content: str | bytes, force: bool, dry: bool, actions: list[str]) -> bool:
    if os.path.exists(path):
        with open(path, "rb") as fh:
            old = fh.read()
        new = content.encode("utf-8") if isinstance(content, str) else content
        if old == new:
            actions.append(f"変更なし      {path}")
            return True
        if not force:
            actions.append(f"スキップ      {path}（既にあります。--force で上書きし、元は .bak に残します）")
            return False
        backup = f"{path}.bak-{dt.datetime.now():%Y%m%d-%H%M%S}"
        if not dry:
            shutil.copy2(path, backup)
        actions.append(f"バックアップ  {backup}")
    if not dry:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(path, mode, **({} if mode == "wb" else {"encoding": "utf-8", "newline": "\n"})) as fh:
            fh.write(content)
    actions.append(f"書き込み      {path}")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Install agent-harness-starter-kit into a project")
    ap.add_argument("--project", required=True, help="作業フォルダ（AIに作業させるフォルダ）")
    ap.add_argument("--tool", required=True, choices=[*TOOLS, "all"], action="append")
    ap.add_argument("--python", default=sys.executable, help="Hookから呼ぶPython（既定：今のPython）")
    ap.add_argument("--force", action="store_true", help="既存の設定を .bak に残して上書きする")
    ap.add_argument("--dry-run", action="store_true", help="何をするか表示するだけ")
    ns = ap.parse_args(argv)

    project = os.path.abspath(os.path.expanduser(ns.project))
    if not os.path.isdir(project):
        print(f"フォルダが見つかりません: {project}", file=sys.stderr)
        return 1
    if os.path.abspath(os.path.expanduser("~")) == project or os.path.dirname(project) == project:
        print("ホームフォルダやドライブ全体には入れられません。作業用のフォルダを指定してください。", file=sys.stderr)
        return 1
    tools = list(TOOLS) if "all" in ns.tool else list(dict.fromkeys(ns.tool))
    python = os.path.abspath(ns.python)
    actions: list[str] = []
    ok = True

    for name in GUARD_FILES:
        with open(os.path.join(KIT, "guard", name), "rb") as fh:
            ok &= write(os.path.join(project, ".agent-guard", name), fh.read(), ns.force or name != "policy.json", ns.dry_run, actions)

    for tool in tools:
        src_dir, files = TOOLS[tool]
        for rel in files:
            with open(os.path.join(KIT, src_dir, rel), encoding="utf-8") as fh:
                text = fh.read()
            _, values = render(text, project, python)
            out = fill(text, values, rel.endswith(".json"))
            ok &= write(os.path.join(project, rel), out, ns.force, ns.dry_run, actions)

    gi = os.path.join(project, ".gitignore")
    lines = [".agent-guard/logs/", ".agent-trash/"]
    existing = open(gi, encoding="utf-8").read().splitlines() if os.path.exists(gi) else []
    missing = [line for line in lines if line not in existing]
    if missing:
        if not ns.dry_run:
            with open(gi, "a", encoding="utf-8", newline="\n") as fh:
                if existing and existing[-1] != "":
                    fh.write("\n")
                fh.write("# agent-harness-starter-kit\n" + "\n".join(missing) + "\n")
        actions.append(f"追記          {gi}")

    print("\n".join(actions))
    print()
    if ns.dry_run:
        print("（--dry-run なので、まだ何も書き込んでいません）")
    print("次にすること：")
    if "claude" in tools:
        print("  Claude Code : このフォルダで claude を起動し、/hooks と /permissions で設定が読まれたか確認")
    if "codex" in tools:
        print("  Codex       : このフォルダで codex を起動し、プロジェクトを信頼（trust）してから /hooks でHookを確認・信頼する")
    if "antigravity" in tools:
        print("  Antigravity : /hooks（CLI）または Settings > Customizations > Hooks で agent-guard が読まれたか確認")
    if "opencode" in tools:
        print("  OpenCode    : opencode debug config で permission が反映されたか確認")
    print("  共通        : 原本は作業フォルダに置かず、読み取り専用の場所から必要な分だけコピーする（README 参照）")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
