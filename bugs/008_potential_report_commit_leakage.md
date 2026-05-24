# BUG-008: Skill 配下に出力されたレポートが gitignore で除外されない可能性 (調査・予防)

## ステータス

未修正

## 発見日

2026-05-23

## 概要

[BUG-001](001_output_lands_in_skill_dir_not_cwd.md) で `report_*.html` / `data_*.json` が Skill 配下に出力されるケースがあるが、`skills/japan-stock-analysis/.gitignore` が `cache/` / `env/` / `__pycache__/` しか除外していないため、誤って `git add .` した場合に 5MB の HTML が commit に紛れる可能性がある。

## 症状

(まだ実発生は観測されていない、予防的記録)

```bash
cd skills/japan-stock-analysis/
ls report_*.html data_*.json 2>/dev/null      # BUG-001 で発生した場合に存在
git check-ignore report_9531.html              # 期待: 何も出ない (= ignore されない)
```

## 原因

[skills/japan-stock-analysis/.gitignore](../skills/japan-stock-analysis/.gitignore) の現状:
```
secret.json
cache/
env/
.venv/
__pycache__/
*.pyc
*.pyo
.pytest_cache/
```

`report_*.html`、`data_*.json`、`mapping_escalation_*.json` が除外対象に入っていない。これらは init_plan.md §3.4 上「Skill 配下に出るべきでない」ファイルなので gitignore 不要という設計判断だったが、BUG-001 が現に起きた以上、二重防御として gitignore で守るべき。

## 影響範囲

- 影響: BUG-001 発生時のみ (BUG-001 修正後でも、手動操作で Skill 配下に出すケース対策)
- 該当ファイル: [skills/japan-stock-analysis/.gitignore](../skills/japan-stock-analysis/.gitignore)

## 再現手順

1. BUG-001 を再現して Skill 配下に `report_*.html` を出す
2. `cd skills/japan-stock-analysis && git status` で untracked に出ることを確認
3. `git check-ignore report_xxxx.html` で何も出ない (= ignore されない) ことを確認

## 修正案

### 案1 (推奨): .gitignore に追加

```gitignore
# Defense in depth: BUG-001 や手動操作で誤って Skill 配下に成果物が出ても commit されないように
report_*.html
data_*.json
mapping_escalation_*.json
mapping_*.json
```

ただし `mapping_*.json` は SKILL.md §6 で「Claude が組み立てるマッピング JSON」を指すことがあり、ユーザーの手元 (CWD) に置く想定だが、誤って Skill 配下に置かれる可能性もある。慎重には外しても良い。

### 案2: BUG-001 修正で十分とする

BUG-001 の修正で根本治療されるなら gitignore 追加は不要、という判断もあり得る。ただし防御は多層化すべき。

## 対応

<!-- AI instruction: 修正完了後に追記するセクション。採用した修正案、または修正案にない独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- 親 bug: [BUG-001](001_output_lands_in_skill_dir_not_cwd.md)
