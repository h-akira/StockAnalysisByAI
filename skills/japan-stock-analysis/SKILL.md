---
name: japan-stock-analysis
description: 日本株（4桁証券コード指定）の財務三表・指標・バリュエーション推移を EDINET と yfinance から取得し、HTML レポートを生成する。1〜数社（〜10社）の個別分析向け。多銘柄スクリーニングは対象外。
when_to_use: ユーザーが日本の上場企業（4桁証券コード）の財務分析・PER/PBR/ROE 等のバリュエーション推移・複数社比較を依頼したとき。「7203を分析して」「トヨタとソニーを比較」「6758の最近の財務を見たい」等のリクエスト。
allowed-tools: Bash(python3 *) Bash(test *) Read
---

USER_CWD: !`pwd`

# japan-stock-analysis

> **重要**: 上記 `USER_CWD` 行は SKILL.md ロード時に動的展開されるユーザーの起動時 CWD。
> 以降の analyze / mapping_resolver 等の Bash 呼び出しでは **必ず `--output-dir <USER_CWD の実値>` を明示する**こと。
> 例: USER_CWD が `/Users/foo/work/proj` であれば `--output-dir /Users/foo/work/proj` を渡す。
> これにより成果物 (`report_*.html` / `data_*.json` / `mapping_escalation_*.json`) が
> Skill 配下ではなくユーザーの作業ディレクトリに確実に落ちる ([BUG-001](../../bugs/001_output_lands_in_skill_dir_not_cwd.md))。

## 1. 目的と前提

**できること**
- 銘柄コード（4桁）から、財務三表（PL/BS/CF）・主要指標・バリュエーション推移を取得しHTMLレポートを生成
- 1〜数社（同時〜10社程度）の比較分析
- データ出所は EDINET（一次情報・財務本体）と yfinance（最新株価・PER/PBR スナップショット補完）

**できないこと**
- 多銘柄スクリーニング（PER<15 等の条件抽出）
- リアルタイム株価、信用残・空売り情報
- セクター/業種別ベンチマーク

**実行モデル**
- 全コマンドは `${CLAUDE_SKILL_DIR}` 絶対パスで起動する（Claude Code が SKILL.md 実行時に自動セットする環境変数）
- CWD はユーザーの作業ディレクトリのまま → 成果物は CWD に落ちる
- キャッシュ・XBRLデータ・restated EPSマッピングは Skill 配下 `cache/` に保持（gitignore）

## 2. 入力受付ルール

ユーザー発話から **4桁の証券コード**を抽出する。

- `7203` → `["7203"]`
- `7203 と 6758 を比較して` → `["7203", "6758"]`
- `トヨタを分析` → 銘柄名から推定できる場合は `["7203"]`、確信が無ければユーザーに4桁を確認
- 4桁未満や5桁以上の数字、複数株式市場のコードが混ざっている場合は、ユーザーに正確な4桁コードを確認

複数銘柄指定時は、比較ビュー（売上高・ROE・営業利益率・PER の重ね描き）も同じ HTML に組み込まれる。

## 3. 環境準備

### 3.1 secret.json 存在チェック

```bash
test -f ${CLAUDE_SKILL_DIR}/secret.json && echo OK || echo "MISSING"
```

`MISSING` なら、ユーザーに以下を案内して配置を依頼してから先に進む:

> EDINET API キーを取得し、`${CLAUDE_SKILL_DIR}/secret.json` に次の形式で配置してください:
> ```json
> {"edinet": {"api_key": "<your key>"}}
> ```
> このファイルは `.gitignore` 済みです。誤コミットの恐れはありません。

### 3.2 venv と依存

初回のみ (cd しない・全パス絶対化。BUG-001 対策):

```bash
python3 -m venv ${CLAUDE_SKILL_DIR}/env
${CLAUDE_SKILL_DIR}/env/bin/pip install -r ${CLAUDE_SKILL_DIR}/requirements.txt
```

以降は `${CLAUDE_SKILL_DIR}/env/bin/python3` を Python 実行に使う（システム Python だと依存が見つからない）。

### 3.3 cache 状態の確認

```bash
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info
```

返り値 JSON の `documents.count` が小さい / 0 の場合は bootstrap 未完了。`§5.2 リカバリ - needs_bootstrap` の手順を参照。

## 4. 実行手順

### 4.1 基本フロー

`--output-dir <USER_CWD>` (冒頭の USER_CWD 実値) を必ず明示する:

```bash
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze \
  --sec-code <code> \
  --output-dir <USER_CWD>
```

複数銘柄比較:
```bash
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze \
  --sec-code <code1> <code2> \
  --output-dir <USER_CWD>
```

主要オプション:
- `--output-dir <path>`: 成果物の出力先（必須相当 — 上記 USER_CWD を渡す）
- `--years N`: bootstrap 完備チェックの対象年数（default 10）
- `--no-yfinance`: 株価フェッチをスキップ（PER/PBR が NaN になる）
- `--force-refresh`: 該当銘柄の派生キャッシュ（derived / prices / split-adjust）を破棄して再計算

`--output-dir` を省略した場合は実行時の CWD にフォールバックするが、CWD が Skill 配下を指していると analyze は `status: "error"` で停止する（BUG-001 防御）。

### 4.2 標準出力 JSON のステータス分岐

`pipeline.py analyze` は JSON を標準出力に1つ出して終了する。**`status` フィールドで分岐する**:

| status | 意味 | 対応 |
|--------|------|------|
| `success` | 成功 | `outputs.html` と `outputs.data_json` のファイルパスをユーザーに提示 |
| `needs_bootstrap` | bootstrap が必要 | §5.2 参照 |
| `needs_mapping` | XBRL要素マッピングが未解決 | §6 AI エスカレーションへ |
| `config_error` | secret.json 関連 | §5.1 参照 |
| `error` | その他 | `reason` を読んでユーザーに案内 |

### 4.3 初回 bootstrap（重い処理。ユーザー確認の上で実行）

```bash
# 一気通貫（過去10年・約2,500 API リクエスト。1秒/req で約40分）
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py init

# 段階実行（途中中断や再開を見越したい場合）
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py refresh-company-map
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py fetch-documents --years 10 --chunk 0/10
# --chunk 1/10, 2/10, ... と分割実行可能。各 chunk は独立に再実行可（既存ファイルはスキップ）
```

bootstrap は時間がかかるため、**実行前にユーザーに必ず確認**する。

EDINET API のレート制限は公式に明示されていない（pre-research 検証では 1秒間隔で安定動作）。
429 が返ったら内部リトライ（指数バックオフ、最大3回）で対応する。

### 4.4 キャッシュ操作

```bash
# 全体状態
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info

# 銘柄別状態
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info --sec-code 7203

# 派生キャッシュのみ削除（再計算で復元可、--confirm 不要）
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --derived
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --sec-code 7203

# 高コストキャッシュ削除（API再取得が必要、--confirm 必須）
${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --documents --confirm
```

詳細フラグは [scripts/cache_admin.py](scripts/cache_admin.py) の docstring を参照。

## 5. 失敗時のリカバリ

### 5.1 config_error (secret.json 関連)

`status: "config_error"` の `reason` がそのままユーザーに伝える文言。`§3.1 secret.json 存在チェック`の案内に従って配置を依頼する。

### 5.2 needs_bootstrap

応答例:
```json
{
  "status": "needs_bootstrap",
  "per_code": [{
    "sec_code": "7203",
    "missing_weekday_count": 221,
    "missing_window_sample": ["2016-05-25", "2016-05-26", "...", "..."],
    "suggested_command": "python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py fetch-documents --years 10"
  }]
}
```

対応:
1. `missing_weekday_count` が大きい場合（数百〜2000+）→ **初回 bootstrap 未完了**。ユーザーに `§4.3` の手順を提案
2. 小さい場合（数〜数十）→ **直近の追加 bootstrap が必要**。`bootstrap fetch-documents --years <推奨>` を実行
3. ユーザーが「直近1〜3年だけ見たい」場合は `pipeline analyze --sec-code <code> --years 1` のように `--years` を小さく指定する選択肢を提示

### 5.3 EDINET API エラー（429・5xx・ネットワーク失敗）

bootstrap や XBRL ダウンロード時に内部で **指数バックオフリトライ（最大3回）** が走る。それでも失敗した場合:

- `bootstrap fetch-documents` の `--max-errors N` で許容失敗数を上げる、または `--chunk K/M` で範囲を絞る
- 429 が連続するならアクセス間隔を空けて再実行（`--sleep 2.0` 等）
- ネットワーク障害なら `${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info` で `secret.ok` が真であることを確認してから再実行

EDINET API の明示的なレート上限は公式に未公開（pre-research 検証時の野良情報では 3-5 秒間隔推奨。本実装は 1 秒間隔がデフォルト）。

### 5.4 yfinance 失敗

`pipeline analyze` の `warnings` に `yfinance failed: ...` が入っていたら、財務指標は正常で **PER/PBR/StockPrice のみ NaN**。ユーザーに以下を提示:
- このまま受け入れる（財務分析は完走している）
- 後日 `--force-refresh` で yfinance だけ再試行

### 5.5 needs_mapping (XBRL要素未解決) → §6

## 6. XBRL要素マッピングのエスカレーション

### 6.1 発生条件

ホワイトリスト（[scripts/xbrl_extract.py](scripts/xbrl_extract.py) の `PATH_A_ITEMS` / `PATH_B_ITEMS`）に該当しない要素を持つ銘柄（典型: 銀行業 8306 / 保険業 8766 等の業種固有勘定科目）を analyze すると、`pipeline analyze` が次のステータスを返す:

```json
{
  "status": "needs_mapping",
  "per_code": [{
    "sec_code": "8306",
    "unresolved": ["NetSales", "OperatingIncome", ...],
    "candidates_payload": "/tmp/.../mapping_escalation_8306.json",
    "knowledge_path": "<SKILL_ROOT>/docs/xbrl_variation_knowledge.md",
    "suggested_command": "<エスカレーション完了後の再実行コマンド>"
  }]
}
```

### 6.2 Claude が行う手順

1. **ナレッジを読む**:
   ```
   Read: ${CLAUDE_SKILL_DIR}/docs/xbrl_variation_knowledge.md
   ```
   業種別の典型的なマッピング候補（銀行=OrdinaryIncome、保険=OrdinaryRevenue 等）と XBRL 名前空間の意味が記載されている。

2. **未解決要素一覧 + 候補ペイロードを読む**:
   ```
   Read: <candidates_payload のパス>
   ```
   このファイルには「未解決項目 (NetSales 等) ごとに、その XBRL に実在する候補要素名・サンプル値・コンテキストID」が並んでいる。

3. **判定する**:
   各未解決項目について、ナレッジに照らして適切な要素を **1つ** 選ぶ。判定根拠 (どの要素を選び、なぜか) を必ず残す。

4. **保存する**:
   ```bash
   ${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/mapping_resolver.py save \
     --sec-code 8306 \
     --mapping-json <Claudeが組み立てた JSON ファイルのパス>
   ```
   保存形式は [docs/xbrl_variation_knowledge.md](docs/xbrl_variation_knowledge.md) の §マッピングJSONフォーマット を参照。

5. **再実行**:
   ```bash
   ${CLAUDE_SKILL_DIR}/env/bin/python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze \
     --sec-code 8306 \
     --output-dir <USER_CWD>
   ```
   2回目以降は `cache/mappings/8306.json` がヒットして AI 介入なしで分析が走る。

### 6.3 取得不能な項目を「意図的に未解決」とする

XBRL に該当要素が存在しないケース（例: 銀行業の OperatingCF/InvestingCF/FinancingCF
は単独要素として開示されず、明細だけしか出ない）では、Claude は判定不能。
そういう項目は **mapping JSON の `unresolved` 配列に明示**する:

```json
{
  ...
  "mappings": { /* 解決できた項目だけ */ },
  "unresolved": ["OperatingCF", "InvestingCF", "FinancingCF"]
}
```

`unresolved[]` に入った項目は以降の analyze で **NaN として許容**され、
needs_mapping は再発しない。warnings に
`"Mapping intentionally leaves [...] unresolved; those fields are emitted as NaN."`
が出るので、ユーザーに「該当項目はこの銘柄では取れません」と明示すること。

### 6.4 注意

- Claudeのマッピング判定はナレッジに無い業種で **誤マッピングのリスクがある**。判定根拠 (`rationale`) を必ず残し、JSON出力の `metrics.PER` 等は `resolved_by: llm` フラグで人間レビューを促すこと
- 同一企業・同一業種でも会計基準が IFRS↔JGAAP で切り替わるとマッピングが変わる可能性あり
- 業種固有の集計値が XBRL に無い場合は **§6.3 の `unresolved[]` パターン**を使う（無理に近似マッピングしない）

## 7. 出力の解釈

成功時:
```json
{
  "status": "success",
  "sec_codes": ["7203"],
  "outputs": {
    "html": "<CWD>/report_7203.html",
    "data_json": {"7203": "<CWD>/data_7203.json"},
    "per_code": [{
      "sec_code": "7203",
      "fiscal_years": ["2025-03-31"],
      "split_adjust_source_doc_id": "S100VWVY",
      "warnings": []
    }]
  },
  "warnings": [...]
}
```

ユーザーへの提示テンプレート:

> 分析が完了しました。
> - HTML レポート: [report_7203.html](file:///path/to/report_7203.html)
> - 構造化データ (JSON): [data_7203.json](file:///path/to/data_7203.json)
> - 対象期: FY2024 (2025-03-31)
> - restated EPS の出処: 有報 S100VWVY

`warnings` がある場合は併せて提示し、特に「PER NaN」や「分割未補正期」「mapping LLM 判定」が含まれていれば**強調する**。

`data_*.json` のスキーマは [docs/json_schema.md](docs/json_schema.md) を参照。

## 8. 既知の制限事項

設計検証（このSkill 開発時の実証）で確定した制約事項:

- **PBR は分割未補正**: SharesOutstanding に restated 形式が無いため、株式分割をまたぐ期で歪む（[docs/json_schema.md](docs/json_schema.md) 既知の制約を参照）
- **5年超の期間**: restated EPS が無いため PER は NaN + warning
- **会計基準切替期**: 同一銘柄の年度間で IFRS↔JGAAP が変わると数値が連続しない可能性あり
- **月次決算 (4/5/6月決算)**: FY ラベルが1年ズレる可能性あり（多くの3月/12月決算では問題なし）
- **EDINET API レート制限**: 公式仕様書に上限の明記なし。本実装は 1秒間隔がデフォルトで pre-research にて安定動作実証済み。429 リトライ機構あり
- **業種固有マッピングは初回 AI 介入が必要**: 銀行・保険等の業種は §6 のエスカレーションを経て `cache/mappings/{sec_code}.json` を作成、以降はキャッシュヒット
