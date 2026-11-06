# Claude Code 用セットアップ

Claude Code は、4ツールの中でHookと権限設定がもっとも揃っています。このキットでは **Hookからの承認画面（ask）が使える** ので、「確認が必要な操作」は本当にその場で承認できます。

## インストール

```bash
python install.py --project <作業フォルダ> --tool claude
```

書き込まれるもの（既存ファイルは上書きしません）：

| ファイル | 役割 |
|---|---|
| `<作業フォルダ>/.claude/settings.json` | 権限ルール（allow / ask / deny）、サンドボックス設定、Hook登録 |
| `<作業フォルダ>/.agent-guard/` | 共通の判定エンジン（agent_guard.py ほか） |

グローバル設定（`~/.claude`）は変更しません。

## 設定の中身（`.claude/settings.json`）

- **Hook（PreToolUse）**: `Bash / Write / Edit / MultiEdit / NotebookEdit / Read` の実行前に agent_guard.py を呼び、危険な命令を `deny`（拒否）または `ask`（承認画面）にします。拒否の理由は日本語で表示されます。
- **権限（permissions）**:
  - `deny`: `git push`、`sudo`、`npm publish`、安全設定ファイル（`.claude/` `.agent-guard/` `.git/` `originals/`）への編集、`~/.ssh` `~/.aws` の読み取り
  - `ask`: `.env` 系ファイルの読み取り
  - `allow`: `git status/diff/log`、`ls`、ゴミ箱退避コマンド（trash.py）
  - `defaultMode: acceptEdits` — 通常の編集はいちいち聞かれない（原則B）
  - `disableBypassPermissionsMode: disable` — `--dangerously-skip-permissions` を無効化
- **サンドボックス**: `sandbox.enabled: true`。許可ドメイン（npm・PyPI・GitHub系）以外への通信を制限します。**Windows本体ではサンドボックスが効かない**ため、WSL2 かコンテナ（`lab/` 参照）で動かすのが安全です（macOS・Linuxは対応）。
- **SessionStart Hook**: セッション開始時に `checkpoint.py` でスナップショットを取ります（第3層）。

## 導入後の確認

1. 作業フォルダで `claude` を起動する。
2. `/hooks` で `agent-guard` のPreToolUseが登録されているか確認する。
3. `/permissions` で deny / ask のルールが見えるか確認する。
4. 試しに「`rm -rf docs` を実行して」と頼み、**承認画面が出ること**を確認する。

## 動作の違い（ほかのツールとの比較）

| 操作 | このキットの挙動 |
|---|---|
| 一時ファイル（`tmp/` 等）の削除 | そのまま実行 |
| `src/` `docs/` など業務ファイルの削除 | **ask**（承認画面。日本語で理由を表示） |
| `git push`、外部送信、`sudo`、原本・設定の変更 | **deny**（拒否） |

## グローバルに入れたい場合

すべてのプロジェクトに同じ安全設定を効かせたいときは、同じ内容を `~/.claude/settings.json` に書くこともできますが、**まずはプロジェクト単位**（`--project`）で始めることをすすめます（影響範囲が小さく、外すのも簡単なため）。
