# ENH-002: split_adjust の EPS Summary プローブを JGAAP / Diluted にフォールバック

## ステータス

完了（検証待ち）

## 起票日

2026-05-23

## 種別

仕様追加

## 概要

`extract_restated_eps_from_zip` が IFRS Basic EPS 一択でプローブしている現状を、IFRS Basic → JGAAP Basic → IFRS Diluted → JGAAP Diluted の優先順位でフォールバックする方式に拡張。採用した候補を `eps_source` に記録して透明性確保。

## 背景・動機

[BUG-002](../bugs/002_jgaap_per_always_nan.md) の根本治療。JGAAP 採用銘柄 (銀行・保険・電力・ガス・鉄道など非製造業の大半) で PER が全期 NaN になる。これは P3.5 / P4 の検証が IFRS 製造業 (Toyota, Sony) のみだったため見落とされた。

中立サブエージェントレビュー (agent ID: a0c1cb76d84bde7b2) で「設計筋良し、追加調査ほぼ不要、影響範囲広いわりに変更局所的」と評価された。

## 要件

- JGAAP 銘柄 (9531 / 8306 等) で PER が NaN でない値を持つ
- 既存の IFRS 銘柄 (7203 / 6758) で PER 値が変化しない (IFRS-Basic が優先採用される)
- どの候補が採用されたかを `eps_source` フィールドに記録 (audit)
- 非 IFRS-Basic フォールバック採用時に warning で透明性確保
- warning メッセージで「restated_eps 空」と「5 年窓外」を区別 ([BUG-003](../bugs/003_warning_message_misleading_for_jgaap.md) 同時解決)

## 影響範囲

- [scripts/xbrl_extract.py](../skills/japan-stock-analysis/scripts/xbrl_extract.py) `extract_restated_eps_from_zip`、定数 `EPS_SUMMARY_ELEMENTS`
- [scripts/split_adjust.py](../skills/japan-stock-analysis/scripts/split_adjust.py) `SplitAdjustResult` (新フィールド `eps_source`)、`resolve_split_adjust` (cache JSON 拡張)
- [scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) warning 生成
- [tests/test_xbrl_extract.py](../skills/japan-stock-analysis/tests/test_xbrl_extract.py) / [tests/test_split_adjust.py](../skills/japan-stock-analysis/tests/test_split_adjust.py) (テスト追加)
- [tests/fixtures/](../skills/japan-stock-analysis/tests/fixtures/) (JGAAP XBRL を 1 件追加、~1.5MB)

## 実現案

### 案1 (推奨): 4 候補フォールバック + audit field

```python
EPS_SUMMARY_ELEMENTS = [
    ("BasicEarningsLossPerShareIFRSSummaryOfBusinessResults", "ifrs_basic"),
    ("BasicEarningsLossPerShareSummaryOfBusinessResults", "jgaap_basic"),
    ("DilutedEarningsPerShareIFRSSummaryOfBusinessResults", "ifrs_diluted"),
    ("DilutedEarningsPerShareSummaryOfBusinessResults", "jgaap_diluted"),
]

def extract_restated_eps_from_zip(zip_path, edinet_code):
    ...
    out = {}
    eps_source: dict[int, str] = {}
    for offset, ctx in SUMMARY_CONTEXTS:
        for elem_name, tag in EPS_SUMMARY_ELEMENTS:
            value, _, _ = get_fact(tree, nsmap, "jpcrp_cor", elem_name, ctx)
            if value is not None:
                out[offset] = float(value)
                eps_source[offset] = tag
                break
    return out, eps_source
```

`split_adjust` cache JSON 拡張:
```json
{
  "sec_code": "9531",
  "source_doc_id": "S100W10L",
  "source_period_end": "2025-03-31",
  "restated_eps": { "2025-03-31": 123.45, ... },
  "eps_source": { "2025-03-31": "jgaap_basic", ... }
}
```

`pipeline.py` warning:
```python
fallback_used = {tag for tag in split_adjust.eps_source.values() if tag != "ifrs_basic"}
if fallback_used:
    warnings.append(
        f"split_adjust used non-IFRS-Basic fallback: {sorted(fallback_used)}. "
        "Verify values."
    )

if not split_adjust.restated_eps:
    warnings.append(
        "split_adjust could not extract any restated EPS. "
        "PER will be NaN for all periods."
    )
elif missing_periods:
    warnings.append(
        f"PER is NaN for periods outside the restated EPS window: {missing_periods}."
    )
```

### 案2: company_map.csv に accounting_standard 列を持って事前分岐

industry → 会計基準の対応表を別途持つ必要があり、保守コスト高。フォールバック方式で十分なので不採用。

## 検証済みの仕様前提

- ✅ IFRS Basic EPS の要素名 `jpcrp_cor:BasicEarningsLossPerShareIFRSSummaryOfBusinessResults` は Toyota / Sony で実証済 ([pre-research Step 7](../pre-research/edinet/verification_results.md))
- ✅ JGAAP の `jpcrp_cor:BasicEarningsLossPerShareSummaryOfBusinessResults` 要素 (IFRS suffix なし) の存在は [docs/xbrl_variation_knowledge.md §4](../skills/japan-stock-analysis/docs/xbrl_variation_knowledge.md) でナレッジ化済。9531 / 8306 の実 XBRL での存在確認は未完了 (実装前調査で確認)
- ⚠️ MUFG 8306 の XBRL では Basic EPS 不在で Diluted のみという観測あり (manual_test と P9 検証で確認済)

## 実装前の追加調査事項

- [ ] **重要**: 9531 / 8306 の XBRL で `BasicEarningsLossPerShareSummaryOfBusinessResults` (IFRS suffix なし版) の context が IFRS 版と同じ (`CurrentYearDuration` / `Prior{N}YearDuration` 等) か実機確認。異なる場合は `SUMMARY_CONTEXTS` 拡張要
- [ ] Diluted EPS が複数年度提供されているか (Basic 不在期に Prior\*YearDuration も Diluted で揃うか)
- [ ] `data_*.json` v1.0 スキーマへの `eps_source` 追加が minor bump で済むか確認

## 想定される効果

- 9531 / 8306 など JGAAP 銘柄で PER が出る
- MUFG 8306 で manual_test / P9 検証時に手動マッピングしていた Diluted EPS が**自動 fallback で取れる**ようになる
- audit 情報 `eps_source` により「どの候補が効いたか」事後検証可能

## 想定される副作用・リスク

- **Diluted を Basic 代用する会計上の妥当性**: Diluted は希薄化考慮済で Basic より若干小さい (絶対値)。結果 PER がやや過大になる。warning で明示するので運用上 OK
- **MUFG 手動 mapping との競合**: `cache/mappings/8306.json` の `EarningsPerShare` 手動エントリと自動 fallback の二重定義。手動側を優先 (extra_mappings ロジック維持) するのが安全。実装後にドキュメント (docs/p9_smoke_results.md) と manual_test mapping JSON 更新
- **`data_*.json` スキーマ変更**: `eps_source` 新フィールド追加は minor bump (1.0 → 1.1)。後方互換あり
- **既存テスト**: test_xbrl_extract.py / test_split_adjust.py に新 fixture 必要

## 後始末 (中立レビュー指摘)

1. **MUFG 8306 手動マッピング簡素化**: 自動 fallback が安定後、`cache/mappings/8306.json` の `EarningsPerShare` 手動エントリは不要となるので削除を推奨 (削除しても挙動同じだが、保守者が二重定義に迷う)
2. **PBR / SharesOutstanding 同一問題確認**: 同じパターンの JGAAP/IFRS 差異が SharesOutstanding にも存在するか調査して、必要なら別 enhancement を切る (9531 は 2016-2018 で TextBlock のみという別の問題もあり、要切り分け)

## ロールバック手順

1. `EPS_SUMMARY_ELEMENTS` を元の `EPS_SUMMARY_ELEMENT` (単一文字列) に戻す
2. `extract_restated_eps_from_zip` の戻り値を 1 つに戻す (`eps_source` 削除)
3. `SplitAdjustResult` から `eps_source` 削除
4. cache JSON の `eps_source` フィールドは無視されるだけなので残置可

warning 改善 (BUG-003) はロールバック不要 (本ロールバックでも維持できる)。

## 対応

案1 (4 候補フォールバック + audit field) を採用。同時解決の BUG-003 込みで実装。実装詳細は [BUG-002 §対応](../bugs/002_jgaap_per_always_nan.md) を参照。

未実施 (本対応スコープ外、必要時に別途):
- JGAAP fixture (9531 等) 同梱と固有 PASS テスト追加 — 今回は実機 mock ベース検証のみ
- `data_*.json` v1.0 → v1.1 スキーマバンプの正式アナウンス (`eps_source` を per-period metrics に流す場合のスキーマ拡張)
- 後始末: MUFG 8306 手動 mapping 簡素化、SharesOutstanding の JGAAP/IFRS 差異調査

## 関連

- 親 bug: [BUG-002](../bugs/002_jgaap_per_always_nan.md)
- 同時解決 bug: [BUG-003](../bugs/003_warning_message_misleading_for_jgaap.md) (warning 改善)
- 元の議論: [README §D JGAAP 銀行業の Basic EPS](../skills/japan-stock-analysis/README.md)
- pre-research: [pre-research/edinet/verification_results.md §Step7](../pre-research/edinet/verification_results.md)
- ナレッジ: [docs/xbrl_variation_knowledge.md §4](../skills/japan-stock-analysis/docs/xbrl_variation_knowledge.md)
- 中立レビュー: subagent ID `a0c1cb76d84bde7b2` (設計妥当、後始末項目を追記)
