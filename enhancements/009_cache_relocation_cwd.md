# ENH-009: 銘柄固有キャッシュを CWD へ移し、グローバルキャッシュは bootstrap のみにする

## ステータス

未着手

## 起票日

2026-05-31

## 種別

改善

## 概要

Skill 配下 `cache/` に一括して置いている各種キャッシュのうち、**銘柄固有のもの（`xbrl/` `derived/` `mappings/` `split_adjust/` `prices/`）をユーザー CWD へ移し**、Skill 配下にグローバルで持つのは **bootstrap 由来の全社共通キャッシュ（`documents/` ＋ `company_map.csv`）だけ**にする。ENH-007（成果物・加工を CWD に集約する方針）と整合させ、「CWD ＝ 1 銘柄分析の作業場、Skill 配下 ＝ 全銘柄共通の重い土台だけ」と概念を単純化する。

## 背景・動機

[ENH-007](007_ai_driven_report_layer.md) で、AI による補正・加工結果（代替 JSON）・生成スクリプト・レポートを
**ユーザー CWD に集約**する方針にした。すると「一次データ（derived/split_adjust/mappings 等）は Skill 配下
cache、補正結果は CWD」と銘柄固有データの置き場が二分され、概念が分かりにくい。

[architecture.md](../architecture.md) のキャッシュ表は、bootstrap キャッシュ（`documents/` ＋
`company_map.csv`）が「重く（取得 ~40 分・~600MB）・全社共通・銘柄横断で必須」なのに対し、
銘柄固有キャッシュは「その銘柄の分析にしか使わない」ことを示している。

**決定的な前提（開発者確認済み）: 別プロジェクト（別 CWD）で同じ銘柄を調べることは想定しない。**
したがって銘柄固有キャッシュを CWD に置いても「別 CWD で同一銘柄を再分析する際の再 DL・再 AI 判定」は
発生せず、CWD ローカル化のデメリットは実質ない。むしろ:

- Skill 配下が肥大化しない（XBRL zip 等が貯まらない。配布物がクリーンに保たれる）。
- 1 銘柄分析に関わるもの（一次データ・補正・スクリプト・レポート）が**すべて CWD に集まり**、
  プロジェクト単位で完結・破棄しやすい。
- bootstrap キャッシュだけが「重いので使い回すグローバル資産」と明確になり、手動テスト時の使い回し規律
  （[AGENTS.md](../AGENTS.md) §手動テスト）とも一致する。

## 要件

- **グローバル（Skill 配下 `cache/`）に残すもの**: `documents/`（日付単位・全社共通）、`company_map.csv`。
- **CWD に移すもの**: `xbrl/`、`derived/`、`mappings/`、`split_adjust/`、`prices/`。配置は
  **`.japan-stock/cache/` 配下**（CWD 直下の隠し作業ディレクトリ。[ENH-007](007_ai_driven_report_layer.md) R3 /
  [architecture.md](../architecture.md) §6 の CWD レイアウトと共通）。成果物（report/data）は CWD 直下に残し、
  作業物（キャッシュ・スクリプト）は `.japan-stock/` にまとめて隠す。`.japan-stock/` は gitignore 推奨。
- `scripts/paths.py` のパス解決を、グローバル分（`DOCUMENTS_DIR` / `COMPANY_MAP`）は `SKILL_ROOT/cache`、
  銘柄固有分（`XBRL_DIR` / `DERIVED_DIR` / `MAPPINGS_DIR` / `SPLIT_ADJUST_DIR` / `PRICES_DIR`）は
  `output_dir()`（CWD）配下、と分けて解決するよう変更する。
- `ensure_cache_dirs()` も二系統（グローバル／CWD）を作るよう調整。
- 別 CWD で同一銘柄を再分析することは想定しないため、CWD 側キャッシュの横断共有は考慮しない。
- 手動テスト（`manual_test_*/`）の前提も更新: グローバルにコピーするのは引き続き bootstrap 分のみ。
  銘柄固有キャッシュは各 CWD（テストディレクトリ）に生成・破棄される。

## 影響範囲

- `scripts/paths.py`: キャッシュパスをグローバル／CWD の二系統に分離。
- `scripts/pipeline.py`・`scripts/xbrl_extract.py`・`scripts/timeseries.py`・`scripts/metrics.py`・
  `scripts/split_adjust.py`・`scripts/mapping_resolver.py`・`scripts/stock_price.py`・`scripts/cache_admin.py`:
  これらが参照するキャッシュパスの解決元が変わる（多くは `paths.py` 経由なので影響は paths に集約できる想定）。
- `cache_admin.py info/clear`: グローバル／CWD の双方を見るよう調整。
- `.gitignore`（CWD 側のキャッシュ生成物の無視。[BUG-010](../bugs/010_manual_test_numbered_dirs_not_gitignored.md) と同様、
  CWD 成果物扱い）。
- `architecture.md` §6 キャッシュ設計、[AGENTS.md](../AGENTS.md) §手動テスト、`docs/json_schema.md`（出力近傍の記述）。
- [SKILL.md](../skills/japan-stock-analysis/SKILL.md): キャッシュ場所の説明（§3 cache 状態確認 等）。

## 実現案

### 案1: paths.py で二系統に分離（推奨）

グローバル分は `SKILL_ROOT/cache`、銘柄固有分は `output_dir()`（CWD）配下に解決するよう `paths.py` を
変更し、各モジュールは引き続き `paths.*` を参照するだけにする。変更の大半を paths.py に集約でき、
呼び出し側の改修を最小化できる。

### 案2: 段階移行（mappings だけ先に CWD）

影響の大きい一括移行を避け、まず再生成コストの低い `derived/split_adjust/prices` を CWD に移し、
`xbrl/mappings` は様子を見る。ただし「別 CWD で同一銘柄を見ない」前提なら一括移行で問題ないため、
段階移行の必要性は薄い。

> 「別 CWD で同一銘柄を再分析しない」前提が確定しているので、案1（一括で二系統に分離）が素直。

## 既存キャッシュ機構との競合確認

- **競合は無い**。現状のキャッシュ機構（doc_list が documents を読む／xbrl_extract が zip をキャッシュ／
  split_adjust・mappings が銘柄 JSON をキャッシュ）はパス解決を `paths.py` に集約しているため、
  配置先を変えるだけで仕組み自体は変わらない。
- ENH-007 とも整合（むしろ補完）: ENH-007 は補正結果・スクリプト・レポートを CWD に集約する方針で、
  本 enhancement は一次データのキャッシュも CWD に寄せることで「銘柄固有はすべて CWD」を完成させる。

## 決定事項・未確定事項

確定済み（ENH-007 と共通）:
- CWD 側キャッシュの置き場は **`.japan-stock/cache/`**（成果物は CWD 直下、作業物は `.japan-stock/` に隠す）。
- gitignore は **`.japan-stock/` を無視**（実利用 CWD でユーザーのリポジトリを汚さない。手動テストは
  `manual_test_*/` で一括無視）。

未確定（実装前に詰める）:
- `cache_admin` のグローバル／CWD 双方の扱い・表示（`info`/`clear` が両系統を見るようにする）。
- pytest が CWD 依存でキャッシュ位置を見失わないためのテスト fixtures／一時ディレクトリ戦略
  （`output_dir()` が `Path.cwd()` 依存になるため）。

## 対応

<!-- AI instruction: 完了後に追記するセクション。採用した実現案、または独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- [ENH-007](007_ai_driven_report_layer.md): 成果物・加工を CWD に集約（本 enhancement で一次キャッシュも CWD へ寄せ整合）
- [architecture.md](../architecture.md) §6: キャッシュ設計（グローバル＝bootstrap のみ、を反映する）
- [AGENTS.md](../AGENTS.md) §手動テスト: bootstrap のみ使い回す規律と一致
- [init_plan.md](../init_plan.md) §3.2: 初期のキャッシュ配置方針（不可侵。現行の正は architecture.md）
