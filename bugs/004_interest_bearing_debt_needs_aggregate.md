# BUG-004: InterestBearingDebt 集計が複数要素加算を要するケースが多発 (mapping 単一要素縛りで対応不能)

## ステータス

未修正

## 発見日

2026-05-23

## 概要

mapping の `extra_mappings` が「1 項目 = 1 要素」しか扱えないため、`BondsAndBorrowingsCLIFRS + BondsAndBorrowingsNCLIFRS` のような複数要素加算が必要な銘柄で IBD を取得できない (近似値か unresolved にするしかない)。

## 症状

- 4502 武田: IBD が `BondsAndBorrowingsCLIFRS` (549B) + `BondsAndBorrowingsNCLIFRS` (3.97T) の 2 要素合算で 4.5 兆円となるはずだが、mapping で表現できず unresolved にした
- 9531 東京ガス: IBD が `BondsPayable` + `LongTermLoansPayable` + `ShortTermLoansPayable` + `CurrentPortion` の 4 要素合算が必要だが unresolved
- 8306 MUFG: IBD は `Deposits` 単独で近似マッピング (本来は預金 + NCDs + 借入金 + 社債の複合)
- 結果として該当銘柄の `data_*.json` の `financials.InterestBearingDebt` が null になる

## 原因

[scripts/xbrl_extract.py:_apply_extra_mappings](../skills/japan-stock-analysis/scripts/xbrl_extract.py) は mapping spec の `element` 1 つを `get_fact` で引くだけ。複数要素を組み合わせる仕様 (例: `aggregate: [...]`) が存在しない。

## 影響範囲

- 影響銘柄: 業種横断 (薬品・ガス・電力・銀行・建設など、複数の負債明細を XBRL で別要素として持つすべて)。製造業 IFRS でも該当
- 該当ファイル:
  - [scripts/xbrl_extract.py](../skills/japan-stock-analysis/scripts/xbrl_extract.py) `_apply_extra_mappings`、`extract_path_a` (InterestBearingDebt 特例ロジック)
  - [scripts/mapping_resolver.py](../skills/japan-stock-analysis/scripts/mapping_resolver.py) `save_mapping` の入力スキーマ検証
  - [docs/xbrl_variation_knowledge.md §7](../skills/japan-stock-analysis/docs/xbrl_variation_knowledge.md) マッピング JSON 仕様

## 再現手順

1. 武田薬品を analyze: `python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 4502`
2. needs_mapping で unresolved に `InterestBearingDebt` が出る
3. mapping JSON で `"InterestBearingDebt": {"element": "jpigp_cor:BondsAndBorrowingsCLIFRS", ...}` のように単一要素を指定しても 549B だけになる
4. 本来の 4.5T を出すには手動加算が必要

## 修正案

### 案1 (推奨): mapping spec に `aggregate` キー追加

```json
{
  "InterestBearingDebt": {
    "aggregate": [
      {"element": "jpigp_cor:BondsAndBorrowingsCLIFRS", "context": "CurrentYearInstant"},
      {"element": "jpigp_cor:BondsAndBorrowingsNCLIFRS", "context": "CurrentYearInstant"}
    ],
    "rationale": "..."
  }
}
```

`_apply_extra_mappings` で `aggregate` キーがあれば各要素を `get_fact` して整数加算するパスを追加。既存 `element` 単一キーと排他制御。

### 案2: whitelist 拡張で対応

`scripts/xbrl_extract.py` の `extract_path_a` 内の InterestBearingDebt 特例ロジックを拡張し、第 3 パターン (BondsAndBorrowings 系) を追加する。Path A 内で完結するので mapping 不要。ただし業種ごとに増え続けるので長期的には案1 の汎用化が必要。

### 推奨

両方併用: 既知のパターン (案2) は whitelist 化、未知パターン (案1) は mapping で表現。今は案1 を新規 enhancement として切り出すべき。

## 対応

<!-- AI instruction: 修正完了後に追記するセクション。採用した修正案、または修正案にない独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- 解決 enhancement: [ENH-003](../enhancements/003_aggregate_mappings.md) (起票済、実装未着手)
- 関連: [README §B extra_mappings の単一要素縛り](../skills/japan-stock-analysis/README.md)
- 関連: [docs/p9_smoke_results.md 改善余地2](../skills/japan-stock-analysis/docs/p9_smoke_results.md)
- 観測: P9 で 4502 武田、manual_test で 9531 東京ガス
