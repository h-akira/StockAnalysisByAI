# Enhancement: split_adjust の EPS Summary プローブを JGAAP / Diluted にフォールバック

- **提案日**: 2026-05-23
- **提案経緯**: manual_test 9531 (JGAAP) で PER 全期 NaN が発覚、bug 化
- **影響範囲**: JGAAP 採用銘柄全般（銀行・保険・電力・ガス・鉄道など非製造業の大半）
- **優先度**: **P0**（[bugs/2026-05-23_jgaap_per_always_nan.md](../bugs/2026-05-23_jgaap_per_always_nan.md) の根本治療）

## 動機

[scripts/xbrl_extract.py:extract_restated_eps_from_zip](../skills/japan-stock-analysis/scripts/xbrl_extract.py) は `BasicEarningsLossPerShareIFRSSummaryOfBusinessResults` 一択。JGAAP 銘柄では同要素が存在せず restated EPS が空辞書 `{}` を返し、PER が全期 NaN になる。

P3.5 / P4 で IFRS 製造業 (Toyota, Sony) のみで検証してきたため見落とされた。

## 現状の挙動

```python
EPS_SUMMARY_ELEMENT = "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults"

def extract_restated_eps_from_zip(zip_path, edinet_code):
    ...
    out = {}
    for offset, ctx in SUMMARY_CONTEXTS:
        value, _, _ = get_fact(tree, nsmap, "jpcrp_cor", EPS_SUMMARY_ELEMENT, ctx)
        if value is None:
            continue
        out[offset] = float(value)
    return out
```

JGAAP 銘柄 (e.g. 9531 東京瓦斯, 8306 MUFG) では `get_fact` が常に `None` を返し、`out` は空 `{}`。

## 提案する変更

### 変更1: 4 候補をフォールバック順にプローブ

```python
# Priority-ordered candidates. First non-null wins per (offset, ctx).
EPS_SUMMARY_ELEMENTS = [
    ("BasicEarningsLossPerShareIFRSSummaryOfBusinessResults", "ifrs_basic"),
    ("BasicEarningsLossPerShareSummaryOfBusinessResults", "jgaap_basic"),
    ("DilutedEarningsPerShareIFRSSummaryOfBusinessResults", "ifrs_diluted"),
    ("DilutedEarningsPerShareSummaryOfBusinessResults", "jgaap_diluted"),
]

def extract_restated_eps_from_zip(zip_path, edinet_code):
    ...
    out = {}
    eps_source: dict[int, str] = {}  # audit which fallback won
    for offset, ctx in SUMMARY_CONTEXTS:
        for elem_name, tag in EPS_SUMMARY_ELEMENTS:
            value, _, _ = get_fact(tree, nsmap, "jpcrp_cor", elem_name, ctx)
            if value is not None:
                out[offset] = float(value)
                eps_source[offset] = tag
                break
    # eps_source can be passed to split_adjust to record in the cache JSON
    return out, eps_source
```

### 変更2: split_adjust cache に audit 情報を残す

`cache/split_adjust/{sec_code}.json` を拡張:

```json
{
  "sec_code": "9531",
  "source_doc_id": "S100W10L",
  "source_period_end": "2025-03-31",
  "resolved_at": "...",
  "restated_eps": {
    "2025-03-31": 123.45,
    "2024-03-31": 117.80
  },
  "eps_source": {
    "2025-03-31": "jgaap_basic",
    "2024-03-31": "jgaap_basic"
  }
}
```

`pipeline.py` の warning に「fallback 採用」を明示:

```python
fallback_used = {tag for tag in split_adjust.eps_source.values()
                 if tag != "ifrs_basic"}
if fallback_used:
    warnings.append(
        f"split_adjust used non-IFRS-Basic fallback for restated EPS: "
        f"{sorted(fallback_used)}. Verify values."
    )
```

### 変更3: bug §「副次的修正: warning メッセージ」も同時実装

`pipeline.py` のメッセージで「5 年窓外」と「restated EPS が空」を区別:

```python
if not split_adjust.restated_eps:
    warnings.append(
        "split_adjust could not extract any restated EPS from the latest "
        "report. PER will be NaN for all periods. "
        "Possible cause: latest report uses an XBRL taxonomy not covered "
        "by EPS_SUMMARY_ELEMENTS in extract_restated_eps_from_zip."
    )
elif missing_periods:
    warnings.append(
        f"PER is NaN for periods outside the restated EPS window: "
        f"{missing_periods}."
    )
```

## 想定される効果

- 9531 / 8306 など JGAAP 銘柄で PER が出る
- MUFG 8306 で手動マッピングしていた `DilutedEarningsPerShareSummaryOfBusinessResults` 採用が **自動化**される（mapping_8306.json の `EarningsPerShare` エントリが不要に）
- audit 情報により後から「どの fallback が効いたか」検証可能

## 想定される副作用・リスク

- Diluted を Basic 代用とすることへの会計上の妥当性: 一般的に Diluted は希薄化考慮済なので Basic より少し小さい値。PER が少し過大になる。warning で明示するので運用上は問題なし
- IFRS 銘柄でも IFRS Basic が無く JGAAP Basic だけがある変則ケース（あるか不明）: 4 候補の優先順位で自動カバー
- 既存の Sony / Toyota 検証値が変わらないこと: IFRS Basic がヒットするので変化なし（テストで担保）
- MUFG mapping の二重定義: 手動マッピングと自動 fallback の競合。手動側を優先するか fallback 側を優先するかの設計判断が必要（手動側優先が妥当）

## 実装の見積もり

- 難易度: 小
- 影響ファイル:
  - [scripts/xbrl_extract.py](../skills/japan-stock-analysis/scripts/xbrl_extract.py)（`extract_restated_eps_from_zip` 拡張）
  - [scripts/split_adjust.py](../skills/japan-stock-analysis/scripts/split_adjust.py)（SplitAdjustResult に `eps_source` 追加、cache JSON 拡張）
  - [scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py)（warning 改善）
- 追加テスト:
  - test_xbrl_extract.py に JGAAP fixture (e.g. 9531 か 8306 の 1 期分) を追加して fallback 検証
  - test_split_adjust.py に `eps_source` audit のテスト

## 関連

- 関連 bug: [bugs/2026-05-23_jgaap_per_always_nan.md](../bugs/2026-05-23_jgaap_per_always_nan.md)
- 元の議論: [README §D JGAAP 銀行業の Basic EPS](../skills/japan-stock-analysis/README.md)
- pre-research: [pre-research/edinet/verification_results.md §Step7](../pre-research/edinet/verification_results.md)
