# 引き継ぎメモ — Dify × n8n ポートフォリオデモ (DEMO-RAG-001)

> これは Cursor (ブラウザ版 Cloud Agents) 上での過去のエージェント作業を、
> Claude Code に引き継ぐための状況整理メモです。元のチャットログは
> Cursor Pro解約に伴いエクスポート不可能だったため、PDF印刷 → OCR で復元した
> ものをベースに、実際の GitHub リポジトリ (main ブランチ) の状態と突き合わせて
> 作成しています。細かい数値・設定値は本メモではなくリポジトリ内のファイルを
> 正とすること。

## プロジェクトの目的

ココナラ／Upwork向けの**公開ポートフォリオ**。実在しない架空企業「株式会社デモ・
ロジスティクス」の就業規則・経費規定をダミーデータとして作成し、それを Dify
(高精度RAG) と n8n (実務自動化) で Bot 化するデモを完成させ、開発力の証明として
GitHub に公開する。**リポジトリはすでに Public化済み。**

- リポジトリ: `knmgn/RAG_with_Dify_Automation` (public, main branch)
- 実在の企業・人物・電話番号とは一切関係のない架空データのみを使用

## 現在のリポジトリの状態 (ファイルとして完成しているもの)

PR #1〜#5 まで merge 済み。以下がすべて main ブランチに存在する:

```
01_dummy_manual_demo_logistics.md   # ダミー社内規定（PDF化してナレッジ投入用）
02_dify_chatflow_design.md          # 設計書 v1.4（965行、英語サマリー含む）
README.md                            # ポートフォリオ全体の説明・クイックスタート
経費精算テンプレート_v3.xlsx          # ダミーExcel（5シート構成）
scripts/build_expense_template.py    # 上記xlsxの再生成スクリプト（openpyxl）
docker/README.md                     # docker compose up -d 一発起動手順
docker/n8n/docker-compose.yml        # n8n本体 + xlsx volume + 共有network
docker/n8n/templates/.gitkeep
docker/dify/docker-compose.override.yaml  # Dify公式構成へのネットワーク追加差分
docker/test/test_webhook.sh          # 4段階疎通テスト（host→n8n / Dify→n8n / WF1 / WF2）
```

設計書 (`02_dify_chatflow_design.md`) には §4-1（フル版）、§4-6（シンプル版）、
**§4-7（完全ローカルDocker版・中小企業向け本命として推奨）**、§4-8（実装ノウハウ集）
まで完全に文書化済み。

## まだ「ファイルに残っていない」= 未実施の作業

Dify / n8n の**画面上での設定作業**は、Dify Cloud版ではすでに一通り検証済み
（Hybrid Search・Rerank・Webhook認証など全部動作確認OKだった）が、その後
「完全ローカルDocker構成（Self-Hosted Dify + n8n）」に移行する方針に決まり、
**Self-Hosted側でまだ再構築していない**状態でチャットが途切れている。

残タスク（設計書のPhase 3〜5相当）:

1. **Phase 3: Self-Hosted DifyでKnowledge再構築**（30〜45分想定）
   - `01_dummy_manual_demo_logistics.md`（またはPDF化したもの）をアップロード
   - Chunk設定: Parent-Child / Paragraph, Parent 1,200 characters, Child **250** characters
     （※ tokens表記とcharacters表記の単位ズレに注意。設計書 §3-3 参照）
   - Replace consecutive spaces: ON / Delete URLs and emails: **OFF**（絶対にONにしない）
   - Index Method: High Quality / Embedding: text-embedding-3-large
   - Retrieval: **Hybrid Search**（Vector Search単体ではNG。固有番号・ファイル名がヒットしない）
     - サブモード: Rerank Model（rerank-multilingual-v3.0）
     - Top K: 4（3でも動くが4推奨） / Score Threshold: 0.5 (ON)
   - Metadata: schema定義（6フィールド, string型）→ 値の割り当て（2段階構成）→ Built-inトグルON

2. **Phase 4: Chatflow再構築**（20〜30分想定）
   - `[Start] → [Question Classifier] → Class1(規程Q&A)→[Knowledge Retrieval]→[LLM]→[Answer]`
   -                                  `→ Class2(ファイル要求)→[HTTP Request]→[Answer]`
   - Question Classifierプロンプト: 設計書 §2-2 をそのままコピペ
   - LLM: gpt-4o-mini, System Message は設計書 §1-2 のシステムプロンプト全文
   - HTTP Requestノード:
     - URL: `http://n8n_local:5678/webhook/<Workflow1のUUID>`（**Difyコンテナ内部からはサービス名 `n8n_local` で叩く。`localhost` ではコンテナ自身を指してしまい届かない = "localhost問題"**）
     - Headers: `X-Auth-Token: {{#env.N8N_WEBHOOK_TOKEN#}}`
     - Body: 設計書 §4-1 のJSONペイロード
   - Dify環境変数 `N8N_WEBHOOK_TOKEN` を Settings → Environment Variables に登録

3. **Phase 5: End-to-Endテスト**
   - 「深夜帰りのタクシー代いくら？」→ Q&A経路の確認
   - 「経費精算のフォーマットちょうだい」→ HTTP Request → n8n → ダウンロードURL返却の確認
   - URLクリック → `localhost:5678/webhook/files/expense-v3` からxlsxダウンロード確認
   - 5シート構成が正しく開けるか確認

4. **デモ動画撮影**（設計書 第6章のシーン台本あり、約3分構成）

## ハマりやすいポイント（過去のデバッグ経緯から）

n8n / Dify / Docker 周りで実際に詰まった箇所。同じ罠にもう一度落ちないためのメモ:

- **n8n Header Auth Credentialの罠**: Credentialモーダル内の `Name` 欄は「HTTPヘッダー名」
  （例: `X-Auth-Token`）を入れる場所であり、Credential自体の管理用の名前ではない。
  管理用の名前はモーダル上部タイトルのインライン編集。ここを混同すると
  `Authorization data is wrong!` エラーになる。
- **Docker内部通信 vs Publish の混同**: `docker run -p` によるポート公開（ブラウザから
  UIを見るために必要）と、同一Dockerネットワーク内でのコンテナ間通信（サービス名で
  直接届く。Publish不要）は別概念。DifyのHTTP RequestノードのURLは後者。
- **Switchノードのフォールバックは自前実装しない**: `does not contain "a, b"` のような
  文字列部分一致でフォールバックを作ると壊れやすい。n8n標準の `Fallback Output`
  （Extra Output設定）を使うこと。
- **チャンクサイズの単位ズレ**: 設計書はtokens表記、Dify UIはcharacters表記。
  日本語 + text-embedding-3-largeでは概ね1文字=1〜1.5トークン。
  「Child 300 tokens」は「Dify UI上 250 characters」に相当。
- **macOS特有**: Google Drive経由でxlsxを扱う場合、`com.google.drivefs.item-id`
  の拡張属性がn8nのallowlistチェックでEPERM原因になることがある。
  `xattr -c` で除去してから使う（`docker/README.md`にも記載）。
- **ファイルダウンロードのファイル名**: Content-Dispositionヘッダーは日本語ファイル名
  だとRFC 5987形式（`filename*=UTF-8''...`）でエンコードする必要がある。

## Claude Codeで作業を再開する際の進め方（提案）

1. まずリポジトリをclone、`docker/README.md` の手順で完全ローカル環境
   （Dify Self-Hosted + n8n）を実際に起動する
2. 上記「Phase 3」の設定をDify管理画面上で行う（これはUI操作なのでClaude Codeが
   自動化できる部分は限定的。スクリーンショットを見せながら一緒に進める形が現実的）
3. Phase 4のChatflowノードを設計書の値通りに組む
4. `docker/test/test_webhook.sh` でWebhook単体の疎通確認 → Dify経由のE2E確認
5. 問題が起きたら上記「ハマりやすいポイント」を先に疑う
6. 全部通ったらデモ動画撮影 → README仕上げ → 公開

## 元のOCRチャットログ

このメモのベースになった全文（OCR由来、誤字あり）は別途 `chat_log_ocr.md` として
提供済み。設計判断の「なぜ」を確認したい場合の参考に。数値・コードは必ずリポジトリ
側を正とすること。
