# EDINET 公式仕様書

このディレクトリには EDINET API v2 の公式仕様書を配置する。
**ファイル本体は `.gitignore` で除外**しており、必要に応じて以下から再ダウンロードする。

## ファイル一覧と入手先

| ファイル | 内容 | 入手先 |
|---------|------|--------|
| `ESE140206.pdf` | EDINET API 仕様書 v2 本体 | https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf |
| `ESE140206.txt` | 同上の PDF テキスト抽出版（`pdftotext` 等で生成） | 上記 PDF から手元で変換 |
| `ESE140327.xlsx` | 書類種別コード（docTypeCode）一覧 | https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140327.xlsx |
| `ESE140328.xlsx` | 書類一覧 API の出力例 | https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140328.xlsx |

## なぜリポジトリに含めないか

- 公式から誰でも入手可能で、内容は EDINET 側の更新で変わりうる
- PDF が数 MB ありリポジトリサイズを膨らませる
- 仕様の引用は本リポジトリ内の Markdown（`pre-research/edinet/edinet_api_overview.md` 等）に必要十分の形で残してある

## PDF からテキスト抽出する方法

PDF を grep したい場合の手順:

```sh
brew install poppler  # 一度だけ
pdftotext references/edinet/ESE140206.pdf references/edinet/ESE140206.txt
```
