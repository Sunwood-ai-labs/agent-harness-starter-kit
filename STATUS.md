# 進捗

| 項目 | 内容 |
|---|---|
| 状態 | 担当をGLM 5.3へ引継ぎ（2026-11-06） |
| projectId | `mcp:e23a06ba-6c0a-472f-8d19-2f3823e14e2e` |
| workspaceRoot | `C:/Prj/nagi-projects/agent-harness-starter-kit` |
| 担当スレッド | Luna｜ハーネス初心者スターターキット `mcp:launch:42db55becccc97175d7ee495d6be12a827fdb4288b678a7787e9c4702dbe87b5` |
| モデル | 予定 codex/gpt-6-luna（max）→ 利用上限（11/9まで）で失敗。チーフが途中まで実施 → ユーザー指示で glm-zai / glm-5.3[1m] へ引継ぎ |
| 起動前の確認 | はい（t3_project_read、執務室と別） |
| 起動後の照合 | はい（projectId一致、codex/gpt-6-luna、worktreePath=null） |
| 成果物・検証結果 | |

## チーフが実施済み（2026-11-06）
- 公式仕様の確認 → `docs/spec-notes.md`
- 判定スクリプト `guard/agent_guard.py`（＋ `trash.py`、`checkpoint.py`、`policy.json`）、インストーラー `install.py`
- 各ツールの設定テンプレート：`claude-code/template/`、`codex/template/`、`antigravity/template/`（＋ `settings.example.json`）、`opencode/template/`
- 単体テスト `tests/test_agent_guard.py`：Windows で 29件 OK（`python -m unittest discover -s tests`）
- Podman マシン `harness-kit-lab` 作成済み。イメージ `localhost/harness-kit-lab:1.0` ビルド済み（claude 2.1.309 / codex 0.163.0 / opencode 1.19.4 / t3 0.1.2）
- `lab/run-lab.sh`、`lab/accident-tests.sh`、`lab/e2e-opencode.sh` 作成。1回目の実行ログ `reports/lab-run-1.log`

## 1回目のラボ実行で見つかった不具合（未修正）
1. `lab/accident-tests.sh` のプロセス暴走テストの後始末 `pkill -u "$(id -u)" sleep` が、コンテナの本体プロセス `sleep infinity` まで止めてしまい、コンテナが停止 → 結果表が出ず、以降の exec がすべて失敗。暴走テストは使い捨ての別コンテナ（`podman run --rm --pids-limit=...`）で行うか、自分で起動した子プロセスだけを止める形に直す。
2. T3 コンテナ：`t3` が `libatomic.so.1` を必要とする → `lab/Containerfile` の apt に `libatomic1` を追加。
3. ネットワーク遮断テスト（`--network none` で POST 失敗）は PASS 済み。

## 次の作業
- 上の不具合を直してラボを再実行し、全テストの結果を `reports/lab-results.md` にまとめる（実行コマンド、実出力）。
- README.ja.md（初心者向け・図入り）、README.md（英語）、各ツールの README、LICENSE（MIT）、`.gitignore`、GitHub Actions CI（ubuntu と windows で単体テスト）。
- `gh repo create Sunwood-ai-labs/agent-harness-starter-kit --public` で公開、push、CI 成功を確認。
- `reports/final-report.md` を書く。

## 最終報告と残る問題
