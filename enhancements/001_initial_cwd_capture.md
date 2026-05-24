# ENH-001: 初期 CWD の捕捉とすべての出力先の固定

## ステータス

未着手

## 起票日

2026-05-23

## 種別

仕様追加

## 概要

`paths.output_dir() == Path.cwd()` が cwd 汚染で破綻している現状を、SKILL.md の dynamic injection で USER_CWD を捕捉 + 全コマンドで `--output-dir` 義務化 + pipeline 側のサニティチェック、の三層で防御する。

## 背景・動機

[BUG-001](../bugs/001_output_lands_in_skill_dir_not_cwd.md) の根本治療。plan §3.4 の最重要設計原則「成果物は CWD」を保証する仕掛けが現状なく、Skill 配下に成果物が出てユーザーが認識できないインシデントが manual_test で発生した。

中立サブエージェントレビュー (agent ID: a0c1cb76d84bde7b2) で以下が判明:

- 私が初稿で提案した `export INITIAL_CWD=$(pwd)` 方式は **Bash tool 呼び出しごとに独立プロセス**なので持続しない (= 不採用)
- `CLAUDE_PROJECT_DIR` は hook ドキュメントに記載があるが、Skill / Bash tool でも参照可能かは公式に明記なし (2026-05-23 時点)
- `${CLAUDE_SKILL_DIR}` は **string substitution** (テキスト置換) であり env として export されているかも未明記

このため、**公式に明記されている**機能 (`` !`<command>` `` による dynamic context injection) だけで設計する。

## 要件

- ユーザーが任意の CWD で `claude` を起動して Skill 経由で analyze したとき、`report_*.html` / `data_*.json` が **起動時の CWD** に確実に出る
- Skill 内部から cwd を変える操作 (cd 等) を排除
- 万が一サニティが破られても error で気付ける (silent に Skill 配下に出ない)
- 後方互換: `--output-dir` 明示指定は従来通り動く

## 影響範囲

- [scripts/paths.py](../skills/japan-stock-analysis/scripts/paths.py) `output_dir()`
- [scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) `cmd_analyze`
- [scripts/mapping_resolver.py](../skills/japan-stock-analysis/scripts/mapping_resolver.py) (新規 `--output-dir` 引数追加)
- [skills/japan-stock-analysis/SKILL.md](../skills/japan-stock-analysis/SKILL.md) §3.0 / §3.2 / §4 / §6
- [tests/test_paths.py](../skills/japan-stock-analysis/tests/test_paths.py) / [tests/test_pipeline.py](../skills/japan-stock-analysis/tests/test_pipeline.py) (テスト追加)

## 実現案

### 案1 (推奨): 三層防御 (dynamic injection + cd 撤廃 + サニティチェック)

#### 層1: SKILL.md 冒頭で USER_CWD を dynamic injection

```markdown
---
name: japan-stock-analysis
...
allowed-tools: Bash(python3 *) Bash(test *) Read
---

USER_CWD: !`pwd`

(以下、本文。Claude は USER_CWD を **リテラル文字列**として記憶し、後段の Bash 呼び出しで使う)
```

`` !`pwd` `` は SKILL.md ロード時にユーザーの shell で実行され、結果がリテラル展開された本文 が Claude に渡る (公式: "Dynamic context injection")。

#### 層2: SKILL.md §3.2 から cd を撤廃

```bash
# 旧 (cwd 汚染源)
cd ${CLAUDE_SKILL_DIR}
python3 -m venv env
env/bin/pip install -r requirements.txt

# 新 (cwd 汚染なし、全パス絶対化)
python3 -m venv ${CLAUDE_SKILL_DIR}/env
${CLAUDE_SKILL_DIR}/env/bin/pip install -r ${CLAUDE_SKILL_DIR}/requirements.txt
```

§4 / §6 の全コマンドテンプレに `--output-dir <USER_CWD-リテラル>` を必須化:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze \
  --sec-code 7203 \
  --output-dir <USER_CWD-リテラル>
```

#### 層3: pipeline.py に SKILL_ROOT 配下出力拒否のサニティチェック

```python
out = Path(args.output_dir).resolve() if args.output_dir else Path.cwd()
try:
    out.relative_to(paths.SKILL_ROOT)
except ValueError:
    pass  # outside SKILL_ROOT — OK
else:
    return _emit({
        "status": "error",
        "reason": (
            f"Refusing to write artifacts to {out}, which is inside the "
            f"Skill directory ({paths.SKILL_ROOT}). Pass --output-dir "
            "<user-cwd> explicitly. See SKILL.md §3 for the USER_CWD pattern."
        ),
    })
```

#### 補助: paths.output_dir() フォールバック順を明示化

```python
def output_dir() -> Path:
    """
    Priority:
      1. Caller-injected override (cmd_analyze --output-dir monkeypatch)
      2. JAPAN_STOCK_OUTPUT_DIR env var (escape hatch for ad-hoc users)
      3. Path.cwd() (last resort)
    """
    override = os.environ.get("JAPAN_STOCK_OUTPUT_DIR")
    if override and Path(override).is_dir():
        return Path(override)
    return Path.cwd()
```

公式 `CLAUDE_PROJECT_DIR` は仕様が固まったら優先候補に追加。

### 案2: 環境変数頼み (不採用)

`export INITIAL_CWD=$(pwd)` を Bash tool に投げる方式。中立レビューで **Bash tool は呼び出しごとに独立プロセスなので env は持続しない**と判明。不採用。

### 案3: company_map のような起動時カレントディレクトリ捕捉ファイル (不採用)

Skill 起動時に `cache/.user_cwd` のようなファイルを生成し、以降は参照。ファイル生成のタイミングと cwd 取得のタイミングが結局同じ問題に当たる。不採用。

## 検証済みの仕様前提

- ✅ Claude Code Agent Skills の dynamic context injection (`` !`<command>` ``) は SKILL.md ロード時にローカル shell で実行され、結果が**リテラル文字列として SKILL.md 本文に注入**される ([公式](https://code.claude.com/docs/en/skills) §"Inject dynamic context")
- ✅ `${CLAUDE_SKILL_DIR}` は string substitution であり Bash env として参照可能かは未明記 (同上 §"Available string substitutions")
- ⚠️ `CLAUDE_PROJECT_DIR` は hook 文脈 ([公式 hooks](https://code.claude.com/docs/en/hooks) "Reference scripts by path") のみ明記、Skill / Bash tool で見えるか不明
- ⚠️ Claude Code Bash tool の cwd / env が呼び出し間で持続するかは公式に未明記。実機検証は manual_test history.md L376 (正常) vs L3033 (異常) で「持続しない (はず) だが特定条件で漏れる」状態

## 実装前の追加調査事項

- [ ] 実機検証: SKILL.md に `` !`echo $CLAUDE_PROJECT_DIR` `` を入れて値が取れるか (将来仕様変更で `paths.output_dir()` のフォールバック順に追加可)
- [ ] 実機検証: SKILL.md の `` !`pwd` `` 出力タイミング (SKILL.md ロード時 vs 各 Bash 呼び出し時) を確認
- [ ] BUG-001 の真の引き金特定 (history L376→L3033 で何が cwd を変えたか)

## 想定される効果

- BUG-001 の根本治療 (案1 三層防御)
- 公式明記の機能のみ使うので壊れにくい
- silent な Skill 配下出力を error で気付ける

## 想定される副作用・リスク

- **既存テスト**: `tests/test_pipeline.py` 等は `paths.output_dir` を monkeypatch しているので、案1 の層3 サニティチェック追加で「`--output-dir` 指定済 + tmp_path` 構成」は影響なし。`--output-dir` 未指定で `Path.cwd()` が tmp_path/SKILL_ROOT 配下になるテストは要見直し
- **後方互換**: `--output-dir` は既存引数。`JAPAN_STOCK_OUTPUT_DIR` env var は新規だが optional
- **SKILL.md の `` !`pwd` `` 実行**: 1 回の pwd しかしないので副作用なし。Claude Code 環境以外で SKILL.md を読む場合 (例: GitHub 上で閲覧) はリテラル `!`pwd`` として表示される、これは仕様

## ロールバック手順

最小ロールバック (BUG-001 発生時点の挙動に戻す):
1. SKILL.md の `USER_CWD: !`pwd`` 行を削除
2. SKILL.md §3.2 を `cd ${CLAUDE_SKILL_DIR}` 方式に戻す
3. `pipeline.py` のサニティチェックブロックを `if False:` で無効化

部分維持 (副作用なし、残しても問題なし):
4. `mapping_resolver.py` の `--output-dir` 引数
5. `paths.py` の env var フォールバック

## 対応

<!-- AI instruction: 完了後に追記するセクション。採用した実現案、または独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- 親 bug: [BUG-001](../bugs/001_output_lands_in_skill_dir_not_cwd.md)
- 副次解決 bug: [BUG-008](../bugs/008_potential_report_commit_leakage.md) (gitignore 二重防御)
- plan: [plan.md §3.4](../plan.md)
- 設計議論: [QA_skill_invocation.md](../QA_skill_invocation.md)
- 公式仕様: [Claude Code Agent Skills](https://code.claude.com/docs/en/skills) §"Inject dynamic context" / §"Available string substitutions"
- 中立レビュー: subagent ID `a0c1cb76d84bde7b2` の指摘で初稿の前提誤りを修正
