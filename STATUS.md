# 進捗

| 項目 | 内容 |
|---|---|
| 状態 | ラボ全テスト成功 → 文書作成済み → GitHub公開作業中（2026-11-06） |
| projectId | `mcp:e23a06ba-6c0a-472f-8d19-2f3823e14e2e` |
| workspaceRoot | `C:/Prj/nagi-projects/agent-harness-starter-kit` |
| 担当スレッド | Luna｜ハーネス初心者スターターキット `mcp:launch:42db55becccc97175d7ee495d6be12a827fdb4288b678a7787e9c4702dbe87b5` |
| モデル | 予定 codex/gpt-6-luna（max）→ 利用上限で失敗。チーフが途中まで実施 → ユーザー指示で glm-zai / glm-5.3[1m] へ引継ぎ（2026-11-06） |
| 起動前の確認 | はい（t3_project_read、執務室と別） |
| 起動後の照合 | はい（projectId一致、worktreePath=null） |
| 成果物・検証結果 | 下記 |

## チーフが実施済み（2026-11-06）
- 公式仕様の確認 → `docs/spec-notes.md`
- 判定スクリプト `guard/agent_guard.py`（＋ `trash.py`、`checkpoint.py`、`policy.json`）、インストーラー `install.py`
- 各ツールの設定テンプレート：`claude-code/template/`、`codex/template/`、`antigravity/template/`（＋ `settings.example.json`）、`opencode/template/`
- 単体テスト `tests/test_agent_guard.py`：Windows で 29件 OK
- Podman マシン `harness-kit-lab` 作成、イメージ `localhost/harness-kit-lab:1.0` ビルド、`lab/*.sh` 作成、1回目ログ `reports/lab-run-1.log`

## 担当（GLM 5.3）が実施（2026-11-06）
1. ラボの不具合修正
   - `lab/accident-tests.sh`：暴走テストを本体コンテナから削除（`pkill` が `sleep infinity` を止める事故の再発防止）。コメントで経緯を記録
   - `lab/run-lab.sh`：暴走テストを `podman run --rm --pids-limit=64` の使い捨てコンテナで実装。T3チェックを明示的な PASS/FAIL に修正（失敗が黙るバグを修正）
   - `lab/Containerfile`：apt に `libatomic1` を追加（t3 が必要）
2. ラボ再実行 → `reports/lab-run-2.log`、結果まとめ `reports/lab-results.md`
   - **26チェックすべて PASS（事故テスト 20/20、ホスト側 6/6）、終了コード0**
   - e2e：OpenCode 無料モデル（opencode/big-pickle）が `rm -rf docs`・`git push` を試み → プラグインが両方阻止、docs/ 残存、監査ログに記録
   - T3：`t3 serve` が port 3773 で応答（libatomic1 修正で解決）
3. 文書：`README.ja.md`（初心者向け・mermaid図入り）、`README.md`（英語）、各ツール `README.ja.md`（4件）、`LICENSE`（MIT/Sunwood-ai-labs）、`.gitignore`、`.github/workflows/ci.yml`（ubuntu+windows で単体テスト）
4. `__pycache__` を git 管理から除外（.gitignore 追加に伴う）

## 追加実施（2026-11-06・実エージェントe2e、チーフ指示）
- チーフがコンテナ `harness-kit-agent` 内にのみログイン情報を配置（`.claude/.credentials.json`、`.codex/auth.json`、dev/600）。表示・複製・ログ出力・コンテナ外持ち出しなし
- `lab/e2e-claude.sh`（新規）：実 `claude -p`（acceptEdits、プロジェクト信頼）で6依頼 → **6/6 PASS**（判定ログ＋ファイル状態の両方で判定）。bubblewrap サンドボックスも cap-drop コンテナ内で動作
- `lab/e2e-codex.sh`（新規）：`codex exec --dangerously-bypass-hook-trust` → **未確認（usage limit、11/8 23:22 解除後 `bash lab/e2e-codex.sh` で再実行）**。Hook読み込み（SessionStart起動）は観測済み
- `lab/run-lab.sh` に `LAB_E2E_CLAUDE=1` / `LAB_E2E_CODEX=1` を接続（ログイン情報が無い環境では自動スキップ）
- 実測仕様を `docs/spec-notes.md` に記録：Claude Code は明示的 deny 規則を PreToolUse Hook より先に評価／`-p` では ask は実行されない／codex 0.163 に `trustlevel` キー無し
- README.ja.md／README.md／lab-results.md／final-report.md 更新（認証情報取り扱いの注意を含む）

## 次の作業
- Codex e2e の再実行（11/8 23:22 以降、usage limit 解除後）と `SessionStart Failed` の調査
- それ以外はなし（完了）

## 最終報告と残る問題（2026-11-06）
- **公開URL：https://github.com/Sunwood-ai-labs/agent-harness-starter-kit**（public、MIT）
- **CI：成功**（run 42195434486、ubuntu-latest ✓ / windows-latest ✓。1回目の失敗=Linux限定のテスト環境依存を修正のうえ再push）
- **ラボ：事故テスト 20/20＋ホスト側 6/6 すべて PASS、FAIL 0**。実エージェントe2eは **Claude Code 6/6 PASS**・OpenCode PASS・Codex 未確認（usage limit）。T3 `t3 serve` 応答
- **単体テスト：30件 OK**（/tmp例外の再発防止テストを1件追加）
- 未確認：Claude Code / Codex / Antigravity のエージェント本体でのHook発火（認証・IDEのため。入力JSONでの検証に代替）、T3のブラウザペアリング（ユーザー操作）→ `reports/final-report.md` 4節
- 詳細：`reports/final-report.md`、`reports/lab-results.md`
- 後片付け：ラボの後始末は `lab/run-lab.sh --clean`（コンテナ・ボリューム削除）。マシン `harness-kit-lab` は残置
