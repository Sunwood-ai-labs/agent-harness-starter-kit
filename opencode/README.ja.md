# OpenCode 用セットアップ

OpenCode（OSSのCLI/エージェント）で使う設定です。**重要な注意が2つあります。**

1. **OpenCode の本体設定（`opencode.json` の `permission`）は `ask`（承認）と `deny`（拒否）を出せます**が、**プラグインからは承認画面を出せません**。そのため判定プラグインは `ask` 相当も止めて、理由をAIに伝えます（Codex と同じ方針）。
2. `permission` のパターンは **複数に当てはまるとき、最後に書いたルールが優先** されます。順序を変えると効かなくなるので、テンプレートの並び順は保ってください。

また `--auto`（自動実行モード）は `ask` を自動で許可しますが、**`deny` は守られたまま**です。危険な命令の拒否は auto でも効きます。

OpenCode 自身にはサンドボックスがなく、**シェルは利用者の権限でそのまま動きます**。第1層（権限・隔離）を効かせたい場合は、コンテナ内で実行する（`lab/` 参照）か、OSのアクセス権で原本を読み取り専用にしてください。

## インストール

```bash
python install.py --project <作業フォルダ> --tool opencode
```

書き込まれるもの：

| ファイル | 役割 |
|---|---|
| `<作業フォルダ>/opencode.json` | 権限ルール（allow / ask / deny） |
| `<作業フォルダ>/.opencode/plugins/agent-guard.js` | 実行前チェックのプラグイン（agent_guard.py を呼ぶ） |
| `<作業フォルダ>/.agent-guard/` | 共通の判定エンジン |

グローバル設定（`~/.config/opencode`）は変更しません。

## 設定の中身

- **`opencode.json`（権限）**
  - `bash` コマンドは既定 `ask`。読み取り系（`ls` `cat` `grep` `git status/diff/log`、`git add/commit`、`npm test` 等）だけ `allow`。
  - `rm *`、`git reset --hard*`、`git clean *` → `ask`（業務ファイルの削除確認）。
  - `git push*`、`sudo *`、`npm publish*` → `deny`。
  - `external_directory: "deny"` — 作業フォルダの外へのアクセスを拒否。
  - `doom_loop: "ask"` — 連続失敗が続いたら確認。
- **`.opencode/plugins/agent-guard.js`**
  - `tool.execute.before` ですべてのツール呼び出しを検査。
  - `deny` と `ask` の両方を止める（プラグインは承認画面を出せないため。理由にはAIへの日本語の説明指示が入る）。
  - agent_guard.py が呼べない・壊れた場合も止めます（fail closed）。

## 導入後の確認

1. 作業フォルダで `opencode` を起動する。
2. `opencode debug config` を実行し、`permission.bash` に `git push*` の `deny` 等が反映されているか確認する。
3. 試しに「`rm -rf docs` を実行して」と頼み、**止まって理由が表示されること**を確認する。

## 動作の違い（ほかのツールとの比較）

| 操作 | このキットの挙動 |
|---|---|
| 一時ファイル（`tmp/` 等）の削除 | そのまま実行（許可リスト＋agent-guard両方で判断） |
| `src/` `docs/` など業務ファイルの削除 | プラグインが **ask 相当で停止**＋説明。対話中なら本体の `ask` も効く |
| `git push`、`sudo`、`npm publish` | **deny**（拒否。`--auto` でも守られる） |

## 連携する無料モデルでの確認

OpenCode のホスト型無料モデル（`opencode/<モデル名>`）を使う e2e テストを `lab/e2e-opencode.sh` で用意しています（認証が必要なため、未確認になる条件は [reports/lab-results.md](../reports/lab-results.md) に記録します）。
