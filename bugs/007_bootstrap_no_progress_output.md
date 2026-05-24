# BUG-007: bootstrap fetch-documents が進捗を一切出さない

## ステータス

未修正

## 発見日

2026-05-23

## 概要

bootstrap fetch-documents が約 13-40 分かかる長時間処理にも関わらず、進捗を一切出さず最終 JSON だけ吐く。ユーザー / Claude は「動いているのか?」「あと何分か?」を判断できない。

## 症状

- `python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py fetch-documents --years 3` を実行
- 約 13 分間、何も出力されない
- 完了時に最終 JSON `{"status": "success", "counters": {...}}` が一度だけ出る
- 現状のワークアラウンドは「Monitor で `ls cache/documents/ | wc -l` を polling」

manual_test history.md L591 で問題視: 「bootstrap.py は途中ログを出さず、完了時に JSON を出力する設計です」

## 原因

[scripts/bootstrap.py](../skills/japan-stock-analysis/scripts/bootstrap.py) `cmd_fetch_documents` には 20 件ごとに stderr 出力するコードがあるが、`subprocess.run(..., capture_output=True)` や `run_in_background` 等で stderr が捕捉される実行形態だとユーザーには見えない可能性。

実機検証が必要だが、少なくとも以下のいずれかが起きている:
- stderr 出力が実装されていない (要コード確認)
- stderr 出力はあるが flush されていないためバッファリングで届かない
- Claude Code Bash ツールが stderr を最終出力までバッファする

## 影響範囲

- 影響: bootstrap fetch-documents の全実行
- 該当ファイル: [scripts/bootstrap.py](../skills/japan-stock-analysis/scripts/bootstrap.py) `cmd_fetch_documents`

## 再現手順

1. cache を fresh 化: `python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --all --confirm`
2. bootstrap: `python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py fetch-documents --years 1`
3. 数分間、stderr / stdout が無音であることを確認

## 修正案

### 案1: stderr 出力の実装確認と flush 追加

```python
for i, d in enumerate(target_dates, start=1):
    ...
    if i % 20 == 0 or i == len(target_dates):
        sys.stderr.write(
            f"[{i}/{len(target_dates)}] fetched={counters['fetched']} "
            f"skipped={counters['skipped']} errors={counters['errors']}\n"
        )
        sys.stderr.flush()  # 重要: バッファリング対策
```

pre-research/edinet/step2_doc_list.py L204-205 と同じパターン。

### 案2: 進捗ファイルへの書き出し

`cache/.bootstrap_progress.json` のようなファイルに `{"current": 234, "total": 783, "fetched": 230, "errors": 0}` を書き込み、Monitor 等から定期的に読める形にする。

### 推奨

案1 が先、案2 は補完。

## 対応

<!-- AI instruction: 修正完了後に追記するセクション。採用した修正案、または修正案にない独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- pre-research 元実装: `pre-research/edinet/step2_doc_list.py` L204-205
- 観測ログ: manual_test history.md L591
