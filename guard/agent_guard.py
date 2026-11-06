#!/usr/bin/env python3
"""agent-guard: a pre-execution safety check shared by four coding-agent harnesses.

It reads one hook event (JSON) on stdin, decides whether the requested tool call
is safe, and prints the answer in the format each harness expects.

    python3 agent_guard.py --tool claude       # Claude Code  PreToolUse
    python3 agent_guard.py --tool codex        # Codex        PreToolUse
    python3 agent_guard.py --tool antigravity  # Antigravity  PreToolUse
    python3 agent_guard.py --tool opencode     # OpenCode     plugin (tool.execute.before)
    python3 agent_guard.py --tool generic      # {"decision": ..., "reason": ...}

Decisions:
    allow    the call is fine; the harness's own permission rules still apply
    confirm  a person should decide (Claude: ask, Antigravity: force_ask,
             Codex: deny with instructions, OpenCode: ask in the plugin)
    block    never run it automatically

This script is the second layer of three. It only sees command text, so it can
miss deletions done another way (a Python script, a build tool, ...). File
permissions, a sandbox and backups are what actually keep data safe.

Standard library only. Works on Linux, macOS and Windows.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable

VERSION = "1.0.0"

GUARD_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_POLICY: dict[str, Any] = {
    # Area C. Never written or deleted by the agent. Relative to the workspace.
    "protected_paths": [
        ".git/**",
        ".agent-guard/**",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".codex/**",
        ".agents/**",
        "opencode.json",
        ".opencode/**",
        "originals/**",
    ],
    # Area A. Deleting inside these needs no confirmation.
    "scratch_paths": [
        "tmp/**",
        "scratch/**",
        ".cache/**",
        "build/**",
        "dist/**",
        "node_modules/**",
        "**/__pycache__/**",
        "*.pyc",
        "*.log",
        ".agent-trash/**",
    ],
    # Files whose content is usually secret. Reading them needs confirmation.
    "secret_patterns": [
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
        "id_rsa*",
        "id_ed25519*",
        ".ssh/**",
        ".aws/**",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials*",
        "*secret*",
    ],
    "secret_allow": [".env.example", ".env.sample", ".env.template"],
    # One edit touching this many files or more needs confirmation.
    "mass_change_files": 20,
    "log_decisions": True,
}

# ---------------------------------------------------------------------------
# Policy and paths
# ---------------------------------------------------------------------------


def load_policy() -> dict[str, Any]:
    policy = dict(DEFAULT_POLICY)
    path = os.environ.get("AGENT_GUARD_POLICY") or os.path.join(GUARD_DIR, "policy.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
        for key, value in user.items():
            if key.startswith("_"):
                continue
            policy[key] = value
    return policy


def workspace_root(policy: dict[str, Any], event: dict[str, Any]) -> str:
    """The folder the agent may work in.

    Priority: AGENT_GUARD_WORKSPACE, policy.workspace_root, the parent of
    .agent-guard/ when the guard is installed there, then the event's cwd.
    """
    env = os.environ.get("AGENT_GUARD_WORKSPACE")
    if env:
        return os.path.abspath(env)
    if policy.get("workspace_root"):
        return os.path.abspath(policy["workspace_root"])
    if os.path.basename(GUARD_DIR) == ".agent-guard":
        return os.path.dirname(GUARD_DIR)
    for key in ("cwd", "directory"):
        if isinstance(event.get(key), str) and event[key]:
            return os.path.abspath(event[key])
    paths = event.get("workspacePaths")
    if isinstance(paths, list) and paths and isinstance(paths[0], str):
        return os.path.abspath(paths[0])
    return os.getcwd()


def _norm(path: str) -> str:
    path = path.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", path):
        path = path[0].lower() + path[1:]
    return path


@dataclass
class Where:
    raw: str
    rel: str | None  # path relative to the workspace, None when outside
    outside: bool
    unknown: bool  # contains variables or globs we cannot resolve


def locate(raw: str, root: str, cwd: str) -> Where:
    text = raw.strip().strip("'\"")
    unknown = bool(re.search(r"[$%`]|\*|\?|\{", text)) and not re.fullmatch(r"[\w./\\:-]*\*[\w.]*", text)
    expanded = os.path.expanduser(text)
    if not os.path.isabs(expanded) and not re.match(r"^[A-Za-z]:[\\/]", expanded):
        expanded = os.path.join(cwd, expanded)
    full = _norm(os.path.normpath(expanded))
    base = _norm(os.path.normpath(root))
    if full == base:
        return Where(raw, ".", False, unknown)
    if full.lower().startswith(base.lower().rstrip("/") + "/"):
        return Where(raw, full[len(base.rstrip("/")) + 1 :], False, unknown)
    return Where(raw, None, True, unknown)


def matches(rel: str, patterns: Iterable[str]) -> bool:
    rel = rel.strip("/")
    name = PurePosixPath(rel).name
    for pat in patterns:
        pat = pat.strip("/")
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat):
            return True
        if pat.endswith("/**"):
            head = pat[:-3]
            if rel == head or rel.startswith(head + "/") or fnmatch.fnmatch(rel, head):
                return True
            if head.startswith("**/") and ("/" + head[3:] + "/") in ("/" + rel + "/"):
                return True
    return False


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

LEVEL = {"allow": 0, "confirm": 1, "block": 2}


@dataclass
class Finding:
    level: str  # confirm | block
    title: str
    what: str
    loss: str
    undo: str
    alternative: str


@dataclass
class Verdict:
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def decision(self) -> str:
        if not self.findings:
            return "allow"
        return max((f.level for f in self.findings), key=LEVEL.__getitem__)


TRASH_HINT = "削除せず、python3 .agent-guard/trash.py <対象> で .agent-trash/ へ移す（あとで戻せます）"


def f_delete_protected(target: str) -> Finding:
    return Finding(
        "block",
        "保護されたファイルの削除・変更",
        f"保護対象（原本・設定・履歴）の {target} を消す、または書き換えようとしています",
        "原本、Gitの履歴、安全設定そのものが失われる可能性があります",
        "元に戻せない可能性が高いです",
        "必要なファイルを作業フォルダへコピーして、コピーの方を編集する",
    )


def f_delete_outside(target: str) -> Finding:
    return Finding(
        "block",
        "作業フォルダの外のファイル削除・変更",
        f"作業フォルダの外にある {target} を消す、または書き換えようとしています",
        "ほかのプロジェクト、個人ファイル、共有フォルダのデータが失われる可能性があります",
        "元に戻せない可能性が高いです",
        "作業フォルダの中だけで作業する。外のファイルが必要なら人がコピーして渡す",
    )


def f_delete_workspace(targets: str) -> Finding:
    return Finding(
        "confirm",
        "ファイルの削除",
        f"作業フォルダの中の {targets} を削除しようとしています",
        "まだ保存していない作業や、手作業で作ったファイルが消える可能性があります",
        "ゴミ箱には入りません。Gitで記録済みの分と、作業前バックアップの分だけ戻せます",
        TRASH_HINT,
    )


def f_delete_unknown(cmd: str) -> Finding:
    return Finding(
        "confirm",
        "削除範囲が読めない削除",
        f"変数やワイルドカードを含む削除を実行しようとしています（{cmd}）",
        "想定より広い範囲のファイルが消える可能性があります",
        "Gitで記録済みの分と、作業前バックアップの分だけ戻せます",
        "対象のファイル名を一つずつ書き出して確認してから、.agent-trash/ へ移す",
    )


# Each rule: (level, regex, title, what, loss, undo, alternative)
COMMAND_RULES: list[tuple[str, str, str, str, str, str, str]] = [
    # --- sending data out --------------------------------------------------
    (
        "block",
        r"\bgit\s+push\b",
        "外部への送信（git push）",
        "コードを外部のGitサーバーへ送ろうとしています",
        "社内のコードや機密が外部に公開される可能性があります",
        "一度送ったものは取り消せません",
        "送信は人が内容を確認してから手作業で行う",
    ),
    (
        "block",
        r"\b(npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b|\bgem\s+push\b|\bdocker\s+push\b|\bpodman\s+push\b",
        "外部への公開（パッケージ・イメージの公開）",
        "パッケージやコンテナイメージを外部へ公開しようとしています",
        "社内のコードや機密が外部に公開される可能性があります",
        "公開したものは取り消せないことが多いです",
        "公開は人が内容を確認してから手作業で行う",
    ),
    (
        "block",
        r"\bgh\s+(repo\s+create|release\s+create|pr\s+create|issue\s+create|gist\s+create|api\b.*-X\s*(POST|PUT|PATCH|DELETE))",
        "外部サービスへの書き込み（GitHub）",
        "GitHubにリポジトリ・リリース・PR・Issueなどを作ろうとしています",
        "社内の情報が外部に公開される可能性があります",
        "公開した内容はキャッシュに残ることがあります",
        "必要なら人が内容を確認してから手作業で行う",
    ),
    (
        "block",
        r"\bcurl\b[^|;&]*(\s-(d|F|T)\b|\s--data\b|\s--data-\w+|\s--form\b|\s--upload-file\b|\s-X\s*(POST|PUT|PATCH|DELETE)\b|\s--request\s+(POST|PUT|PATCH|DELETE)\b)",
        "外部へのデータ送信（curl）",
        "curl でデータを外部のサーバーへ送ろうとしています",
        "社内のファイルや機密情報が外部に送られる可能性があります",
        "送ったデータは取り消せません",
        "情報を見るだけなら GET（ダウンロード）だけを使う",
    ),
    (
        "block",
        r"\bwget\b[^|;&]*--(post|body)-(data|file)\b|\bInvoke-(WebRequest|RestMethod)\b[^|;&]*(-Method\s+(Post|Put|Patch|Delete)|-InFile|-Body)",
        "外部へのデータ送信",
        "Web経由でデータを外部のサーバーへ送ろうとしています",
        "社内のファイルや機密情報が外部に送られる可能性があります",
        "送ったデータは取り消せません",
        "情報を見るだけなら GET（ダウンロード）だけを使う",
    ),
    (
        "block",
        r"(^|[\s;&|(])(scp|sftp|ftp|nc|ncat|netcat|socat|telnet)\s|\brsync\b[^|;&]*\s[\w.@-]+:",
        "外部へのファイル転送",
        "ファイルを別のコンピューターへ転送しようとしています",
        "社内のファイルが外部に送られる可能性があります",
        "送ったデータは取り消せません",
        "転送は人が内容を確認してから手作業で行う",
    ),
    # --- running code from the internet straight away ----------------------
    (
        "block",
        r"\b(curl|wget)\b[^;&]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b|\b(curl|wget)\b[^;&]*\|\s*(python3?|node|perl|ruby)\b|\b(iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b[^;&]*\|\s*(iex|Invoke-Expression)\b|\b(iex|Invoke-Expression)\s*\(\s*(iwr|irm|New-Object\s+Net\.WebClient)",
        "ダウンロードしたプログラムの即時実行",
        "インターネットから取ってきたスクリプトを、中身を確かめずにその場で実行しようとしています",
        "悪意あるプログラムがこのPCの権限で動く可能性があります",
        "実行された内容によっては元に戻せません",
        "いったんファイルに保存して中身を確認し、隔離環境（コンテナ）で実行する",
    ),
    # --- OS and permissions -------------------------------------------------
    (
        "block",
        r"(^|[\s;&|(])(sudo|su|doas|runas)\s|\bStart-Process\b[^;&]*-Verb\s+RunAs",
        "管理者権限での実行",
        "管理者（root）の権限でコマンドを実行しようとしています",
        "OSやほかの利用者のデータまで変更できてしまいます",
        "OSの変更は元に戻せないことがあります",
        "管理者権限が必要な作業は、管理者に依頼する",
    ),
    (
        "block",
        r"\b(mkfs(\.\w+)?|fdisk|parted|diskpart|format\s+[a-zA-Z]:)|\bdd\b[^;&]*\bof=/dev/|>\s*/dev/sd[a-z]",
        "ディスクの初期化",
        "ディスクやパーティションを書き換えようとしています",
        "ディスク上のすべてのデータが失われます",
        "元に戻せません",
        "ディスクの操作は管理者に依頼する",
    ),
    (
        "block",
        r"\b(systemctl|service|launchctl|schtasks|crontab|reg(\.exe)?\s+(add|delete|import)|Set-ExecutionPolicy|Set-ItemProperty\s+-Path\s+'?HK|netsh|iptables|nft|ufw|shutdown|reboot|halt|poweroff|useradd|userdel|usermod|passwd|chpasswd|visudo)\b",
        "OS設定の変更",
        "OSの設定、自動起動、ネットワーク設定、ユーザーなどを変更しようとしています",
        "PC全体の動作やセキュリティ設定が変わる可能性があります",
        "元に戻すには専門知識が必要です",
        "OSの設定変更は管理者に依頼する",
    ),
    (
        "block",
        r"\bchmod\b[^;&]*\b(777|a\+w|o\+w)\b|\bchmod\s+-R\b[^;&]*\s/(\s|$)|\bchown\s+-R\b|\bicacls\b[^;&]*/grant\b[^;&]*Everyone|\btakeown\b",
        "アクセス権の変更",
        "ファイルのアクセス権を広げる、または所有者を変えようとしています",
        "守っていたファイルを誰でも変更できるようになる可能性があります",
        "元の権限を覚えていないと戻せません",
        "アクセス権の変更は管理者に依頼する",
    ),
    # --- the guard itself ---------------------------------------------------
    (
        "block",
        r"\.agent-guard\b(?!/trash\.py)|\.claude[/\\]settings|\.codex[/\\]|\.agents[/\\]hooks|opencode\.json|\.opencode[/\\]plugins|--dangerously|--no-verify|hooks\s*=\s*false|disableAllHooks",
        "安全設定の変更・回避",
        "安全設定（Hook、権限設定）を書き換える、または回避しようとしています",
        "安全装置が外れ、ほかの事故を防げなくなります",
        "気づかないうちに保護が無効になる可能性があります",
        "安全設定の変更は管理者が行う",
    ),
    # --- git history ---------------------------------------------------------
    (
        "confirm",
        r"\bgit\s+(reset\s+--hard|clean\s+-\w*[fdx]|checkout\s+(--\s+)?\.(\s|$)|restore\s+(--\S+\s+)*\.(\s|$)|stash\s+(clear|drop)|branch\s+-D|filter-branch|filter-repo|reflog\s+expire|gc\s+--prune)",
        "Gitの変更履歴の破棄",
        "まだ記録していない変更、またはGitの履歴を捨てようとしています",
        "保存前の作業内容が消える可能性があります",
        "記録前の変更は元に戻せません",
        "先に git stash や git commit で今の状態を記録しておく",
    ),
    # --- secrets --------------------------------------------------------------
    (
        "confirm",
        r"(^|[\s/\\'\"=])(\.env(\.[\w-]+)?|id_rsa|id_ed25519|\.netrc|\.npmrc|\.pypirc|credentials(\.json)?|\.aws[/\\]|\.ssh[/\\])(?=$|[\s'\";|&)])",
        "秘密情報の読み取り",
        "パスワードや鍵が入っているかもしれないファイルにアクセスしようとしています",
        "読んだ内容がAIの会話や外部に残る可能性があります",
        "一度見えた秘密情報は取り消せません（鍵の作り直しが必要になります）",
        "秘密情報を使う作業は、人が自分で行う",
    ),
]

_COMPILED = [(lvl, re.compile(rx, re.IGNORECASE), t, w, l, u, a) for lvl, rx, t, w, l, u, a in COMMAND_RULES]
_ENV_EXAMPLE = re.compile(r"\.env\.(example|sample|template)\b", re.IGNORECASE)

DELETE_CMDS = {"rm", "rmdir", "unlink", "del", "erase", "rd", "remove-item", "ri", "rimraf", "trash", "shred", "srm", "wipe"}
DELETE_WRAPPERS = re.compile(
    r"\bfind\b[^;&|]*\s-(delete|exec\s+rm)\b|\bshutil\.rmtree\b|\bos\.(remove|unlink|rmdir|removedirs)\b|\b(Path|pathlib\.Path)\([^)]*\)\.(unlink|rmdir)\b|\bfs\.(rm|rmSync|unlink|unlinkSync|rmdir|rmdirSync)\b|\bxargs\b[^;&|]*\brm\b|\bgit\s+rm\b|\[System\.IO\.(File|Directory)\]::Delete",
    re.IGNORECASE,
)
REDIRECT = re.compile(r"(?<![<>\d&])>>?\s*(['\"]?)([^\s;&|'\"]+)\1")
MOVE_CMDS = {"mv", "move", "move-item", "mi", "cp", "copy", "copy-item", "cpi", "tee", "truncate", "touch", "mkdir", "ln"}


def split_segments(command: str) -> list[str]:
    parts = re.split(r"\|\||&&|;|\n|\|(?!\|)", command)
    return [p.strip() for p in parts if p.strip()]


def tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def strip_prefix(tok: list[str]) -> list[str]:
    i = 0
    while i < len(tok) and (tok[i] in {"command", "builtin", "exec", "nohup", "time", "env", "xargs", "cmd", "/c", "powershell", "pwsh", "-Command", "-c"} or re.match(r"^\w+=", tok[i])):
        i += 1
    return tok[i:]


def classify_command(command: str, root: str, cwd: str, policy: dict[str, Any], verdict: Verdict) -> None:
    text = command.strip()
    if not text:
        return
    seen_titles: set[str] = set()
    for lvl, rx, title, what, loss, undo, alt in _COMPILED:
        if title == "秘密情報の読み取り" and _ENV_EXAMPLE.search(text) and not re.search(r"\.env(?!\.(example|sample|template))\b", text):
            continue
        if rx.search(text) and title not in seen_titles:
            seen_titles.add(title)
            verdict.add(Finding(lvl, title, what + f"（{shorten(text)}）", loss, undo, alt))

    delete_targets: list[Where] = []
    unknown_delete = False
    for seg in split_segments(text):
        tok = strip_prefix(tokens(seg))
        if not tok:
            continue
        name = os.path.basename(tok[0]).lower()
        if name.endswith(".exe"):
            name = name[:-4]
        args = [t for t in tok[1:] if not t.startswith("-") and not re.match(r"^/[a-zA-Z]$", t)]
        if name in DELETE_CMDS:
            if not args:
                unknown_delete = True
            for a in args:
                w = locate(a, root, cwd)
                delete_targets.append(w)
        elif name in MOVE_CMDS:
            for a in args:
                w = locate(a, root, cwd)
                check_write_target(w, policy, verdict, via=name)
        for m in REDIRECT.finditer(seg):
            target = m.group(2)
            if target.startswith("&") or target in {"/dev/null", "nul", "NUL", "$null"}:
                continue
            check_write_target(locate(target, root, cwd), policy, verdict, via="リダイレクト")

    if DELETE_WRAPPERS.search(text):
        unknown_delete = True

    judge_deletes(delete_targets, unknown_delete, text, policy, verdict)


def judge_deletes(targets: list[Where], unknown: bool, text: str, policy: dict[str, Any], verdict: Verdict) -> None:
    in_ws: list[str] = []
    for w in targets:
        if w.outside:
            verdict.add(f_delete_outside(w.raw))
        elif w.rel in (".", "") or w.rel is None:
            verdict.add(f_delete_outside(w.raw + "（作業フォルダ全体）"))
        elif matches(w.rel, policy["protected_paths"]):
            verdict.add(f_delete_protected(w.rel))
        elif w.unknown:
            unknown = True
        elif matches(w.rel, policy["scratch_paths"]):
            continue
        else:
            in_ws.append(w.rel)
    if in_ws:
        verdict.add(f_delete_workspace("、".join(in_ws[:5]) + (" ほか" if len(in_ws) > 5 else "")))
    if unknown:
        verdict.add(f_delete_unknown(shorten(text)))


def check_write_target(w: Where, policy: dict[str, Any], verdict: Verdict, via: str = "") -> None:
    if w.outside:
        if _norm(w.raw).startswith(("/tmp/", "/var/tmp/")):
            return
        verdict.add(f_delete_outside(w.raw))
    elif w.rel and matches(w.rel, policy["protected_paths"]):
        verdict.add(f_delete_protected(w.rel))


def shorten(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Normalising the four harnesses' events
# ---------------------------------------------------------------------------

SHELL_TOOLS = {"bash", "run_command", "shell", "local_shell", "exec_command", "powershell", "run_in_terminal"}
WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit", "write_to_file", "replace_file_content", "multi_replace_file_content", "create_file", "edit_file", "patch"}
READ_TOOLS = {"read", "view_file", "read_file", "view_code_item", "grep", "glob"}
DELETE_TOOLS = {"delete_file", "remove_file"}
PATH_KEYS = re.compile(r"(file_?path|target_?file|absolute_?path|^path$|notebook_path|filePath|TargetFile|AbsolutePath|DirectoryPath)", re.IGNORECASE)


@dataclass
class Call:
    tool: str
    command: str | None
    paths: list[str]
    patch: str | None
    cwd: str


def normalise(tool: str, event: dict[str, Any], root: str) -> Call:
    if tool == "antigravity":
        tc = event.get("toolCall") or {}
        name = str(tc.get("name") or "")
        args = tc.get("args") or {}
        command = args.get("CommandLine") if isinstance(args, dict) else None
        cwd = args.get("Cwd") if isinstance(args, dict) and args.get("Cwd") else root
    elif tool == "opencode":
        name = str(event.get("tool") or "")
        args = event.get("args") or {}
        command = args.get("command") if isinstance(args, dict) else None
        cwd = event.get("directory") or root
    else:  # claude, codex, generic
        name = str(event.get("tool_name") or event.get("tool") or "")
        args = event.get("tool_input") or event.get("args") or {}
        command = args.get("command") if isinstance(args, dict) else None
        cwd = event.get("cwd") or root
    if isinstance(command, list):
        command = " ".join(str(c) for c in command)
    lname = name.lower()
    patch = None
    if lname in {"apply_patch"} or (isinstance(command, str) and command.lstrip().startswith("*** Begin Patch")):
        patch, command = command, None
    elif lname not in SHELL_TOOLS:
        command = None if not lname.startswith("mcp") else command
    paths: list[str] = []
    if isinstance(args, dict):
        for key, value in args.items():
            if isinstance(value, str) and PATH_KEYS.search(key):
                paths.append(value)
    return Call(lname, command if isinstance(command, str) else None, paths, patch, str(cwd))


PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$", re.MULTILINE)
PATCH_MOVE = re.compile(r"^\*\*\* Move to: (.+)$", re.MULTILINE)


def evaluate(tool: str, event: dict[str, Any], policy: dict[str, Any]) -> Verdict:
    root = workspace_root(policy, event)
    call = normalise(tool, event, root)
    verdict = Verdict()
    if call.command:
        classify_command(call.command, root, call.cwd, policy, verdict)
    if call.patch:
        files = PATCH_FILE.findall(call.patch)
        deletes: list[Where] = []
        for kind, path in files:
            w = locate(path.strip(), root, call.cwd)
            if kind == "Delete":
                deletes.append(w)
            else:
                check_write_target(w, policy, verdict)
        for path in PATCH_MOVE.findall(call.patch):
            check_write_target(locate(path.strip(), root, call.cwd), policy, verdict)
        judge_deletes(deletes, False, "apply_patch", policy, verdict)
        if len(files) >= int(policy["mass_change_files"]):
            verdict.add(mass_change(len(files)))
    for p in call.paths:
        w = locate(p, root, call.cwd)
        if call.tool in DELETE_TOOLS:
            judge_deletes([w], False, call.tool, policy, verdict)
        elif call.tool in READ_TOOLS:
            if w.rel is not None and matches(w.rel, policy["secret_patterns"]) and not matches(w.rel, policy["secret_allow"]):
                verdict.add(Finding("confirm", "秘密情報の読み取り", f"{w.rel} を読もうとしています", "読んだ内容がAIの会話や外部に残る可能性があります", "一度見えた秘密情報は取り消せません", "秘密情報を使う作業は、人が自分で行う"))
            elif w.outside and matches(_norm(p), policy["secret_patterns"]):
                verdict.add(Finding("block", "秘密情報の読み取り", f"作業フォルダの外の {p} を読もうとしています", "鍵やパスワードが漏れる可能性があります", "一度見えた秘密情報は取り消せません", "秘密情報を使う作業は、人が自分で行う"))
        elif call.tool in WRITE_TOOLS or call.tool.startswith("mcp"):
            check_write_target(w, policy, verdict)
    return verdict


def mass_change(count: int) -> Finding:
    return Finding(
        "confirm",
        "大量のファイル変更",
        f"一度に {count} 個のファイルを変更しようとしています",
        "依頼していない場所まで変わる可能性があります",
        "Gitで記録済みなら戻せますが、確認に時間がかかります",
        "変更を小分けにして、一つずつ内容を確認する",
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def explain(verdict: Verdict, for_codex: bool = False) -> str:
    worst = verdict.decision
    head = "【この操作は止めました】" if worst == "block" else "【確認が必要です】"
    lines = [head]
    for f in verdict.findings:
        lines += [
            f"■ {f.title}",
            f"・AIがやろうとしていること：{f.what}",
            f"・失われる可能性があるもの：{f.loss}",
            f"・元に戻せるか：{f.undo}",
            f"・安全な代わりの方法：{f.alternative}",
        ]
    if worst == "block":
        lines.append("AIへ：この操作は実行しないでください。上の「安全な代わりの方法」を使うか、人に相談してください。")
    elif for_codex:
        lines.append("AIへ：この操作は自動では実行できません。利用者に上の内容を日本語で説明し、安全な代わりの方法を提案してください。利用者が実行を望む場合は、利用者自身に実行してもらってください。")
    else:
        lines.append("AIへ：利用者に、何をするのか・何が失われるのか・元に戻せるのかを日本語で説明してから進めてください。")
    return "\n".join(lines)


def render(tool: str, verdict: Verdict) -> tuple[str, int]:
    d = verdict.decision
    if tool == "claude":
        if d == "allow":
            return "", 0
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny" if d == "block" else "ask",
                "permissionDecisionReason": explain(verdict),
            }
        }
        return json.dumps(out, ensure_ascii=False), 0
    if tool == "codex":
        # Codex PreToolUse supports deny but not ask ("ask" fails open), so a
        # confirmation is turned into a deny that tells the agent to ask.
        if d == "allow":
            return "", 0
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": explain(verdict, for_codex=True),
            }
        }
        return json.dumps(out, ensure_ascii=False), 0
    if tool == "antigravity":
        mapping = {"allow": "allow", "confirm": "force_ask", "block": "deny"}
        out: dict[str, Any] = {"decision": mapping[d]}
        if d != "allow":
            out["reason"] = explain(verdict)
        return json.dumps(out, ensure_ascii=False), 0
    # opencode and generic. An OpenCode plugin cannot open the approval prompt,
    # so the plugin blocks "ask" too; the reason tells the agent to ask instead.
    mapping = {"allow": "allow", "confirm": "ask", "block": "deny"}
    out = {"decision": mapping[d], "reason": explain(verdict, for_codex=(tool == "opencode")) if d != "allow" else ""}
    return json.dumps(out, ensure_ascii=False), 0


def log(policy: dict[str, Any], tool: str, event: dict[str, Any], verdict: Verdict) -> None:
    if not policy.get("log_decisions"):
        return
    try:
        log_dir = os.environ.get("AGENT_GUARD_LOG_DIR") or os.path.join(GUARD_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        record = {
            "time": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "tool": tool,
            "decision": verdict.decision,
            "titles": [f.title for f in verdict.findings],
            "call": shorten(json.dumps(event.get("tool_input") or event.get("toolCall") or event.get("args") or {}, ensure_ascii=False), 400),
        }
        with open(os.path.join(log_dir, "decisions.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tool", choices=["claude", "codex", "antigravity", "opencode", "generic"], required=True)
    parser.add_argument("--version", action="version", version=VERSION)
    ns = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        event = json.loads(raw) if raw.strip() else {}
        if not isinstance(event, dict):
            event = {}
        policy = load_policy()
        verdict = evaluate(ns.tool, event, policy)
    except Exception as exc:  # fail closed: a broken guard must not wave things through
        verdict = Verdict([Finding("block", "安全チェックのエラー", f"安全チェックが失敗しました（{type(exc).__name__}: {exc}）", "判定できないため、念のため止めました", "—", "管理者に agent-guard の設定を確認してもらう")])
        event = {}
        policy = {"log_decisions": True}
    log(policy, ns.tool, event, verdict)
    text, code = render(ns.tool, verdict)
    if text:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
