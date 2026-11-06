# Google Antigravity 用セットアップ

Google Antigravity（Gemini系のエージェントIDE）で使う設定です。Antigravity はHookから `force_ask`（強制的に人へ確認）を出せるので、Claude Code に近い運用ができます。

## インストール

```bash
python install.py --project <作業フォルダ> --tool antigravity
```

書き込まれるもの：

| ファイル | 役割 |
|---|---|
| `<作業フォルダ>/.agents/hooks.json` | Hook登録（agent_guard.py を呼ぶ） |
| `<作業フォルダ>/.agent-guard/` | 共通の判定エンジン |

グローバル設定（`~/.gemini`）は変更しません。全プロジェクトに適用したい場合は同じ内容を `~/.gemini/config/hooks.json` に置けます（`settings.example.json` はグローバル用の例です）。

## 設定の中身（`.agents/hooks.json`）

- **PreToolUse**（`matcher: "*"` — すべてのツール呼び出し）：agent_guard.py が判定し、
  - 取消不能・機密に関わる命令 → `deny`
  - 業務ファイルの削除など確認が必要な操作 → `force_ask`（操作が人の確認に回る）
  - 安全 → `allow`（通常の権限判定に進む。`allow` は「許可確定」ではない点に注意）
- **SessionStart**：`checkpoint.py` で作業前スナップショット（第3層）。

形式のメモ：最上位は「Hookの名前 → イベント」の形です（`"hooks"` で囲みません）。コマンドは `toolCall.args.CommandLine` に入ってくるため、agent_guard はそこを読みます。

## 導入後の確認

1. Antigravity で作業フォルダを開く。
2. `/hooks`（CLI）または Settings > Customizations > Hooks で `agent-guard` が読み込まれているか確認する。
3. 試しに「`docs` フォルダを削除して」と頼み、**確認（force_ask）に回ること**を確認する。

## 動作の違い（ほかのツールとの比較）

| 操作 | このキットの挙動 |
|---|---|
| 一時ファイル（`tmp/` 等）の削除 | そのまま実行 |
| `src/` `docs/` など業務ファイルの削除 | **force_ask**（人の確認） |
| `curl … | bash`、外部送信、`sudo`、原本・設定の変更 | **deny**（拒否） |

## サンドボックス（第1層）

Antigravity 自身にもサンドボックス（Default プリセット。Linux / macOS / Windows 11 24H2以降）があります。設定は IDE 側のプリセット選択になるため、このキットのファイルには含まれません。**Default プリセットのまま**（プロジェクトの外に書けない）使うことを前提にしています。

## 未確認の仕様

- Hookが失敗したとき（終了コード・時間切れ・JSONの誤り）の扱いは公式に明記されていません。agent_guard は内部エラーのとき `deny` を返します（止める側に倒れる）。
- ファイルを書くツールの正式な引数名は確定していません。agent_guard は名前に `path` / `file` を含む引数をすべて検査します。

詳細は [docs/spec-notes.md](../docs/spec-notes.md)。
