# Enhancement: 初期 CWD の捕捉とすべての出力先の固定

- **提案日**: 2026-05-23
- **提案経緯**: manual_test で発覚した CWD バグの根治
- **影響範囲**: SKILL.md / pipeline.py / mapping_resolver.py の出力場所
- **優先度**: **P0**（[bugs/2026-05-23_output_lands_in_skill_dir_not_cwd.md](../bugs/2026-05-23_output_lands_in_skill_dir_not_cwd.md) の根本治療）

## 動機

[bugs/2026-05-23_output_lands_in_skill_dir_not_cwd.md](../bugs/2026-05-23_output_lands_in_skill_dir_not_cwd.md) で発覚した通り、`paths.output_dir() == Path.cwd()` は **Claude が途中で `cd` を打つと変わってしまう**。Skill 設計の根幹である「成果物は CWD に落とす」(plan §3.4) を保証できない。

これは「Claude が cd しないようにする」だけでは不十分。複合 Bash コマンド、background プロセス、人間の手動操作など、cwd が変わる経路は多数ある。**設計レベルで `INITIAL_CWD` を捕捉して以降固定**するのが正攻法。

## 現状の挙動

[scripts/paths.py:output_dir()](../skills/japan-stock-analysis/scripts/paths.py):
```python
def output_dir() -> Path:
    return Path.cwd()
```

呼ばれた時点の cwd を返す。複数回呼ばれる間に cwd が変わると別の場所を指す可能性すらある。

[scripts/pipeline.py:cmd_analyze](../skills/japan-stock-analysis/scripts/pipeline.py):
```python
if args.output_dir:
    forced = Path(args.output_dir).resolve()
    forced.mkdir(parents=True, exist_ok=True)
    paths.output_dir = lambda: forced  # monkeypatch
```

`--output-dir` 指定時のみ固定。指定なしは `Path.cwd()` に依存。

## 提案する変更

### 変更1: SKILL.md §3 冒頭で `INITIAL_CWD` 環境変数を確立

SKILL.md の Claude 向け手順を改訂:

```markdown
## 3. 環境準備

### 3.0 INITIAL_CWD の捕捉 (最重要)

Skill が成果物を CWD に正しく出すため、Claude は **すべての作業の最初**
に現在の作業ディレクトリを変数として固定する:

\`\`\`bash
export INITIAL_CWD=$(pwd)
\`\`\`

以降のすべての analyze / mapping_resolver / cache_admin 呼び出しでは
`--output-dir "$INITIAL_CWD"` を渡す（**例外なく**）。

### 3.1 secret.json 存在チェック (変更なし)
...

### 3.2 venv と依存 (cd を撤廃)

\`\`\`bash
python3 -m venv "${CLAUDE_SKILL_DIR}/env"
"${CLAUDE_SKILL_DIR}/env/bin/pip" install -r "${CLAUDE_SKILL_DIR}/requirements.txt"
\`\`\`

`cd ${CLAUDE_SKILL_DIR}` は **使用しない**（cwd 汚染を避けるため）。
```

### 変更2: paths.output_dir() を環境変数優先に

```python
import os
from pathlib import Path

def output_dir() -> Path:
    """Resolve the artifact output directory.

    Priority:
      1. Caller monkeypatch (pipeline cmd_analyze --output-dir)
      2. INITIAL_CWD env var set by SKILL.md §3.0
      3. Path.cwd() (fallback)
    """
    override = os.environ.get("INITIAL_CWD")
    if override and Path(override).is_dir():
        return Path(override)
    return Path.cwd()
```

これにより:
- SKILL.md の手順通り `export INITIAL_CWD=$(pwd)` した場合: 確実にユーザー CWD に出る
- 手動で python を直接叩いた場合: 従来通り Path.cwd() で動く（後方互換）
- pipeline `--output-dir` 明示時: 引数優先（既存挙動）

### 変更3: SKILL.md §4 / §6 のコマンドテンプレを全て `--output-dir "$INITIAL_CWD"` 付き化

```markdown
## 4.1 基本フロー

\`\`\`bash
${CLAUDE_SKILL_DIR}/env/bin/python3 \\
  ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze \\
  --sec-code <code> \\
  --output-dir "$INITIAL_CWD"
\`\`\`
```

mapping_resolver / cache_admin にも同様の `--output-dir` を追加（mapping_escalation_*.json の出力先に効く）。

### 変更4: pipeline.py 起動時のサニティチェック

```python
def cmd_analyze(args):
    ...
    out = paths.output_dir()
    if str(out).startswith(str(paths.SKILL_ROOT)):
        # 想定外: Skill 配下に出力されようとしている
        return _emit({
            "status": "error",
            "reason": (
                f"output_dir() resolved to {out} which is inside the Skill "
                "directory. This usually means INITIAL_CWD was not captured "
                "before invocation. See SKILL.md §3.0."
            ),
        })
```

これで万が一手順を忘れても**サイレントに Skill 配下に出力する**ことだけは防げる。

## 想定される効果

- bugs/2026-05-23_output_lands_in_skill_dir_not_cwd.md の根本治療
- ユーザーが期待する場所に確実に成果物が出る
- 同じ問題の再発防止（サニティチェック）

## 想定される副作用・リスク

- 既存テストへの影響: test_pipeline.py / test_html_report.py / test_json_export.py が `paths.output_dir` を monkeypatch しているため、`INITIAL_CWD` を考慮した assertion が必要かも（おそらく monkeypatch が優先されるので影響なし）
- ユーザーが SKILL.md を読まずに直接 python を叩くケース: `INITIAL_CWD` 未設定だと従来通り `Path.cwd()` フォールバック → 既存動作維持
- サニティチェックで `error` を返すケース: 利便性のため `warning` レベルにする選択肢もある

## 実装の見積もり

- 難易度: 小〜中
- 影響ファイル:
  - [scripts/paths.py](../skills/japan-stock-analysis/scripts/paths.py)（1関数）
  - [scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py)（サニティチェック追加）
  - [scripts/mapping_resolver.py](../skills/japan-stock-analysis/scripts/mapping_resolver.py)（`--output-dir` 引数追加）
  - [skills/japan-stock-analysis/SKILL.md](../skills/japan-stock-analysis/SKILL.md)（§3.0 追加、§3.2 修正、§4 / §6 テンプレ更新）
- 追加テスト:
  - `test_paths.py` に `INITIAL_CWD` 環境変数優先のテスト
  - `test_pipeline.py` にサニティチェックの assertion テスト

## 関連

- 関連 bug: [bugs/2026-05-23_output_lands_in_skill_dir_not_cwd.md](../bugs/2026-05-23_output_lands_in_skill_dir_not_cwd.md)
- 元の設計: [plan.md §3.4](../plan.md)、[QA_skill_invocation.md](../QA_skill_invocation.md)
- 公式仕様参照: Claude Code Agent Skills `${CLAUDE_SKILL_DIR}` の慣習
