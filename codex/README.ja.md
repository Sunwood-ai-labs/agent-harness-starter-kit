# Codex 用セットアップ

Codex（OpenAI のCLIエージェント）で使う設定です。**最重要の注意：Codex の PreToolUse Hook は `deny` か `allow` しか返せず、`ask`（承認画面）を出せません。** 仕様上、Hookが `ask` を返すと「Hook失敗」扱いになり、**操作は止まらずにそのまま実行されてしまいます**（公式ドキュメント確認済み → [docs/spec-notes.md](../docs/spec-notes.md)）。

そこでこのキットは、Codex では「確認が必要な操作」も **`deny`（拒否）** にしています。拒否の理由には「利用者に日本語で説明し、実行してほしいなら利用者自身が実行するように」とAIへの指示が入っています。つまりCodexでは **確認は人の手作業** になります。

## インストール

```bash
python install.py --project <作業フォルダ> --tool codex
```

書き込まれるもの：

| ファイル | 役割 |
|---|---|
| `<作業フォルダ>/.codex/config.toml` | サンドボックスと承認ポリシー |
| `<作業フォルダ>/.codex/hooks.json` | Hook登録（agent_guard.py を呼ぶ） |
| `<作業フォルダ>/.agent-guard/` | 共通の判定エンジン |

グローバル設定（`~/.codex`）は変更しません。

## 設定の中身

- **`.codex/config.toml`**
  - `sandbox_mode = "workspace-write"` — エージェントが動かすコマンドは、**この作業フォルダの中にしか書けない**サンドボックスで実行されます（第1層）。
  - `approval_policy = "on-request"` — サンドボックスの外に出る操作（外への書き込み、ネットワーク利用）はCodex本体が承認を求めます。
  - `network_access = false` — サンドボックス内のコマンドはネットに出られません（=ファイルを外へ送れない）。Codex自身のWeb検索は別経路なので使えます。
- **`.codex/hooks.json`**
  - PreToolUse（`Bash` と `apply_patch` の2種のツール）：agent_guard.py が `git push` `sudo` `curl -d` 等の命令を **deny**、業務ファイルの削除も（askできないので）**deny＋説明** にします。
  - SessionStart：`checkpoint.py` で作業前スナップショット（第3層）。

## 導入後の確認（信頼の手順が必要です）

Codex はプロジェクトの設定を **信頼（trust）するまで読み込みません**。2段階の信頼が必要です：

1. 作業フォルダで `codex` を起動し、**プロジェクトを信頼（trust）する**。
2. `/hooks` を開き、`agent-guard` のHookを**個別に信頼（trust）する**。

この手順を飛ばすとHookは動きません。`/hooks` で緑色（有効）になっていることを確認してください。

3. 試しに「`rm -rf docs` を実行して」と頼み、**拒否されて理由が表示されること**（承認画面ではなく拒否になるのが正常）を確認する。

## 動作の違い（ほかのツールとの比較）

| 操作 | このキットの挙動（Codex） |
|---|---|
| 一時ファイル（`tmp/` 等）の削除 | そのまま実行 |
| `src/` `docs/` など業務ファイルの削除 | **deny**＋「利用者に説明して、利用者が実行するように」の指示（askが使えないため） |
| `git push`、外部送信、`sudo`、原本・設定の変更 | **deny**（拒否） |

## グローバルに入れたい場合

`~/.codex/hooks.json` と `~/.codex/config.toml` に同じ内容を書けば全プロジェクトに適用できますが、まずはプロジェクト単位で始めてください。グローバルのHookはすべてのフォルダのCodexに影響します。
