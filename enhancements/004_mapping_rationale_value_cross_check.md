# ENH-004: mapping rationale / aggregate 中の数値と候補ペイロード実値の自動照合

## ステータス

完了（検証待ち）

## 起票日

2026-05-31

## 種別

改善

## 概要

AI 判定経路に「もっともらしいが実データにない数値」が混入するリスクを抑える。本システムは AI 介在型 Skill であり、揺れの吸収は本来 AI 判定（ナレッジ＋候補ペイロードを読んで根拠付きで選ぶ）に委ねる設計（[SKILL.md](../skills/japan-stock-analysis/SKILL.md) §6）。よって**主たる対処は SKILL.md のガイド強化**（rationale には候補ペイロードの実 `sample_value` のみを引用し、推測値・暗算値を書かないと明示）とし、**コード側は二重防御としての軽い警告のみ**を担う。機械的な保存拒否ガードは設けない（誤検知・ENH-003 との整合コスト・非決定性のため過剰）。

## 背景・動機

manual_test_02 で、AI は初回 mapping に実データ未確認の捏造値を書き込んでいた（[history.md](../manual_test_02/history.md) L4623 付近）:

- `InterestBearingDebt`: 「bonds (250B) + long-term (180B) + short-term (120B) = 550B」→ 実値は BondsPayable=651.4B / LongTermLoansPayable=577.8B / ShortTermLoansPayable=11.0B で、250/180/120 はどの実値とも一致しない。
- `EarningsPerShare`: 「Value 171.79 matches jppfs fallback」「IFRS variant」→ 東京ガスは JGAAP、候補 EPS は 192.22 のみ。171.79 は実在しない。
- `FinancingCF: 94,621,000,000` / `InvestingCF: -411,234,000,000` → 実値（-255,979M / -263,526M）と全く異なる。

この mapping は `mapping_resolver._cmd_save` のフォーマット検証（`element`/`context`/`rationale` 必須）に**たまたま**引っかかって保存に失敗し、AI が作り直した。しかしフォーマットが合っていれば根拠不明の合算値が保存・採用されていた可能性がある。SKILL.md §6.4 は「rationale を残せ」とは言うが、rationale 中の数値が候補ペイロードの実値に一致することを機械的に検証する仕組みはなく、AI の自己申告依存。

## 要件

**主: SKILL.md ガイド強化（AI 介在側）**
- §6.2 手順3（判定）/ §6.4（注意）に、「rationale に書く数値は必ず候補ペイロードの実 `sample_value` を引用する。読み取った実値以外の推測値・暗算値・合算結果を rationale に書かない」旨を明記する。
- aggregate（[ENH-003](003_aggregate_mappings.md)）導入後は、構成要素として挙げる各値が候補ペイロードに実在する sample_value であることを AI 自身が確認する手順を加える（合算後の値は計算結果なので別扱い）。
- 「判定に使える実値が候補ペイロードに無い項目は、無理に値を作らず §6.3 の `unresolved[]` に逃がす」ことを再強調する。

**副: コード側の軽い警告（二重防御・保存はブロックしない）**
- `mapping_resolver.py save` に、直前のエスカレーションペイロード（既に CWD に出ている `mapping_escalation_*.json`）を任意で渡せる導線を設ける。
- 渡された場合のみ、保存ペイロードの rationale 文字列中の数値・aggregate 構成要素の値を抽出し、候補ペイロードの `sample_value` 集合と許容誤差内で照合する。いずれの実値とも一致しない数値があれば `_emit` 出力に warning を含める。
- **保存はブロックしない**（誤検知や合算後の値で正当な保存を止めないため）。警告は AI/ユーザーへの気付きに留める。

## 影響範囲

- `SKILL.md` §6.2 / §6.4: 実値引用ルールの明記（主たる対処）
- `scripts/mapping_resolver.py`: `_cmd_save`（[mapping_resolver.py:132](../skills/japan-stock-analysis/scripts/mapping_resolver.py#L132)）への `--escalation-json` 追加と軽い照合・warning（副）、`build_escalation_payload`（[mapping_resolver.py:88](../skills/japan-stock-analysis/scripts/mapping_resolver.py#L88)）が持つ `candidates: (element, context, sample_value)` の再利用

## 実現案

### 案1: SKILL.md ガイド主体 + 軽いコード警告（採用）

上記「要件」のとおり、AI への実値引用指示を主とし、コードは渡されたエスカレーションペイロードとの照合 warning のみを担う。本システムの AI 介在思想に沿い、機械的ガードの過剰実装を避けつつ最後の気付きを与える。

### 案2: コードによる機械的ガード（保存拒否）— 不採用

`save` 時に sample_value と一致しない数値があれば保存を拒否する強制ガード。確実だが、aggregate の合算値や正当な派生値での誤検知が多く、AI 介在思想に逆行し ENH-003 との整合コストも高い。本件では採らない。

> aggregate（[ENH-003](003_aggregate_mappings.md)）と密接に関わるため、コード側照合を実装する際は ENH-003 の設計を先に確定させ、「構成要素は実値・合算結果は計算値」の区別を前提にすること。

## 対応

案1（SKILL.md ガイド主体 + 軽いコード警告）を採用。

**主: SKILL.md ガイド**
- §6.2 手順3 に「rationale には実値だけを書く」ルールを追加（候補ペイロードの実 `sample_value` のみ引用、推測値・暗算合算値・記憶値の禁止、aggregate 構成要素は実値確認、無ければ `unresolved[]` へ）。
- §6.2 手順4（保存）のコマンド例に `--escalation-json <候補ペイロード>` を追加し、`value_check_warnings` が出たら rationale を直して save し直す旨を明記。
- §6.4 注意に、実値引用ルールと `--escalation-json` 照合の活用を一文追加。

**副: コード側の軽い警告（保存はブロックしない）**
- `scripts/mapping_resolver.py`:
  - `_parse_numbers` / `_sample_values` / `_value_matches_payload` / `check_rationale_values` / `_load_candidates` を追加。rationale 中の金額相当の数値（10 以上、桁区切り許容）を抽出し、候補 `sample_value` と相対誤差 1% で照合、未一致を warning 化。
  - `_cmd_save` に `--escalation-json` を追加し、渡された場合のみ照合。結果を出力 JSON の `value_check_warnings` に含める。**保存は常に成功させる**（誤検知・合算結果での誤ブロックを避けるため）。
  - CLI `save` サブコマンドに `--escalation-json` 引数を追加。
- `tests/test_mapping_resolver.py`: `check_rationale_values` の捏造検知/実値スルー/候補なし無音、CLI `--escalation-json` 経由で `value_check_warnings` が出ても save 成功する、の 4 ケースを追加。

機械的な保存拒否ガード（案2）は不採用。aggregate 合算値等での誤検知と AI 介在思想への逆行を避けた。

## 関連

- レビュー: [manual_test_02/review_report.md](../manual_test_02/review_report.md) §3.2
- [ENH-003](003_aggregate_mappings.md): aggregate mapping（照合対象設計に影響）
- `SKILL.md` §6（AI 動的解決手順）
