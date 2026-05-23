# Bug: JGAAP 銘柄で PER が全期 NaN (restated EPS が一切取れない)

- **発見日**: 2026-05-23
- **発見シーン**: manual_test で 9531 東京瓦斯 (JGAAP) を分析、warning に「PER NaN for periods outside the latest report's restated EPS coverage」が**全 10 期に対して**出た
- **影響範囲**: JGAAP を採用するすべての銘柄（銀行・保険・電力・ガス・鉄道など、業種非製造の大半）
- **重大度**: **P0**（影響範囲が広く、Skill 主要指標の一つである PER が出ない）
- **再現性**: JGAAP 銘柄なら常に再現

## 症状

JGAAP の銘柄を analyze すると、`cache/split_adjust/{sec_code}.json` の `restated_eps` が空辞書 `{}` になり、`pipeline.py` が **全期間** で PER を NaN にする。

東京ガス 9531 の実例（[manual_test/.claude/skills/japan-stock-analysis/cache/split_adjust/9531.json](../manual_test/.claude/skills/japan-stock-analysis/cache/split_adjust/9531.json)）:

```json
{
  "sec_code": "9531",
  "source_doc_id": "S100W10L",
  "source_period_end": "2025-03-31",
  "resolved_at": "2026-05-23T14:00:10.115686+00:00",
  "restated_eps": {}
}
```

warnings:
```
PER is NaN for periods outside the latest report's restated EPS coverage (5-year window):
['2016-03-31', '2017-03-31', '2018-03-31', ..., '2025-03-31']
```

**最新期 2025-03-31 まで含めて全期 NaN** = 「5 年窓外なので NaN」ではなく「restated EPS 自体が空」が真相。warning メッセージも誤解を招く（「5 年窓外」と表示しているが実態は全期）。

## 再現手順

```bash
# JGAAP 銘柄なら何でも再現
# 例: 9531 東京ガス (manual_test で実証済)
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 9531
# data_9531.json の metrics.PER がすべて null
```

cache/split_adjust/{sec_code}.json の中身を見れば即わかる。

## 期待される挙動

JGAAP の SummaryOfBusinessResults には `BasicEarningsLossPerShareSummaryOfBusinessResults` （IFRS の `IFRS` suffix なし版）が存在する。これを fallback として probe すれば JGAAP 銘柄でも restated EPS が取れて PER が出る。

## 実際の挙動

[scripts/xbrl_extract.py:extract_restated_eps_from_zip](../skills/japan-stock-analysis/scripts/xbrl_extract.py) は **IFRS 一択**:

```python
EPS_SUMMARY_ELEMENT = "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults"

SUMMARY_CONTEXTS: list[tuple[int, str]] = [
    (0, "CurrentYearDuration"),
    ...
]

def extract_restated_eps_from_zip(zip_path: Path, edinet_code: str) -> dict[int, float]:
    ...
    for offset, ctx in SUMMARY_CONTEXTS:
        value, _, _ = get_fact(tree, nsmap, "jpcrp_cor", EPS_SUMMARY_ELEMENT, ctx)
        if value is None:
            continue
        out[offset] = float(value)
    return out
```

JGAAP の XBRL には `BasicEarningsLossPerShareIFRSSummaryOfBusinessResults` が存在せず、毎回 `None` を返すため `out` が空のまま。

## 根本原因

P3.5 / P4 で **IFRS 製造業 (Toyota, Sony) のみで検証してきた**ため、IFRS suffix なしの JGAAP variant の存在を考慮していなかった。pre-research Step 7 でも IFRS suffix 付きの値のみ使った。

README §D で既に「将来の課題」として認識していたが、優先度 P0 として bug 扱いすべき内容だった。

## 修正案

[scripts/xbrl_extract.py:extract_restated_eps_from_zip](../skills/japan-stock-analysis/scripts/xbrl_extract.py) を 2 候補プローブに:

```python
EPS_SUMMARY_ELEMENTS = [
    "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults",  # IFRS
    "BasicEarningsLossPerShareSummaryOfBusinessResults",       # JGAAP
    # Diluted は MUFG 8306 のように Basic が無い場合の fallback
    "DilutedEarningsPerShareIFRSSummaryOfBusinessResults",
    "DilutedEarningsPerShareSummaryOfBusinessResults",
]

def extract_restated_eps_from_zip(zip_path: Path, edinet_code: str) -> dict[int, float]:
    ...
    out: dict[int, float] = {}
    for offset, ctx in SUMMARY_CONTEXTS:
        for elem_name in EPS_SUMMARY_ELEMENTS:
            value, _, _ = get_fact(tree, nsmap, "jpcrp_cor", elem_name, ctx)
            if value is not None:
                out[offset] = float(value)
                break  # 最初にヒットしたものを採用
    return out
```

これだけで:
- IFRS 銘柄: 従来通り IFRS Basic を採用
- JGAAP 銘柄: IFRS Basic 不在 → JGAAP Basic にフォールバック
- MUFG 8306 のような Basic 不在ケース: Diluted に fallback

副作用:
- フォールバック採用時は `resolved_by_fallback: "jgaap"` のような audit フィールドを出力 JSON に追加すべき（既存の `resolved_by: "llm"` と並ぶ）
- mapping_resolver の手動マッピング（MUFG 8306 で行った `DilutedEarningsPerShareSummaryOfBusinessResults` 採用）は不要になる

### 副次的修正: warning メッセージ

`pipeline.py` の warning メッセージは「5 年窓外」と表示しているが、実態が「restated EPS 自体が取れない」場合は別メッセージにすべき:

```python
if not split_adjust.restated_eps:
    warnings.append(
        "split_adjust could not extract any restated EPS from the latest "
        "report (extract_restated_eps_from_zip returned empty). "
        "PER will be NaN for all periods."
    )
elif missing:
    warnings.append(
        f"PER is NaN for periods outside the restated EPS coverage: {missing}."
    )
```

## 関連

- 関連 enhancement: [enhancements/2026-05-23_jgaap_eps_summary_fallback.md](../enhancements/2026-05-23_jgaap_eps_summary_fallback.md)
- 関連 bug (PBR 系): まだ独立 bug 化していないが、SharesOutstanding も同様に IFRS 一択になっている可能性が高い
- 元の議論: [skills/japan-stock-analysis/README.md §D](../skills/japan-stock-analysis/README.md)、[docs/p9_smoke_results.md](../skills/japan-stock-analysis/docs/p9_smoke_results.md) §3
- 過去 commit: `7c66bbf feat(skill): P8 — SKILL.md handbook and XBRL mapping LLM escalation` で問題は認識済みだが対応未了
