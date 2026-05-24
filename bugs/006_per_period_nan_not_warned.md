# BUG-006: 期間別に取得失敗した項目が silent NaN になり warning も出ない

## ステータス

未修正

## 発見日

2026-05-23

## 概要

mapping を適用しても XBRL タクソノミが年度間で変わっている場合、古い期で値が取れず NaN になる。`extract_from_zip` の `value is None` 分岐で silent に NaN を返すため、ユーザーには「なぜ NaN なのか」が伝わらない。

## 症状

- 9531 東京瓦斯の 2016-2018 年度 (古い期) で `SharesOutstanding` が NaN
- 2019 年度以降は同 mapping で値が取れる
- warnings には期間別の取得失敗が出ない (mapping は保存済みなので「intentionally unresolved」warning も出ない)
- ユーザーは CSV を見て初めて「なぜここだけ NaN?」と気付く

## 原因

[scripts/xbrl_extract.py:_apply_extra_mappings](../skills/japan-stock-analysis/scripts/xbrl_extract.py) は `value is None` ならマッピングを上書きしない実装 (これ自体は正しい)。しかし、[scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) / [scripts/timeseries.py](../skills/japan-stock-analysis/scripts/timeseries.py) のどこにも「mapping ありなのに期間別に取得失敗」を追跡する仕掛けがない。

## 影響範囲

- 影響銘柄: XBRL タクソノミが年度間で変化している銘柄すべて。jpcrp_cor タクソノミ自体が毎年改訂されるため、長期分析するほど該当ケースが増える
- 該当ファイル:
  - [scripts/timeseries.py](../skills/japan-stock-analysis/scripts/timeseries.py) `extract_row` / `build_timeseries`
  - [scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) warning 集約

## 再現手順

1. 9531 を mapping 付きで analyze (SharesOutstanding を最新期向け要素にマッピング)
2. `cache/derived/timeseries_9531.csv` を確認、2016-2018 行の SharesOutstanding が空、2019 以降は値あり
3. `data_9531.json` の warnings に該当する記述がない

## 修正案

### 案1 (推奨): 期間別 NaN を追跡して warning 化

`build_timeseries` で期間ごとに extract_row が None を返した項目を追跡:

```python
def build_timeseries(...):
    ...
    nan_periods: dict[str, list[str]] = {}  # item -> [period_end, ...]
    for doc in docs:
        items, _ = extract_row(...)
        for k, v in items.items():
            if v is None and k in mapped_keys:  # mapping あるのに値が取れなかった
                nan_periods.setdefault(k, []).append(doc.period_end)
        rows.append(...)
    return df, unresolved_union, nan_periods
```

pipeline で warning に列挙:
```
"[9531] SharesOutstanding is NaN for 2016-03-31, 2017-03-31, 2018-03-31
 (mapping exists but the XBRL element is missing in those periods —
 taxonomy may have changed)."
```

### 案2: 案1 + mapping JSON spec 拡張 (`unresolved_periods` 等で明示)

将来 mapping ファイルが豊富になったら案1 だけでは足りないかもしれない。spec 拡張は必要になった時で十分。

## 対応

<!-- AI instruction: 修正完了後に追記するセクション。採用した修正案、または修正案にない独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- 関連 bug: [BUG-005](005_needs_mapping_loop.md) (UX 面で同根)
- 関連: [README §J 会計基準の年度間切替](../skills/japan-stock-analysis/README.md)
- mapping cache の現状形式: [docs/xbrl_variation_knowledge.md §7](../skills/japan-stock-analysis/docs/xbrl_variation_knowledge.md)
- 観測: 9531 の S10080AQ (FY2015) と S100W10L (FY2024) で `SharesOutstanding` 要素の有無を確認済み
