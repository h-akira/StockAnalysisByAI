# BUG-003: PER NaN の warning メッセージが「5 年窓外」と誤った原因を示す

## ステータス

未修正

## 発見日

2026-05-23

## 概要

restated EPS が一切取れない場合 ([BUG-002](002_jgaap_per_always_nan.md) のケース) でも、warning が「5 年窓外」と表示される。原因と表示が乖離しているため、ユーザーが本当の原因を究明できない。

## 症状

- 9531 JGAAP を analyze すると warnings に全 10 期が「PER is NaN for periods outside the latest report's restated EPS coverage (5-year window)」と表示される
- 実態は restated_eps が空辞書 `{}` で、5 年窓内の最新 5 期も値が無い
- 「5 年窓外」だけ見たユーザーは「過去 10 年中 5 年は出るはず」と誤認する

## 原因

[scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) の warning 生成ロジックが `restated_eps` の空・一部欠落を区別していない。常に「5 年窓外」フォーマットで出している。

## 影響範囲

- 影響銘柄: JGAAP 銘柄全般 (BUG-002 と同じ条件) + restated EPS 抽出失敗時すべて
- 該当ファイル: [scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) warning 文字列生成

## 再現手順

1. JGAAP 銘柄を analyze: `python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 9531`
2. stdout JSON の `warnings[]` を確認、「outside the latest report's restated EPS coverage (5-year window)」が**全期に対して**出ている

## 修正案

### 案1 (推奨): restated_eps の空・部分欠落を区別

```python
if not split_adjust.restated_eps:
    warnings.append(
        "split_adjust returned no restated EPS at all. "
        "PER will be NaN for all periods. "
        "Likely cause: latest report's XBRL taxonomy lacks the elements "
        "probed in EPS_SUMMARY_ELEMENTS (see BUG-002 for JGAAP case)."
    )
elif missing_periods:
    warnings.append(
        f"PER is NaN for periods outside the restated EPS window: {missing_periods}."
    )
```

ENH-002 (JGAAP EPS fallback) 実装と同時に対応するのが効率的。

## 対応

<!-- AI instruction: 修正完了後に追記するセクション。採用した修正案、または修正案にない独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- 親 bug: [BUG-002](002_jgaap_per_always_nan.md)
- 解決 enhancement: [ENH-002](../enhancements/002_jgaap_eps_summary_fallback.md) (warning 改善も同 enhancement で扱う)
