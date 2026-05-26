# Dify × n8n ポートフォリオデモ素材

ココナラ／Upwork向けポートフォリオ（見本）として、「Dify（高精度RAG）×n8n（実務自動化）」のデモ動画を撮影するための素材一式。

## 成果物

### 1. ダミー社内マニュアル（PDF化用テキスト）
[`01_dummy_manual_demo_logistics.md`](./01_dummy_manual_demo_logistics.md)

株式会社デモ・ロジスティクスの「旅費交通費・経費精算および労務手続き規定（DL-HR-RG-2024-007）」のダミー本文。
- 第1章 総則
- 第2章 旅費交通費規定（タクシー代の細則、超過理由書、NG事例）
- 第3章 経費精算の手続き（25日必着、テンプレート v3、遅延始末書）
- 第4章 福利厚生・労務手続き（夜勤手当、深夜シフト申請、保険証紛失時の窓口）
- 第5章 雑則
- 別表1：申請フォーマット一覧
- 別表2：問い合わせ窓口

**PDF化の手順例：**
```bash
# Pandoc + wkhtmltopdf を使用する場合
pandoc 01_dummy_manual_demo_logistics.md \
  -o 01_dummy_manual_demo_logistics.pdf \
  --pdf-engine=wkhtmltopdf \
  -V CJKmainfont="Noto Sans CJK JP"
```
または、VSCode / Typora / Obsidian で開いて「PDFエクスポート」でも可。

### 2. Dify Chatflow 設計書
[`02_dify_chatflow_design.md`](./02_dify_chatflow_design.md)

上記マニュアルをナレッジに食わせる Dify Bot の設計書。
- システムプロンプト（ハルシネーション抑制ガードレール、Citation強制）
- ハイブリッド検索（Vector + Keyword）× Rerank の設定
- Question Classifier による Intent 検出
- n8n Webhook 連携（経費テンプレート自動配布 → Slack DM）
- テストクエリ集、デモ動画台本、納品チェックリスト

## 使い方

1. `01_dummy_manual_demo_logistics.md` を PDF化してDifyのナレッジにアップロード
2. `02_dify_chatflow_design.md` の設定値をもとに Dify Chatflow を組み立て
3. n8n のワークフローを設計書の通り構築
4. デモ動画台本（設計書の第6章）に沿って撮影

## ライセンス

このダミー素材は架空のものです。実在の企業・人物・住所・電話番号とは一切関係ありません。
