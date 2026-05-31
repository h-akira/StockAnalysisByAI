# ENH-005: 単一銘柄レポートのグラフ軸設計の是正

## ステータス

完了（検証待ち）

## 起票日

2026-05-31

## 種別

改良

## 概要

`html_report.py:build_single` の単一銘柄レポートは、PER と PBR を同一軸（row=4）、ROE・自己資本比率・営業利益率を同一軸（row=3）に重ね描きしており、スケール差・水準帯の違いで一部指標の推移が読み取れない。データは正しく出力されているが可視化で情報が失われている。軸設計を是正する。

## 背景・動機

`scripts/html_report.py:build_single`（[html_report.py:60-84](../skills/japan-stock-analysis/scripts/html_report.py#L60-L84)）は 4 段サブプロット構成:

| row | 内容 | 問題 |
|---|---|---|
| 1 | 売上高（兆円・棒） | OK |
| 2 | 営業利益・当期純利益（兆円・棒） | OK |
| 3 | ROE・自己資本比率・営業利益率（%・線）を同一軸 | 水準帯が違う |
| 4 | PER・PBR（倍）を同一軸 | スケール差で PBR が潰れる |

**問題A: PER と PBR の同一軸（row=4・最も深刻）**
東京ガス実データで PER=3.86〜24.78 倍、PBR=0.68〜1.15 倍。約 20 倍のスケール差があり Y 軸が PER に支配され、PBR の線が軸最下部にほぼ平坦に張り付き推移が読めない。PBR が 0.68→1.03 と 1.5 倍に動いた情報がグラフ上で失われている。

**問題B: ROE・自己資本比率・営業利益率の同一軸（row=3）**
3 つとも単位は「%」だが水準帯と意味が異なる:
- 自己資本比率: 39〜50%（財務安全性・年変動小）
- ROE: 4.0〜17.7%（収益性・年変動大）
- 営業利益率: 5.0〜12.8%（収益性・年変動中）

「%だから同じ軸でよい」は短絡で、自己資本比率（高位）が上方に張り付き ROE/営業利益率の小さな変動が下方に圧縮される。

> なお比較ビュー（`build_comparison`, [html_report.py:87-118](../skills/japan-stock-analysis/scripts/html_report.py#L87-L118)）は ROE/営業利益率/PER をそれぞれ別サブプロットに分けており軸混在の問題はない。単一銘柄ビューだけが指標を詰め込んでいる。

## 要件

- PER と PBR を別サブプロットに分離する（または PBR を二軸 secondary_y 右側に逃がす）。PER/PBR は意味が異なるので別段が素直。
- row=3 の 3 指標を性質で束ね直す: 「安全性（自己資本比率・将来 DERatio）」と「収益性（ROE・営業利益率）」に分離する、または自己資本比率を二軸右側に逃がす。ROE と営業利益率は水準が近く意味も収益性で揃うため同軸でも比較的妥当。
- DERatio は現状 null（[BUG-004](../bugs/004_interest_bearing_debt_needs_aggregate.md)）だが、IBD が取れれば安全性段に同居させたい指標。
- 比較ビューの分離方式を参考にできる。

## 影響範囲

- `scripts/html_report.py`: `build_single`（サブプロット構成・row 数・`make_subplots` の specs/secondary_y 設定）
- サブプロット数が増える場合は `height` の調整
- `templates/` への影響（埋め込み HTML 数が変わる場合）は要確認

## 実現案

### 案1: サブプロットを増やして指標を分離（推奨）

row を増やし、PER と PBR を別段、安全性指標と収益性指標を別段にする。実装が単純で各指標が独立スケールを持てる。比較ビューと一貫した方針。

### 案2: secondary_y による二軸化

row 数は維持し、PBR を右軸、自己資本比率を右軸に逃がす。グラフ段数を増やさず縦長化を避けられるが、二軸は読み手に軸対応の認知負荷がある。

> `build_single` の局所変更で対応可能。まず案1（分離）を基本とし、縦長を嫌う場合に案2 を検討。

## 対応

案1（サブプロット分離）を基本に、安全性段のみ案2（二軸）を併用した。`scripts/html_report.py` の `build_single` を 4 段 → 6 段構成に変更:

- row1: 売上高（兆円・棒）
- row2: 営業利益・当期純利益（兆円・棒）
- row3: 収益性（ROE・営業利益率、%・線）— 水準が近く意味も収益性で揃うため同軸維持
- row4: 安全性（自己資本比率 %=左軸、D/Eレシオ 倍=右軸 `secondary_y`）— 単位の異なる 2 指標を二軸で分離
- row5: PER（倍・線）— PBR と分離
- row6: PBR（倍・線）— PER と分離（約 20 倍のスケール差で潰れる問題を解消）

`height` を 1400 → 1900 に拡大。`make_subplots` の row4 のみ `specs=[{"secondary_y": True}]` を指定し、`update_yaxes` で左右軸のタイトル（% / 倍）を付与。比較ビュー（`build_comparison`）は元々分離済みのため変更なし。

DERatio は IBD 未解決（[BUG-004](../bugs/004_interest_bearing_debt_needs_aggregate.md)）の銘柄では全期 null になるが、Plotly は欠損として扱い線が描かれないだけで安全性段の自己資本比率は正常に出る。IBD が解決されれば D/E も同段に描画される。

## 関連

- レビュー: [manual_test_02/review_report.md](../manual_test_02/review_report.md) §3.5
- [BUG-004](../bugs/004_interest_bearing_debt_needs_aggregate.md): DERatio が null（安全性段に同居させたい指標）
