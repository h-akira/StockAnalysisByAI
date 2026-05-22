# EDINET API v2 検証計画

## 目的

日本株の個別銘柄分析基盤として EDINET API v2 を使えるかを検証する。
「証券コード（4桁）を指定したら、その企業の財務三表・指標を過去にさかのぼって取得できる」ことを確認するのがゴール。

---

## ディレクトリ構成

```
pre-research/edinet/
├── step0_verify.py          # 疎通確認 ✅
├── step1_company_map.py     # 証券コード↔EDINETコード マッピング
├── step2_doc_list.py        # 有価証券報告書 一覧取得
├── step3_xbrl_parse.py      # XBRLパース・主要勘定科目抽出
├── step4_timeseries.py      # 複数期の時系列 DataFrame 化
├── step5_metrics.py         # PER/PBR/ROE 等の指標計算
├── step6_html_output.py     # plotly による HTML グラフ出力
├── env/                     # venv（git管理外）
├── requirements.txt         # 依存ライブラリ
├── data/                    # 取得データ・中間ファイル（git管理外）
│   ├── company_map.csv      # 証券コード↔EDINETコード対応表
│   └── cache/               # XBRL zip キャッシュ
├── verification_plan.md     # 本ファイル（計画＋検証結果まとめ）
└── edinet_signup_issue.md   # 登録トラブルメモ
```

## コーディング方針

本検証は**本実装への再現性を重視**する。各スクリプトは以下の基準を満たすこと。

- **WHYを書く**: 仕様上の制約・EDINET固有の挙動・非自明な設計判断には必ずコメントを残す
  - 例: 5桁ゼロ埋め仕様、2行ヘッダのCSV構造、ドメインの使い分け
- **WHATは書かない**: 変数名・関数名から自明なことはコメントしない
- **モジュール docstring**: 各ファイル冒頭に「何を確認するか」「データソースのURL」「実行方法」を明記する
- **合否基準を満たした時点で次へ**: 過度な汎用化・最適化はしない（本実装で行う）

## 検証結果

→ **[verification_results.md](verification_results.md)** に記録する。本ファイルは計画のみ。

## 現在地

- [x] API キー取得
- [x] 書類一覧エンドポイント (`/api/v2/documents.json`) の疎通確認（`step0_verify.py`）
- [x] XBRL zip ダウンロードの疎通確認（`step0_verify.py`）
- [x] Step 1: 証券コード ↔ EDINETコード マッピング（`step1_company_map.py`）
- [x] Step 2: 有価証券報告書 一覧取得（`step2_doc_list.py`、窓スキャン方式）
- [x] Step 3a: XBRL パース・主要勘定科目抽出（`step3a_lxml.py`、9項目取得・2社で実証）
- [x] Step 3 完了判定: 会社間差異のナレッジ化（`xbrl_company_variation.md`）。Step 3b（Arelle）はスコープ外に判断
- [x] Step 4: 複数期の時系列 DataFrame 化（`step4_timeseries.py`、トヨタ3期で実証）
- [x] Step 5: 指標計算（`step5_metrics.py`、PER/PBR/ROE等を二社で実証・株式分割課題を発見）
- [x] Step 6: HTML グラフ出力（`step6_html_output.py`、スタンドアロンHTML・二社比較を実証）
- [ ] Step 7: 株式分割補正手法の選定（`step7_split_adjust.py`、本実装 P4 着手前提）
- [x] Step 1〜6 完了。本実装が P3.5 で Step7 追検証を要求したため再オープン中

---

## 検証ステップ

### Step 1: 証券コード → EDINETコードのマッピング

**確認したいこと**
- EDINET が提供する「提出者一覧 CSV」から証券コード↔EDINETコードの対応表を作れるか
- 例: `7203` → `E02144`（トヨタ）

**確認方法**
- EDINET公式が配布する「EDINETコード一覧 ZIP」を取得・解析する
  - URL: `https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip`
  - APIキー不要、全11,000社超を一括取得可能
  - ※ `/api/v2/documents.json` の `secCode` フィールドや `companies.csv` エンドポイントも調査したが前者は日付ループが必要で非効率、後者は存在しないため採用せず

**合否基準**: 4桁の証券コードからEDINETコードを一意に引ける

---

### Step 2: 有価証券報告書の特定と取得

**確認したいこと**
- 指定した企業の有価証券報告書（年次決算）一覧を過去にさかのぼって列挙できるか
- 書類種別（`docTypeCode`）のフィルタが正しく機能するか

**主な docTypeCode**

| コード | 書類種別 |
|--------|---------|
| `120`  | 有価証券報告書（年次） |
| `140`  | 四半期報告書 |
| `160`  | 半期報告書 |

**確認方法**
- 日付範囲をループして `docTypeCode == "120"` かつ対象 EDINETコードの書類を収集
- 何年分さかのぼれるか確認（仕様上は10年）

**合否基準**: 対象企業の過去10期分の有価証券報告書を一覧化できる

---

### Step 3: XBRLのパースと主要勘定科目の抽出

**確認したいこと**
- zip 内の `.xbrl` ファイルから財務三表の数値を取り出せるか
- 勘定科目名（タクソノミ要素名）の特定方法
- 複数企業で再現できるか・会社間差異はどう吸収するか

**抽出対象（9項目）**
- BS: 総資産、純資産、有利子負債
- PL: 売上高、営業利益、当期純利益、EPS
- CF: 営業CF、投資CF、財務CF、フリーCF

**実施方針（当初計画から見直し）**
- 当初: lxml と Arelle の両方を試して比較する Step 3a / Step 3b 構成
- 実施: Step 3a（lxml）で 2社実証＋会社間差異を文書化、Step 3b は **スコープ外** に判断
- 判断根拠: 会社間差異の本質はタクソノミパースの問題ではなく「**要素名の意味判定**」であり、Arelle でも解決しない。本実装では AI（Agent Skill）による動的解決が筋（→ [xbrl_company_variation.md](xbrl_company_variation.md)）

**合否基準**: 9項目を正しい数値（単位・符号）で取り出せ、**かつ複数企業で再現する**こと

---

### Step 4: 複数期の時系列データ化

**確認したいこと**
- Step 2〜3 を繰り返して複数期分をまとめ、pandas DataFrame にできるか
- 期ずれ（3月決算 vs 12月決算等）の扱い

**合否基準**: 1銘柄・10期分を DataFrame に整形して CSV 出力できる

---

### Step 5: 指標の計算

**確認したいこと**
- Step 4 の DataFrame から PER・PBR・ROE・自己資本比率等を計算できるか
- 株価は yfinance から補完して PER/PBR の時系列を作れるか

**確認方法**
- yfinance で日足株価を取得し、EPS・BPS と突き合わせる

**合否基準**: PER・PBR の過去推移グラフを plotly で HTML 出力できる

---

### Step 6: HTML 出力

**確認したいこと**
- plotly で財務推移・指標グラフをインタラクティブな HTML に出力できるか

**出力イメージ**
- 売上高・営業利益・純利益の棒グラフ（期別）
- PER・PBR の折れ線グラフ（日次 or 四半期）
- ROE・自己資本比率の推移

**合否基準**: ブラウザで開けるスタンドアロン HTML が生成される

---

### Step 7: 株式分割補正の手法選定（本実装 P4 の前提検証）

**背景**
- Step 5 で判明した「EDINET の EPS は報告書提出時点の発行済株式数で焼き付け、yfinance の Close は最新分割比率で遡及調整」という不整合により、分割が報告書提出より後に起きた期で PER/PBR が大きく狂う（Sony 6758 FY2022 で PER=3.16 → 正しくは 14.7）。
- 本実装 P4 の `scripts/split_adjust.py` 実装手法を決めるための実機検証。

**候補手法**
- **(a) restated EPS 方式**: 最新年の有報の SummaryOfBusinessResults（直近5年分の Prior\*YearDuration コンテキスト）から post-split EPS を取得し、各年に当てはめる。Sony FY2022 で **Prior2YearDuration=162.71 → PER=14.7** が pre-research Step5 で実証済み。
- **(b) yfinance.Ticker.splits 方式**: yfinance から累積分割比率を取得し、各年の raw EPS を割って統一。データソースが yfinance に一元化される利点があるが、**`Ticker.splits` 自体の挙動は未検証**。

**確認したいこと**

1. **yfinance.Ticker.splits の信頼性**:
   - TSE上場銘柄（`.T` ティッカー）で分割履歴が取れるか
   - 複数回分割があった銘柄で累積比率を正しく合成できるか
   - 5年より古い分割も取れるか
   - 株式併合（reverse split）があった場合の符号
2. **(a) と (b) の PER 一致**: Sony 6758 の FY2020〜FY2024 を両手法で計算し、PER が一致するか（誤差±1%以内が目安）
3. **(a) の射程**: SummaryOfBusinessResults は直近5年分のため、6年以上前の期は (a) では救えないことを実機確認
4. **エッジケース**: 分割実施年（FY中に分割があった期）の扱い、(a)/(b) で違いが出るか

**検証対象銘柄**
- **Sony 6758**: 2024-10-01 に 1:5 分割（確定済み）。FY2020〜FY2024 を対象に両手法を比較
- 初期検証は Sony 1 社に絞る。Step7 結果次第で追加銘柄を検討する（複数回分割／株式併合のエッジケースは将来の宿題として残し、本 Step では深掘りしない）

**実装方針**
- `pre-research/edinet/step7_split_adjust.py` 新設
- 既存の step5_metrics.py を流用しつつ、(a) と (b) 両方の PER を並べて出力
- 出力: `data/split_adjust_{sec_code}.csv` に
  `period_end, raw_eps, restated_eps_(a), split_ratio_(b), per_raw, per_a, per_b, agreement`
  カラムを並べる

**合否基準**
- (a) と (b) の PER が Sony 6758 の FY2020〜FY2024 で概ね一致する（誤差±1%以内）
- yfinance.Ticker.splits が Sony 6758 で動くことを確認（1:5 分割が累積比 5.0 として取れる）
- 5年超期間で (a) が NaN になることを実機確認、(b) でカバーできるかを併せて記録
- 結果と教訓を `verification_results.md` の Step 7 セクションに追記
- 本実装 P4 で採用する手法と、片方を採れない場合のフォールバック条件を明示

---

## 依存ライブラリ（予定）

| ライブラリ | 用途 | インストール |
|-----------|------|------------|
| `requests` | API 呼び出し | 導入済み |
| `lxml` | XBRL 解析 | 要追加 |
| `pandas` | データ整形 | 要追加 |
| `yfinance` | 株価補完 | 要追加 |
| `plotly` | HTML グラフ出力 | 要追加 |

---

## リスク・懸念点

| 項目 | 内容 | 対策候補 |
|------|------|---------|
| XBRL タクソノミの複雑さ | 勘定科目の要素名が企業ごとに揺れる場合あり | EDINET タクソノミ仕様書を参照、主要要素名をホワイトリスト管理 |
| 過去データの欠損 | 古い期の XBRL は構造が異なる可能性 | 取得可能な期のみ処理し欠損は NaN で許容 |
| API レート制限 | 公式仕様書に記載なし。実測では **1リクエストあたり3〜5秒の間隔が必要**（守らないと接続切断）。旧v1時代の「日100回」説は現仕様書には不記載 | sleep を3〜5秒に設定。本実装では取得済み日付をキャッシュして再リクエストしない設計が必須 |
| 株価と決算期のずれ | PER 計算には決算発表日付近の株価が必要 | 決算発表日（`periodEnd`）を基準日として yfinance から取得 |
