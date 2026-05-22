---
name: japan-stock-analysis
description: 日本株（4桁証券コード指定）の財務三表・指標・バリュエーション推移を EDINET と yfinance から取得し、HTML レポートを生成する。1〜数社（〜10社）の個別分析向け。多銘柄スクリーニングは対象外。
---

# japan-stock-analysis

<!--
  このファイルは Claude が読んで実行するエントリ手順書。
  Phase P1 時点では骨子のみ。各セクションは後続 Phase で詰める。
  詳細設計の出典: ../../plan.md (リポジトリ直下) と pre-research/
-->

## 1. 目的と前提

<!-- TODO(P8): plan.md §1 から転記。
     - できること: 1〜数社の財務・指標・バリュエーション推移取得と HTML レポート化
     - できないこと: 多銘柄スクリーニング、リアルタイム株価、信用残・空売り、セクター比較
     - 一次情報: EDINET 主、yfinance は最新株価/PER/PBR 補完用
-->

## 2. 入力受付ルール

<!-- TODO(P8): ユーザー発話から sec_code (4桁) を抽出するルール。
     - "7203" / "トヨタ (7203)" / "7203 と 6758 を比較" などを sec_code list へ正規化
     - 4桁数字以外が渡されたら確認質問
-->

## 3. 環境準備

<!-- TODO(P8): 実行前チェック。
     - secret.json が Skill ルートに存在するか確認。無ければユーザーに配置を促す。
       期待形式: {"edinet": {"api_key": "..."}}
       配置先: skills/japan-stock-analysis/secret.json (gitignore 済)
     - requirements.txt の依存をインストール (推奨: python -m venv env してから)
     - bootstrap 済か判定。未完了なら scripts.pipeline analyze の出力に
       "status": "needs_bootstrap" が乗るので、その指示に従い bootstrap を提案。
-->

## 4. 実行手順

<!-- TODO(P8): 主要コマンドの呼び方を plan.md §4.3 から転記。
     全コマンドは ${CLAUDE_SKILL_DIR} 絶対パスで起動する (Claude Code が
     SKILL.md 実行時に自動セットする環境変数)。CWD はユーザーの作業ディレクトリ
     のまま — 成果物は CWD に落ちる。

     - 分析: python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code <code>
     - 比較: python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code <code1> <code2>
     - 初回 bootstrap: python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py init
     - キャッシュ情報: python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info [--sec-code <code>]
     - 標準出力は JSON。"status" で分岐 (success / needs_bootstrap / config_error / error)。
-->

## 5. 失敗時のリカバリ

<!-- TODO(P8):
     - ConfigError (secret.json 関連): ユーザーへ配置/修正を案内
     - needs_bootstrap: ユーザー確認の上 bootstrap fetch-documents を実行
     - EDINET レート制限 (1日100req): --chunk K/M で分割実行を提案
     - yfinance 失敗: --no-yfinance で財務のみで完走させる選択肢を提示
     - XBRL 解析失敗 (未解決要素): §6 のマッピング解決フローへ
-->

## 6. XBRL 要素マッピングのエスカレーション

<!-- TODO(P8): plan.md §4.4 のフローを実装する手順。
     1. pipeline の出力で "unresolved_elements" が空でなければ:
     2. cache/mappings/{sec_code}.json を確認
     3. 無ければ、未解決要素一覧 + XBRL 名前空間ナレッジ
        (pre-research/edinet/xbrl_company_variation.md §4.4 を移植) を見て
        Claude 自身が判定し、mapping_resolver save に渡してキャッシュ
-->

## 7. 出力の解釈

<!-- TODO(P8):
     - 成果物: CWD 直下に report_{sec_code}.html と data_{sec_code}.json
     - JSON スキーマは P5 で確定
     - HTML は plotly inline 埋め込みでオフライン閲覧可
     - ユーザーへの提示テンプレ: ファイルパスをクリック可能リンクで提示し、
       警告 (株式分割未補正・LLM マッピング使用等) があれば併せて伝える
-->

## 8. 既知の制限事項

<!-- TODO(P8): pre-research/edinet/verification_results.md から継承。
     - 株式分割補正: P4 完了までは PER/PBR が一部銘柄で歪む (警告に出る)
     - 月次決算ラベルの揺れ
     - documents_index に存在しない期間は bootstrap 未取得 → needs_bootstrap で返す
     - 銀行・保険は P8 のマッピング解決フロー必須
-->
