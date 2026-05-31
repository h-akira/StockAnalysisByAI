# ENH-006: 検証フェーズの json_schema 参照導線強化と mapping 試行回数の削減

## ステータス

完了（検証待ち）

## 起票日

2026-05-31

## 種別

改善

## 概要

manual_test_02 のセッションで観測された 2 つのプロセス上の冗長さを SKILL.md のガイド強化で抑制する。(1) 成果物の再検証時に data スキーマを把握せず Bash が連続失敗・巻き添えキャンセルした件、(2) AI が良かれと思い mapping を複数回 save→再 analyze して分析が複数回走って見えた件。

## 背景・動機

**(1) 検証時のスキーマ未把握による手戻り（§3.3）**
[history.md](../manual_test_02/history.md) L5776〜L6255 で、CF 値の交差検証や価格キャッシュ確認の Bash が十数回連続で「Cancelled: parallel tool call ... errored」になっている。原因は、並列実行した Bash 群の 1 つが `KeyError`（`fiscal_year` / `currency` という存在しない列・キーへのアクセス）で落ち、同一バッチの残りが巻き添えキャンセルされたため。AI が data_json の実スキーマ（`fiscal_years[].financials.X` 形式）を把握しないまま `d["financials"]` / `d["currency"]` / `fiscal_year` 列を仮定して失敗した。[docs/json_schema.md](../skills/japan-stock-analysis/docs/json_schema.md) を先に読んでいれば避けられた手戻り。SKILL.md §7 は「スキーマは json_schema.md 参照」と書くが、検証時に読む導線が弱い。

**(2) mapping 複数回 save の冗長さ（§3.4）**
東京ガスで mapping を 3 回保存している:
1. 捏造版 → フォーマットエラーで失敗
2. JGAAP 版（SharesOutstanding/InterestBearingDebt を unresolved）→ 成功・analyze 成功
3. SharesOutstanding を追加マッピング → `--force-refresh` で再 analyze

2 で success 後に AI が自発的に「SharesOutstanding は単一要素で取れる」と気付き 3 で精度を上げたのは良い判断だが、ユーザー視点では「分析が 3 回走った」ように見える。[BUG-005](../bugs/005_needs_mapping_loop.md) で「mapping 後の needs_mapping 再発」は対処済みだが、AI が良かれと思って複数回 save→再 analyze する分の冗長さは残る。

## 要件

- SKILL.md §7（検証）に、成果物を再検証する際は data 構造が `fiscal_years[].financials/metrics` 形式であることに留意し [json_schema.md](../skills/japan-stock-analysis/docs/json_schema.md) を参照する旨の一文を追加する。並列 Bash の巻き添えキャンセル多発を抑制。
- SKILL.md §6（AI 動的解決手順）に、最初の判定時点で SharesOutstanding 等の単一要素候補も拾い切るチェックリストを設け、save→再 analyze の往復を減らす。

## 影響範囲

- `SKILL.md` §6（mapping 手順）、§7（検証手順）
- コード変更は不要（手順ドキュメントの改善）

## 実現案

### 案1: SKILL.md のガイド追記（推奨）

§7 にスキーマ参照の一文、§6 に「単一要素候補も初回で拾うチェックリスト」を追記する。低コストで両課題を抑制できる。

### 案2: 検証ヘルパースクリプトの提供

data_json のコア値を安全に読み出す検証用 CLI（スキーマに沿った read）を用意し、AI が ad-hoc な Bash でスキーマを推測せずに済むようにする。より確実だが実装コストがある。将来検討。

## 対応

案1（SKILL.md ガイド追記）を採用。`SKILL.md` を 2 箇所修正:

- **§7（出力の解釈）**: 「成果物を再検証する際の注意」ブロックを追加。`data_*.json` の構造が
  `fiscal_years[].financials/metrics` の入れ子であり `d["financials"]`/`currency`/`fiscal_year`
  といったトップレベルキーは存在しないこと、仮定でキーを当てた並列 Bash が 1 つの KeyError で
  バッチ全体を巻き添えキャンセルさせること、先に json_schema.md で実スキーマを確認することを明記。
- **§6.2 手順3（判定）**: 「初回判定で拾い切る」チェックリストを追加。単一要素で解決できる項目は
  その場で含める／適切な値が無い項目は `unresolved[]` に回す／全項目を 1 回の save で確定する、を明示。

コード変更なし。案2（検証ヘルパー CLI）は将来検討として見送り。

## 関連

- レビュー: [manual_test_02/review_report.md](../manual_test_02/review_report.md) §3.3, §3.4
- [BUG-005](../bugs/005_needs_mapping_loop.md): needs_mapping ループ（対処済み・本件は別の冗長さ）
- [docs/json_schema.md](../skills/japan-stock-analysis/docs/json_schema.md)
