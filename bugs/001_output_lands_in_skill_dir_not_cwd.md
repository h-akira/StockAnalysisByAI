# BUG-001: HTML/JSON 出力先が CWD ではなく Skill 配下になる

## ステータス

未修正

## 発見日

2026-05-23

## 概要

`paths.output_dir() == Path.cwd()` 依存のため、Skill 実行途中で何らかの経路で cwd が Skill 配下に変わると、レポートが意図しない場所に落ちる。init_plan.md §3.4 の最重要設計原則 (成果物は CWD) が守れていない。

## 症状

- ユーザーの起動 cwd が `manual_test/` だったにも関わらず、`report_9531.html` が `manual_test/.claude/skills/japan-stock-analysis/` に出力された
- ユーザーには「JSON だけ出て HTML が出ない」と認識された（実際は HTML も出ていたが Skill 配下にあって気付かなかった）
- 同じ session 内でも `cache_admin info` 時には `output_dir: .../manual_test` で正しく動いていた (history.md L376)。後段の pipeline analyze 時 (L3033) に Skill 配下に出力された

## 原因

確証なし。**強い仮説**:

- `scripts/paths.py:output_dir()` が `Path.cwd()` を返すだけで、cwd 変更に対する防御がない
- `Bash` ツールでの `&&` チェーン (`cd ${CLAUDE_SKILL_DIR} && python3 -m venv env && ...`) や同等の cd を含む複合コマンドが cwd を変えた可能性
- ただし Claude Code Bash tool は呼び出しごとに独立プロセスのはずなので、cwd が次の呼び出しに持ち越されない仕様 / されている仕様が公式に明記されておらず、確証なし

## 影響範囲

- [scripts/paths.py](../skills/japan-stock-analysis/scripts/paths.py) `output_dir()`
- [scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) `cmd_analyze`
- [scripts/json_export.py](../skills/japan-stock-analysis/scripts/json_export.py) `write_data_json`
- [scripts/html_report.py](../skills/japan-stock-analysis/scripts/html_report.py) `render_report`
- [scripts/mapping_resolver.py](../skills/japan-stock-analysis/scripts/mapping_resolver.py) `build_escalation_payload`
- 影響銘柄: すべて (条件次第)

## 再現手順

1. 任意の作業ディレクトリに Skill を配置 (`~/work/proj/.claude/skills/japan-stock-analysis/`)
2. `cd ~/work/proj` してから `claude` を起動
3. claude 内で「7203 を分析して」と依頼
4. Skill 経由で SKILL.md §3.2 venv セットアップが走り、その後 pipeline.py analyze が走る
5. `~/work/proj/.claude/skills/japan-stock-analysis/` 配下に成果物が出るのを確認 (期待: `~/work/proj/`)

## 修正案

### 案1: dynamic injection で USER_CWD 捕捉 + 全コマンドに --output-dir 義務化

[enhancements/001_initial_cwd_capture.md](../enhancements/001_initial_cwd_capture.md) を参照。SKILL.md 冒頭で `` !`pwd` `` で USER_CWD を文字列展開、後段の全 Bash 呼び出しで `--output-dir <USER_CWD>` を明示。

### 案2: pipeline.py に「SKILL_ROOT 配下出力拒否」サニティチェック

`cmd_analyze` 冒頭で `out.relative_to(paths.SKILL_ROOT)` が成功 (= 配下) なら error を返す防御層。案1 の最後の砦。

### 案3 (推奨): SKILL.md §3.2 から cd 撤廃 + 案1 + 案2 の三層防御

絶対パスで venv 操作 (`python3 -m venv ${CLAUDE_SKILL_DIR}/env`)、案1で正常系を担保、案2 で異常系を防御。

## 対応

<!-- AI instruction: 修正完了後に追記するセクション。採用した修正案、または修正案にない独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- 解決 enhancement: [ENH-001](../enhancements/001_initial_cwd_capture.md)
- 関連 bug: [BUG-008](008_potential_report_commit_leakage.md) (二重防御として gitignore も検討)
- plan: [init_plan.md §3.4 パス解決方針](../init_plan.md)
- 設計議論: [tmp/QA_skill_invocation.md](../tmp/QA_skill_invocation.md)
- 観測ログ: `manual_test/history.md` L376 (cache_admin info 時は CWD 正常) と L3033-3066 (pipeline 時 Skill 配下)
- 検証環境: Skill commit `c8e0453` 付近、Python 3.14.3、macOS 14
