# 仕様メモ（2026-11-06 時点の公式ドキュメント）

このキットの設定は、下の公式ドキュメントで確認した仕様に合わせています。ツールの更新で変わることがあるので、導入前に読み直してください。

## まとめ：4ツールの違い

| 機能 | Claude Code | Codex | Antigravity | OpenCode |
|---|---|---|---|---|
| 実行前Hook | `PreToolUse` | `PreToolUse` | `PreToolUse` | プラグインの `tool.execute.before` |
| Hookから止める | `deny` | `deny`（または終了コード2） | `deny` | 例外を投げる |
| Hookから承認画面を出す | `ask` | **できない**（`ask` は失敗扱いになり、操作はそのまま実行される） | `ask` / `force_ask` | **できない**（権限設定の `ask` を使う） |
| 権限設定での承認 | `permissions.ask` | `approval_policy` | Ask リスト | `permission` の `ask` |
| サンドボックス | `sandbox.enabled`（macOS、Linux、WSL2。Windows本体は非対応） | `sandbox_mode = "workspace-write"` | Default プリセット（Linux、macOS、Windows 11 24H2以降） | なし（シェルは利用者の権限で動く） |
| Hookの有効化 | 設定ファイルに書けば動く | **`/hooks` で信頼（trust）が必要**。プロジェクトも信頼が必要 | 設定ファイルに書けば動く | プラグインを置けば起動時に読む |
| 作業前に動くHook | `SessionStart` | `SessionStart` | `SessionStart` | — |

## 会話で出た内容との違い

| 会話での説明 | 公式ドキュメントでの確認結果 |
|---|---|
| Codexの `ask` は非対応 | 正しい。さらに、`ask` を返すとHookは「失敗」扱いになり、**操作は止まらずに続く**。このキットはCodexでは確認が必要な操作も `deny` にする |
| Codexの設定は `~/.codex/hooks.json` | 正しい。プロジェクトの `.codex/hooks.json` と `config.toml` の `[hooks]` も使える。ただしプロジェクトのHookは、プロジェクトを信頼したときだけ読み込まれ、Hookごとに `/hooks` での信頼も必要 |
| Antigravityの設定は `.agents/hooks.json`、グローバルは `~/.gemini/config/hooks.json` | 正しい。最上位は「Hookの名前 → イベント」の形（`"hooks"` キーは無い） |
| Antigravityの判定は allow / deny / ask / force_ask / deny_unless_prior_grant | 正しい。ほかに `auto_approve` がある。`allow` は通常の権限判定へ進むだけで、許可を強制しない |
| Antigravityのコマンドは `toolCall.args.CommandLine` | 正しい |
| OpenCodeの `permission` は ask/deny を使える | 正しい。複数のパターンに当てはまるときは**最後に書いたルール**が優先される。`--auto` は `ask` を自動で許可するが、`deny` は守られる |
| OpenCode 2系は形式が違う | 公式のpermissionsページには2系専用の形式は書かれていない（`experimental.policies` だけ2系専用）。このキットは1系（1.19）で確認した |
| Claude Codeは `ask` で承認画面を出せる | 正しい。`PreToolUse` は権限モードより先に動くので、`bypassPermissions` でも `deny` は破られない。終了コード0〜2以外のエラーでは操作が続く |

## 出典

- Claude Code: https://code.claude.com/docs/en/hooks.md 、https://code.claude.com/docs/en/permissions.md 、https://code.claude.com/docs/en/sandboxing.md 、https://code.claude.com/docs/en/managed-settings.md
- Codex: https://learn.chatgpt.com/docs/hooks 、https://learn.chatgpt.com/docs/config-file/config-reference 、https://learn.chatgpt.com/docs/sandboxing （developers.openai.com/codex/... から転送）
- Antigravity: https://antigravity.google/docs/hooks 、https://antigravity.google/docs/permissions 、https://antigravity.google/docs/sandbox
- OpenCode: https://opencode.ai/docs/permissions 、https://opencode.ai/docs/plugins 、https://opencode.ai/docs/config 、https://opencode.ai/docs/cli/

## 未確認のこと

- Antigravity のHookが失敗したとき（終了コード、時間切れ、JSONの誤り）の扱いは公式に書かれていない。このキットの判定スクリプトは、内部エラーのとき `deny` を返す。
- Antigravity でファイルを書くツールの正式な名前と引数名。判定スクリプトは、名前に `path` や `file` を含む引数をすべて調べる。
- Codex の `network_access` は設定リファレンスには載っているが、サンドボックスのページには書かれていない。
