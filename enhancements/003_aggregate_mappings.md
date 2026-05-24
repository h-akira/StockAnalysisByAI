# ENH-003: mapping spec に `aggregate` キーを追加し複数要素加算をサポート

## ステータス

未着手

## 起票日

2026-05-24

## 種別

仕様追加

## 概要

mapping JSON の `extra_mappings` を「1 項目 = 1 要素」しか扱えない現状から、複数要素を整数加算して 1 項目に集約できる `aggregate` キー仕様を追加する。これにより銀行・ガス・電力等の業種で複数の負債明細を合算しなければ取れない `InterestBearingDebt` 等を mapping で表現可能にする。

## 背景・動機

[BUG-004](../bugs/004_interest_bearing_debt_needs_aggregate.md) の根本治療。

現状は `scripts/xbrl_extract.py:_apply_extra_mappings` が mapping spec の `element` 1 つだけを `get_fact` で引く実装。`BondsAndBorrowingsCLIFRS + BondsAndBorrowingsNCLIFRS` のような複数要素加算が必要なケースで:

- 4502 武田薬品: 549B + 3.97T = 4.5T の本来 IBD を mapping で表現できず unresolved に逃げている
- 9531 東京ガス: `BondsPayable` + `LongTermLoansPayable` + `ShortTermLoansPayable` + `CurrentPortion` の 4 要素合算が必要
- 8306 MUFG: 預金 + NCDs + 借入金 + 社債の複合だが `Deposits` 単独に近似マッピング

結果として該当銘柄の `data_*.json` の `financials.InterestBearingDebt` が null になる。製造業 IFRS でも該当する可能性あり (`extract_path_a` の特例 whitelist でカバーしきれない場合)。

## 要件

- mapping JSON に `aggregate: [{element, context}, ...]` 形式の指定を追加できる
- 既存の `element` 単一指定は引き続き動く (排他制御)
- `aggregate` の各要素を `get_fact` で引き、`value is None` でないものを整数加算
- 加算結果が空 (全要素 None) なら mapping は適用しない (= 既存の単一要素挙動と同じ "失敗時は触らない")
- mapping save 時の入力バリデーション (`mapping_resolver._cmd_save`) で `element` か `aggregate` のどちらかは必須、両方同時指定は禁止
- audit のため `source` を `aggregate of [...]` 形式で記録
- `docs/xbrl_variation_knowledge.md §7` のスキーマセクションに `aggregate` 形式を追記

## 影響範囲

- [scripts/xbrl_extract.py](../skills/japan-stock-analysis/scripts/xbrl_extract.py)
  - `_apply_extra_mappings`: `aggregate` キー分岐を追加
- [scripts/mapping_resolver.py](../skills/japan-stock-analysis/scripts/mapping_resolver.py)
  - `_cmd_save`: 入力バリデーションを拡張 (`element` xor `aggregate` 必須)
- [skills/japan-stock-analysis/docs/xbrl_variation_knowledge.md](../skills/japan-stock-analysis/docs/xbrl_variation_knowledge.md) §7
  - スキーマに `aggregate` を追記
- [tests/test_xbrl_extract.py](../skills/japan-stock-analysis/tests/test_xbrl_extract.py) / [tests/test_mapping_resolver.py](../skills/japan-stock-analysis/tests/test_mapping_resolver.py)
  - `aggregate` 適用ケースのテスト追加 (fixture XBRL に対して 2-3 要素合算)
  - mapping save バリデーション (両方指定エラー、片方欠落エラー) のテスト追加

## 実現案

### 案1 (推奨): mapping spec に `aggregate` キー追加

mapping JSON 形式の拡張例:

```json
{
  "InterestBearingDebt": {
    "aggregate": [
      {"element": "jpigp_cor:BondsAndBorrowingsCLIFRS", "context": "CurrentYearInstant"},
      {"element": "jpigp_cor:BondsAndBorrowingsNCLIFRS", "context": "CurrentYearInstant"}
    ],
    "rationale": "Takeda: current + non-current bonds & borrowings"
  }
}
```

`_apply_extra_mappings` の擬似コード:

```python
for item, spec in extra_mappings.items():
    if merged.get(item, {}).get("value") is not None:
        continue
    if "aggregate" in spec:
        parts, sources = [], []
        for entry in spec["aggregate"]:
            element = entry.get("element", "")
            ctx = entry.get("context", CTX_DURATION)
            if ":" not in element:
                continue
            prefix, local = element.split(":", 1)
            v, _, _ = get_fact(tree, nsmap, prefix, local, ctx)
            if v is not None:
                parts.append(int(v))
                sources.append(f"{element}@{ctx}")
        if parts:
            merged[item] = {
                "value": str(sum(parts)), "unit": "JPY", "decimals": "-6",
                "source": f"aggregate of [{', '.join(sources)}]",
                "path": "mapping",
                "rationale": spec.get("rationale", ""),
            }
        continue
    # existing single-element path
    ...
```

`mapping_resolver._cmd_save` のバリデーション:

```python
for k, v in mappings.items():
    has_element = "element" in v
    has_aggregate = "aggregate" in v
    if has_element == has_aggregate:
        bad.append(k)  # both or neither
        continue
    if has_aggregate:
        if not isinstance(v["aggregate"], list) or not v["aggregate"]:
            bad.append(k)
        # each aggregate entry needs element + context
        ...
```

### 案2: `extract_path_a` の InterestBearingDebt 特例 whitelist 拡張

`scripts/xbrl_extract.py:extract_path_a` の IBD 特例ロジック (Pattern 1 / 2) に Pattern 3 (BondsAndBorrowings 系) を追加。Path A 内で完結し mapping 不要。

ただし業種ごとに増え続けるので長期的には案1 の汎用化が必要。BUG-004 の議論通り**両方併用**が最終形だが、本 ENH は案1 (汎用化) に集中する。Pattern 3 は別 enhancement か、ナレッジが固まった時点で追加する。

## 想定される効果

- 4502 / 9531 / 8306 等で IBD が正しく出る (handラベル mapping で複合要素を表現可)
- `extra_mappings` の表現力が「単一要素」から「整数加算複合」に拡張、銀行/保険等の業種固有勘定科目への対応が大幅に楽になる
- 将来的に `subtract` / `multiply` 等の演算が必要になったら同パターンで追加できる素地ができる

## 想定される副作用・リスク

- mapping JSON 形式の変更 → 既存 mapping (`element` 単一) は引き続き動くので後方互換
- 加算順序による浮動小数点誤差: XBRL の数値は整数 (decimals="-6" 等) で扱っているので問題なし
- 加算対象に重複 (例: `BondsPayable` と `LongTermLoansPayable` が概念的に重なる) があると二重計上になる → ナレッジで明示するしかない
- 案1 と案2 を併用する場合、whitelist が先に解決するので mapping は触らない (既存挙動と同じ)

## ロールバック手順

1. `xbrl_extract.py:_apply_extra_mappings` の `if "aggregate" in spec:` ブロックを削除
2. `mapping_resolver._cmd_save` のバリデーション拡張を revert
3. 既に保存された mapping JSON に `aggregate` キーがある場合は無視されるだけ (item が unresolved に戻る) なので破壊的なリスクは小さい

## 関連

- 親 bug: [BUG-004](../bugs/004_interest_bearing_debt_needs_aggregate.md)
- 参考: [README §B extra_mappings の単一要素縛り](../skills/japan-stock-analysis/README.md)
- 参考: [docs/p9_smoke_results.md 改善余地2](../skills/japan-stock-analysis/docs/p9_smoke_results.md)
- 観測対象: P9 で 4502 武田、manual_test で 9531 東京ガス
