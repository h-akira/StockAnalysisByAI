# Bug: HTML/JSON 出力先が CWD ではなく Skill 配下になる

- **発見日**: 2026-05-23
- **発見シーン**: ユーザーによる manual_test (`/Users/hakira/Programs/501_Finance/FinanceSource/manual_test/` で `claude` 起動 → 9531 東京ガス分析)
- **影響範囲**: Skill が動くすべての analyze 実行（条件次第）
- **重大度**: **P0**（ユーザーに「JSON だけ出て HTML が出ない」と誤認させた / plan §3.4 の最重要設計原則違反）
- **再現性**: SKILL.md §3.2 の `cd ${CLAUDE_SKILL_DIR}` を実行し、その後で cd を戻さずに pipeline を呼ぶと再現

## 症状

ユーザーが想定する出力場所（CWD = ユーザーの作業ディレクトリ、例 `manual_test/`）ではなく、**Skill 配下** (`manual_test/.claude/skills/japan-stock-analysis/`) に `report_*.html` と `data_*.json` が落ちる。

ユーザー報告:
> 現在出力はjsonだけだった。htmlなどにレポートは出なかったがどういうことか？

実態は HTML も出ているが、想定外の場所（Skill 配下）にあるので「ない」と認識された。

## 再現手順

```bash
# 1. 任意の作業ディレクトリに Skill を配置
mkdir -p ~/work/manual_test/.claude/skills
cp -r ~/path/to/skill ~/work/manual_test/.claude/skills/japan-stock-analysis

# 2. claude を起動
cd ~/work/manual_test
claude

# 3. claude 内で「7203 を分析して」と依頼
# SKILL.md §3.2 の手順に従い、Claude が venv 作成のため:
#    cd ${CLAUDE_SKILL_DIR}
#    python3 -m venv env
#    env/bin/pip install ...
# を実行する。その後 cd を戻さずに pipeline を呼ぶと CWD = Skill 配下に。

# 4. その後の analyze 実行
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 7203

# → report_7203.html / data_7203.json が ${CLAUDE_SKILL_DIR}/ に出る
#    （期待: ~/work/manual_test/ に出る）
```

## 期待される挙動

plan.md §3.4 で明確:

> 成果物の出力先 = 現在の作業ディレクトリ。
> Claude実行時のCWDは「ユーザーがそのプロジェクトで作業中のディレクトリ」になる前提。

つまり `~/work/manual_test/report_7203.html` が正しい配置。

## 実際の挙動

`~/work/manual_test/.claude/skills/japan-stock-analysis/report_7203.html` に出力された。

実際の出力（history.md より）:
```json
"outputs": {
  "html": "/Users/hakira/Programs/501_Finance/FinanceSource/manual_test/.claude/skills/japan-stock-analysis/report_9531.html",
  "data_json": {
    "9531": "/Users/hakira/Programs/501_Finance/FinanceSource/manual_test/.claude/skills/japan-stock-analysis/data_9531.json"
  }
}
```

ユーザーの Working Directory は `~/manual_test/` だったので、ここに出るべきだった。

## 根本原因

`scripts/paths.py:output_dir()` は `Path.cwd()` を返す:

- [scripts/paths.py:33-39](../skills/japan-stock-analysis/scripts/paths.py#L33-L39)
- [scripts/json_export.py:write_data_json](../skills/japan-stock-analysis/scripts/json_export.py)
- [scripts/html_report.py:render_report](../skills/japan-stock-analysis/scripts/html_report.py)

`Path.cwd()` はプロセス起動時の OS の cwd を返す。Claude (Agent) が `Bash` ツールで `cd ${CLAUDE_SKILL_DIR} && env/bin/python3 ...` のような複合コマンドを打つと、その Bash プロセスの cwd が Skill 内になり、結果として python の `Path.cwd()` も Skill 内になる。

SKILL.md §3.2 が原因の一つ:
```
## 3.2 venv と依存
初回のみ:
    cd ${CLAUDE_SKILL_DIR}
    python3 -m venv env
    env/bin/pip install -r requirements.txt
```

この `cd ${CLAUDE_SKILL_DIR}` を Claude が同じ Bash セッションで実行すると、後続のすべてのコマンドが Skill 配下から動く。

さらに、Claude Code の Bash ツールはコマンドごとに独立した Bash プロセスを起動するはず（持続セッションではない）が、history を見ると複数コマンドが `&&` でチェーンされており、その中の `cd` が後続に影響を与えるケースは確実にある。

## 修正案

3 つのアプローチがある。**併用が望ましい**:

### 案1: paths.output_dir() を環境変数で上書き可能に

`output_dir()` が `CLAUDE_USER_CWD` のような環境変数を優先するように:

```python
def output_dir() -> Path:
    override = os.environ.get("JAPAN_STOCK_OUTPUT_DIR")
    if override:
        return Path(override)
    return Path.cwd()
```

SKILL.md 側で「Claude は実行前に `export JAPAN_STOCK_OUTPUT_DIR=$(pwd)` を打つ」と指示する。ただし `pwd` 取得自体がもう Skill 配下の cwd で動くと意味がない。

### 案2: pipeline.py --output-dir をデフォルトで「親 cwd を捕捉」モードにする

既に `--output-dir` 引数は存在する ([scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py))。SKILL.md §4.1 で **Claude が必ず `--output-dir $(pwd)` を渡す**よう義務化。ただし上と同じ問題（pwd の取得タイミング）。

**ベターな実装**:
- SKILL.md 冒頭で `INITIAL_CWD` 変数を定義し、その後のすべてのコマンドで `--output-dir $INITIAL_CWD` を使う
- もしくは Claude Code が提供する `${CLAUDE_PROJECT_DIR}` のような環境変数（要調査）を使う

### 案3: SKILL.md §3.2 から cd を撤廃

`cd ${CLAUDE_SKILL_DIR}` の代わりに絶対パスで venv 操作:

```bash
python3 -m venv ${CLAUDE_SKILL_DIR}/env
${CLAUDE_SKILL_DIR}/env/bin/pip install -r ${CLAUDE_SKILL_DIR}/requirements.txt
```

これだけでも cwd 汚染は起きない。**最も低コストかつ確実な修正**。案2と併用すべき。

### 推奨

1. **即時**: 案3（SKILL.md §3.2 から cd 撤廃）
2. **次に**: 案2（`--output-dir` 義務化、または `CLAUDE_PROJECT_DIR` 等の調査）
3. **保険**: 案1 のような環境変数オーバーライド機能

加えて、SKILL.md §7「出力の解釈」で Claude がユーザーへ提示するファイルパスを **必ず確認**するよう注意書きを足す（パスが Skill 配下だったら警告する）。

## 関連

- 関連 enhancement: [enhancements/2026-05-23_initial_cwd_capture.md](../enhancements/2026-05-23_initial_cwd_capture.md)
- 元の設計: [plan.md §3.4 パス解決方針](../plan.md)
- 公式仕様: [QA_skill_invocation.md](../QA_skill_invocation.md)
