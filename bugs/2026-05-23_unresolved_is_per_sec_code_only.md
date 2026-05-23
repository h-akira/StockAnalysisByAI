# Bug: mapping の `unresolved[]` が銘柄全体単位でしか宣言できない (期間別 unresolved 不可)

- **発見日**: 2026-05-23
- **発見シーン**: manual_test で 9531 東京瓦斯の **2016-2018年度 (古い期)** で `SharesOutstanding` の単独要素が XBRL に存在せず、しかし **2019年度以降は存在する**ことが判明。現状の mapping 仕様ではこのパターンを表現できず、銘柄全体で unresolved にするしかない。
- **影響範囲**: XBRL タクソノミが年度間で変更された銘柄すべて（年度を遡るほど該当ケースが増える）
- **重大度**: P1（古い期だけ NaN になる、新しい期は数字が取れるべきなのに不必要に NaN になる）
- **再現性**: 9531 で常に再現（他の年度跨ぎ XBRL 変更銘柄でも同様の可能性）

## 症状

mapping JSON で `"unresolved": ["SharesOutstanding"]` と宣言すると、現実装は **全期間で SharesOutstanding を NaN 扱い**にする。本来は「2016-2018 のみ NaN、2019 以降は通常抽出 (whitelist or mapping) を使う」と期間別に制御したいが、それを表現する仕様がない。

manual_test 9531 のケース:
- 2016年度 XBRL (`S10080AQ`): `jpcrp_cor:NumberOfIssuedSharesAsOfFiscalYearEnd...` は **TextBlock 形式のみ**（HTML テーブルとして埋め込まれ、構造化された数値要素はない）
- 2025年度 XBRL (`S100W10L`): 同要素が **shares unit の数値要素として存在**、388,893,859 株

mapping JSON は最新年度の構造を見て作るので「取れるはず」と宣言、しかし古い年度では取れない → `extract_from_zip` の `extra_mappings` 解決パスで `value` が None → silent に NaN になる。

幸い `value is None` なら override しない実装なので破壊的ではないが、warning に「2016-2018 では SharesOutstanding 取れません」と出ないので**ユーザーから見ると不透明**。

## 再現手順

```bash
# 9531 の事例
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 9531
# → cache/derived/timeseries_9531.csv の 2016-2018 行の SharesOutstanding が空
#   2019-2025 行は値が入る

# mapping JSON で SharesOutstanding を unresolved にすると、現実装では
# 2019-2025 までも NaN になってしまう（期間別の意図を表現できないので、
# manual_test では unresolved に入れた）
```

## 期待される挙動

mapping JSON で期間別 unresolved を表現できる:

```json
{
  "mappings": {
    "SharesOutstanding": {
      "element": "jpcrp_cor:NumberOfIssuedSharesAsOfFiscalYearEnd...",
      "context": "FilingDateInstant",
      "rationale": "...",
      "unresolved_periods": ["2016-03-31", "2017-03-31", "2018-03-31"]
    }
  }
}
```

または「該当期で値が取れなかったら自動で warning を出す」だけでも一定の改善:

```
warnings.append(
  "[9531] SharesOutstanding could not be extracted for periods "
  "['2016-03-31', '2017-03-31', '2018-03-31'] despite a mapping being "
  "in place. Likely the XBRL taxonomy changed across years."
)
```

## 実際の挙動

[scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py):
```python
accepted_unresolved: set[str] = (
    set(mapping_cached.get("unresolved", [])) if mapping_cached else set()
)
...
unresolved = [u for u in unresolved if u not in accepted_unresolved]
```

`accepted_unresolved` は **全期 union**。各 doc の extract から戻る `unresolved` も union しか持たない（[scripts/timeseries.py:build_timeseries](../skills/japan-stock-analysis/scripts/timeseries.py)）。

期間別の追跡情報が **どこにもない**ため、修正には複数箇所の改修が必要。

## 根本原因

設計時に「mapping は銘柄に対して 1 つ」と仮定していた（plan §4.4、cache/mappings/{sec_code}.json の形式）。同一銘柄でも XBRL 構造が年度間で変わるケースを考慮していなかった。

XBRL タクソノミ（jpcrp_cor 等）自体が年度ごとに改訂されており、古い年度の XBRL は新しい要素名を持たない / 新しい年度の XBRL は古い要素名を捨てる、ということが起きる。

## 修正案

### 案1: timeseries.extract_row が期間別の unresolved を返す (最小工数)

現状:
```python
def extract_row(api_key, doc, *, extra_mappings=None) -> tuple[dict, list[str]]:
    ...
    return row, result.unresolved
```

期間ごとに unresolved を保持:
```python
def build_timeseries(...):
    ...
    unresolved_by_period: dict[str, list[str]] = {}  # period_end -> [items]
    for doc in docs:
        items, unresolved = extract_row(...)
        rows.append({"period_end": doc.period_end, **items})
        if unresolved:
            unresolved_by_period[doc.period_end] = unresolved
    return df, unresolved_by_period
```

pipeline.py で「全期で同じ unresolved があれば従来通り集約、期間別に違えば期間別 warning」と分岐。

### 案2: mapping spec に `unresolved_periods` を追加 (柔軟だが破壊的)

mapping JSON のフォーマット拡張:
```json
"unresolved": ["InterestBearingDebt"],
"unresolved_per_period": {
  "SharesOutstanding": ["2016-03-31", "2017-03-31", "2018-03-31"]
}
```

新フィールド追加なので後方互換あり。`pipeline.py` で `unresolved_per_period[period].issubset(...)` で期間別に許容判定。

### 案3: silent NaN を許容するが必ず audit 出力

最も軽い改修。`build_timeseries` が `(period, item) -> value=None` の events を集めて pipeline に渡し、warnings に明示:

```
"[9531] SharesOutstanding is NaN for 2016-03-31, 2017-03-31, 2018-03-31
 (mapping exists but the XBRL element is missing in those periods —
 taxonomy may have changed)."
```

### 推奨

案3 がまず必要（透明性確保、即実装可）。その上で案1で期間別 unresolved を内部表現として持ち、必要なら案2 を加える。

## 関連

- 関連 bug: [2026-05-23_jgaap_per_always_nan.md](2026-05-23_jgaap_per_always_nan.md)（同じ「JGAAP/古い期で XBRL 構造が違う」系の問題）
- 関連: [README §J 会計基準の年度間切替](../skills/japan-stock-analysis/README.md)
- mapping cache の現状形式: [docs/xbrl_variation_knowledge.md §7](../skills/japan-stock-analysis/docs/xbrl_variation_knowledge.md)
