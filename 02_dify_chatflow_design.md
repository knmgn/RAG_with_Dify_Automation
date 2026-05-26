# Dify Chatflow（ワークフロー型）＆プロンプト設計書
## 株式会社デモ・ロジスティクス向け 社内規程ナレッジ Bot

> プロジェクトコード：DEMO-RAG-001
> 設計バージョン：v1.3
> 想定LLM：OpenAI gpt-4o-mini（コスト最適化）／本番昇格時は gpt-4o または Claude 3.5 Sonnet
> 想定埋め込みモデル：text-embedding-3-large（dimension: 3072）
> Rerankモデル：Cohere rerank-multilingual-v3.0
> 想定UI：Dify標準WebApp ／ Slack ／ 社内ポータル iframe 埋め込み
> 連携先：n8n（Self-hosted on Docker）→ Slack Bot → Google Drive（共有ドライブ）

---

## Targeted Use Case for Japanese SMEs (English Summary for Global Clients)

> This section is intentionally written in English for international clients (e.g. Upwork buyers) who evaluate this portfolio without reading Japanese. It clarifies **why** the demo targets Japan-specific back-office pain points and how the same architecture is reusable across other linguistic and regulatory contexts.

### Why this demo targets Japanese SMEs

Japanese small and medium-sized enterprises (SMEs) carry an unusually heavy back-office burden compared to their Western counterparts. The dummy regulation bundled with this portfolio (`01_dummy_manual_demo_logistics.md`) is a faithful caricature of the operational reality faced by tens of thousands of Japanese SMEs in logistics, manufacturing, construction, and professional services.

1. **Hyper-granular internal rules.** Expense policies routinely encode dozens of edge cases — taxi reimbursement only after 23:00, per-route last-train screenshots required as evidence, a JPY 15,000 cap with a separate "excess justification form (F-021)" requiring two-manager approval, distinct lodging caps for the 23 wards of Tokyo vs. other ordinance-designated cities, kilometer-based reimbursement for personal-car business use, and so on. These rules are rarely digitized in a searchable form; they live in 30-page PDFs on a shared drive.
2. **Strict deadlines enforced by social cost.** Late expense submissions trigger an "incident report" (始末書 / *shimatsu-sho*) and HR performance deductions. The social cost of asking a human (the General Affairs department, *Soumu-bu*) the same question repeatedly is high, which paradoxically *suppresses* healthy clarification and increases compliance errors.
3. **Single points of failure.** A named individual — in this demo, "Mr. Sato in General Affairs, ext. 1234" — becomes the human bottleneck for health-insurance-card reissuance, shift filings, expense-template distribution, and dozens of unrelated requests. This is the canonical Japanese SME bottleneck.
4. **Specialized vocabulary and severe orthographic variation.** A Japanese employee asks "深夜帰りのタクシー代いくら？" (colloquial), while the policy is written as "業務終了時刻が23:00を超え" (formal). Bridging this gap requires **Hybrid Search + Rerank**: pure semantic search alone misses form identifiers (`F-021`, `DL-HR-RG-2024-007`), and pure keyword search misses the colloquial-to-formal gap.
5. **Tool fragmentation typical of Japanese workplaces.** Files live on Google Drive or a "社内共有ドライブ" (internal shared drive), conversations happen on Slack/Teams/Chatwork, approvals run through a separate workflow tool ("Coconala-Flow" in this demo), and HR records sit in yet another system. **n8n is the glue** that turns "request → file delivery → audit log" into a single conversational action.

### What this architecture solves

By combining **Dify (high-precision RAG with anti-hallucination guardrails)** and **n8n (executable back-office automation)**, this demo demonstrates:

- **Deflection of 60–80% of repetitive questions** away from the General Affairs bottleneck (Mr. Sato), while preserving the citation trail required for Japanese audit and labor-compliance culture.
- **Zero-hallucination boundary.** When the policy is silent, the bot does not improvise. It returns a strict, fixed deflection message naming the responsible department and contact — matching the cultural expectation of clear accountability (責任の所在 / *sekinin no shozai*).
- **End-to-end automation, not just Q&A.** The "give me the expense template" intent does not return a link in chat — it triggers n8n to fetch the file from Drive, resolve the user's Slack identity, post a Block Kit card with a download button, and log the request to a Google Sheet for audit. This is the difference between a chatbot and a back-office automation system.

### Reusability beyond Japan

The same Chatflow topology (Classifier → Hybrid Retrieval → Score Gate → Guardrailed LLM → Webhook) generalizes to:

- US/EU SMEs with similarly fragmented HR policies and SOPs (PTO, expense, compliance training, OSHA filings).
- Multi-site manufacturing firms in Southeast Asia where regulatory documents are bilingual.
- Healthcare and legal firms where citation and refusal-to-hallucinate are non-negotiable.

To localize this architecture for another region, only three layers need to change:

1. **Knowledge corpus** — replace the regulation PDF.
2. **System-prompt language and deflection contact** — substitute the responsible department / named owner.
3. **Rerank model** — e.g. switch `cohere/rerank-multilingual-v3.0` to `cohere/rerank-english-v3.0` for English-only workloads.

The Chatflow graph, the intent classifier, the n8n integration pattern, and the Slack Block Kit payload remain unchanged. **This portability is the core value proposition** we sell to clients evaluating us on Coconala (domestic Japan) and Upwork (global).

---

## 0. 全体アーキテクチャ（俯瞰図）

```
┌────────────────────────────────────────────────────────────────────┐
│  [ユーザー]                                                         │
│   ⇣ 自然言語で質問                                                  │
│  ┌──────────────────────────────────────────┐                       │
│  │     Dify Chatflow (ワークフロー型)         │                       │
│  │ ┌──────────────────────────────────────┐ │                       │
│  │ │ ①START (sys.query)                   │ │                       │
│  │ │   ↓                                  │ │                       │
│  │ │ ②Question Classifier (Intent Detect) │ │                       │
│  │ │   ├─ 規程Q&A → ③へ                  │ │                       │
│  │ │   └─ ファイル要求 → ⑥へ              │ │                       │
│  │ │   ↓                                  │ │                       │
│  │ │ ③Knowledge Retrieval (Hybrid+Rerank) │ │                       │
│  │ │   ↓                                  │ │                       │
│  │ │ ④IF/ELSE (取得スコア > 0.5)          │ │                       │
│  │ │   ├─ YES → ⑤LLM 回答生成 + Citation  │ │                       │
│  │ │   └─ NO  → ⑦突っぱね回答             │ │                       │
│  │ │   ↓                                  │ │                       │
│  │ │ ⑥HTTP Request → n8n Webhook         │ │ ─── Webhook ──┐       │
│  │ │   ↓                                  │ │              ⇣       │
│  │ │ ⑧Answer (Streaming)                  │ │     ┌─────────────┐  │
│  │ └──────────────────────────────────────┘ │     │   n8n        │  │
│  └──────────────────────────────────────────┘     │ ┌──────────┐ │  │
│                                                    │ │Webhook In│ │  │
│  Knowledge Base:                                   │ │  ↓       │ │  │
│   - 01_dummy_manual_demo_logistics.pdf             │ │Switch    │ │  │
│     (chunked, vectorized, BM25 indexed)            │ │  ↓       │ │  │
│                                                    │ │Slack Send│ │  │
│                                                    │ └──────────┘ │  │
│                                                    └──────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

---

## 1. システムプロンプト（LLM挙動制御）

### 1-1. 配置ノード
Chatflow 内の「LLM」ノード（ノードID: `llm_answerer`）の **System Message** に以下を貼り付ける。

### 1-2. プロンプト本文（コピペ用）

```text
# 役割
あなたは「株式会社デモ・ロジスティクス」社内規程アシスタント "Demo-Logi-Bot" です。
社員の旅費交通費・経費精算・労務に関する質問に、社内規程（DL-HR-RG-2024-007）に基づいて正確に回答します。

# 絶対遵守ルール
1. 回答は必ず<context>タグ内のナレッジ（マニュアル本文）を最優先で参照してください。
2. <context>に該当する記載が存在しない、または関連スコアが低い場合は、推測・憶測・一般論で補完してはいけません。代わりに必ず以下の定型文で回答してください：

   「ご質問の件について、社内規程（DL-HR-RG-2024-007）内に明示的な記載が見当たりませんでした。詳細については総務部の佐藤（内線1234／sato.kenichi@demo-logistics.example.co.jp）まで直接お問い合わせください。」

3. 法律・税務・労務に関する一般論を質問された場合でも、社内規程に直接の記載がない限り、上記の定型文で回答してください。「労働基準法では〜」等の一般解説は禁止です。
4. 金額・期日・条件は、<context>の表記を一字一句改変せず引用してください（例：「1回あたり15,000円（消費税込）」と完全一致で書く）。
5. ユーザーが規程の改変・例外適用を求めた場合（「特別に認めて」等）は、判断権限がないため総務部に確認するよう促してください。

# 回答フォーマット（厳守）
回答は以下の3ブロック構造で出力してください。

【結論】
（質問への直接回答を1〜3文で簡潔に。金額・条件・期日があれば箇条書きで明示）

【詳細・補足】
（規程の該当条文を踏まえて補足説明。NG事例や例外条件がある場合は必ず明記）

【引用元】
- 規程名：株式会社デモ・ロジスティクス 旅費交通費・経費精算および労務手続き規定（DL-HR-RG-2024-007）
- 該当箇所：第◯章 第◯条 第◯項（◯◯について）
- 最終改訂：2024年10月1日（第3版）

# トーン・スタイル
- 敬体（です・ます調）で、ビジネス文書として丁寧かつ簡潔に。
- 不必要な前置き（「ご質問ありがとうございます」等）は省略。
- 絵文字は使用しない。

# 禁止事項
- ナレッジに根拠のない金額・期限・人名・部署名の生成
- 過去の質問履歴に基づく回答の使い回し（毎回ナレッジを参照する）
- "おそらく"、"一般的には"、"だと思います" 等の曖昧表現
- 規程番号・条文番号の創作

# 入力データ
ユーザーの質問：{{#sys.query#}}

参照ナレッジ：
<context>
{{#context.result#}}
</context>
```

### 1-3. 設計意図メモ
- `<context>` タグでナレッジを囲うのは、LLMに「これが事実情報源だ」と明示するため。OpenAI系・Anthropic系ともにXMLタグ構造で渡すと指示遵守率が向上する。
- 「該当しない場合の定型文」を**完全一致レベルで書かせる**ことで、ハルシネーションを抑制し、責任の所在（佐藤）を明確化する。
- 回答フォーマットの3ブロック構造は、エグゼクティブ層が「結論ファースト」で読めるように設計（PREP法の応用）。

---

## 2. Chatflow ノード設計（詳細）

### 2-1. ノード一覧

| # | ノード名 | タイプ | ノードID | 役割 |
|---|---|---|---|---|
| ① | START | 開始ノード | `start` | ユーザー入力受付（`sys.query`） |
| ② | インテント分類 | Question Classifier | `intent_classifier` | 「Q&A」か「ファイル要求」かを判定 |
| ③ | ナレッジ検索 | Knowledge Retrieval | `kb_retrieval` | Hybrid Search + Rerank |
| ④ | スコア判定 | IF/ELSE | `score_gate` | Rerankスコア > 0.5 で分岐 |
| ⑤ | 回答生成 | LLM | `llm_answerer` | システムプロンプトで回答生成 |
| ⑥ | Webhook送信 | HTTP Request | `n8n_webhook` | n8nへPOSTリクエスト |
| ⑦ | 突っぱね回答 | Answer (固定文) | `fallback_answer` | 「総務部へどうぞ」の定型文出力 |
| ⑧ | 最終出力 | Answer | `final_answer` | LLM出力 or Webhook完了メッセージ |

### 2-2. ノード② Question Classifier 設定

**Classifier プロンプト：**
```text
ユーザーの発話を以下の2クラスのいずれかに分類してください。

【クラス1：規程Q&A】
- 規程内容に関する質問
- 例：「タクシー代の上限は？」「経費精算の締切は？」「夜勤手当の計算方法は？」

【クラス2：ファイル要求】
- 経費精算テンプレートやフォーマットの送付・ダウンロード要求
- 例：「経費精算のフォーマットちょうだい」「テンプレートのリンクが欲しい」「Excelファイル送って」

判定が曖昧な場合は【クラス1：規程Q&A】を選択してください。
```

**出力先：**
- クラス1 → ③へ
- クラス2 → ⑥（n8n Webhook）へ

### 2-3. ノード③ Knowledge Retrieval 設定

| 項目 | 設定値 | 備考 |
|---|---|---|
| 検索モード | **Hybrid Search**（Vector + Full-Text） | 後述「3章」で詳説 |
| Top K | 8 | 多めに取って後段でRerank |
| Score Threshold | 0.3（粗フィルタ） | 後段で再判定するため緩めに |
| Rerank Model | `cohere/rerank-multilingual-v3.0` | 日本語精度が高い |
| Rerank後 Top K | 4 | プロンプトに渡す最終件数 |
| メタデータフィルタ | `doc_type = "regulation"` | 規程文書のみ対象 |

### 2-4. ノード④ IF/ELSE 設定

```
条件式: {{#kb_retrieval.result[0].score#}} > 0.5
  TRUE  → ⑤ LLM Answerer
  FALSE → ⑦ Fallback Answer（突っぱね定型文）
```

突っぱねノードの固定文：
```text
ご質問の件について、社内規程（DL-HR-RG-2024-007）内に明示的な記載が見当たりませんでした。
詳細については総務部の佐藤（内線1234／sato.kenichi@demo-logistics.example.co.jp）まで直接お問い合わせください。

なお、緊急の場合は総務部代表（内線1230）でも対応可能です。
```

---

## 3. ハイブリッド検索（Vector + Keyword）×Rerank の重要性と設計

### 3-1. 「なぜハイブリッドが必要なのか」を一言で
- **Vector検索だけ**：「深夜帰り」「夜遅く」「終電後」など**意味的に近い表現**は拾えるが、「F-021」「DL-HR-RG-2024-007」など**固有の番号・コード**は弱い。
- **Keyword検索（BM25）だけ**：固有番号・条文番号には強いが、口語表現の揺れに弱い。
- **両者を融合**することで、表記揺れ × 固有名詞 の両方に強くなる。さらに**Rerank**で文脈的関連度を再評価し、ノイズを除去する。

### 3-2. 想定される表記揺れ例（実務でよくあるパターン）

| ユーザー口語表現 | 規程内の正式表記 | 対策 |
|---|---|---|
| 「深夜帰りのタクシー代いくら？」 | 「業務終了時刻が23:00を超え」「タクシー代の支給要件」 | Vectorで意味類似拾い |
| 「経費の締め切りいつ？」 | 「経費精算書の提出期限」「毎月25日17:00必着」 | Vectorで意図類似拾い |
| 「テンプレ v3」 | 「経費精算テンプレート_v3.xlsx」 | BM25でファイル名拾い |
| 「保険証なくした」 | 「健康保険被保険者証」「再交付申請書（F-031）」 | Hybrid（両方必要） |
| 「F-021って何？」 | 「タクシー代超過利用理由書」 | BM25が必須 |
| 「夜勤の申込いつまで？」 | 「深夜シフトの申請期日」「前々週金曜日17:00」 | Vector + Rerankで条文絞込 |

### 3-3. Dify側 ナレッジ設定（推奨パラメータ）

#### ① チャンク分割
- **チャンクモード：階層分割（Parent-Child）**
  - 親チャンク（Parent）: 1,200 tokens（条単位で区切る）
  - 子チャンク（Child）: 300 tokens（embedding対象。意味の粒度を保つ）
- セパレータ：`\n### `、`\n#### `、`\n第`（Markdown見出し・条文見出しで自然に分割）
- オーバーラップ：50 tokens（条文の境界で文脈断絶を防ぐ）

#### ② インデキシング
- **Embedding Model**：`text-embedding-3-large`（日本語性能：◎、3072次元）
  - コスト重視なら `text-embedding-3-small`（1536次元）も可。精度差は規程文書ではほぼ無視できる。
- **Index Method**：High Quality（経済モードは禁止）
- **Search Setting**：Hybrid Search 有効化、Semantic Weight = `0.7` / Keyword Weight = `0.3`
  - 日本語規程文書では Semantic 寄せがやや有利。固有番号検索のテストで Keyword Weight を 0.4 に上げる調整余地あり。

#### ③ Rerank
- **モデル**：`cohere/rerank-multilingual-v3.0`（日本語サポート、トップクラス精度）
- **代替案**：`jina-reranker-v2-base-multilingual`（OSS、Self-Host可、API課金不要）
- 入力：Top 8、出力：Top 4

#### ④ メタデータ
PDFをアップロードする際、以下のメタデータを付与する。

```json
{
  "doc_id": "DL-HR-RG-2024-007",
  "doc_title": "旅費交通費・経費精算および労務手続き規定",
  "doc_version": "v3",
  "last_revised": "2024-10-01",
  "doc_type": "regulation",
  "category": "総務"
}
```

### 3-4. 動作確認用テストクエリ（10件）
本番リリース前に以下のクエリでRecall@4を確認すること。

| # | テストクエリ | 期待ヒット条文 |
|---|---|---|
| 1 | 深夜帰りのタクシー代いくら？ | 第5条 第1項 |
| 2 | クライアントとタクシー乗っていいの？ | 第5条 第2項 |
| 3 | タクシー上限超えた | 第5条 第4項（F-021） |
| 4 | 経費の締め切りいつ？ | 第8条 第1項 |
| 5 | テンプレ v3 どこ？ | 第9条 第2項 |
| 6 | 25日過ぎちゃった | 第8条 第3・4項 |
| 7 | 保険証なくした | 第15条 |
| 8 | 夜勤手当いくら？ | 第13条 |
| 9 | 深夜シフトいつまでに申請？ | 第14条 第1項 |
| 10 | 新幹線グリーン車乗れる？ | 第4条 第2項 |

各クエリで期待条文がTop 4内にヒットすればRecall@4=100%。本番品質の目安はRecall@4 >= 90%。

---

## 4. n8n Webhook連携ロジック

### 4-1. インテント検出ロジック（Dify側）

ノード② Question Classifier で **「クラス2：ファイル要求」** に分類された場合、以下の処理を行う。

#### ノード⑥ HTTP Request 設定

| 項目 | 設定値 |
|---|---|
| メソッド | POST |
| URL | `https://n8n.demo-logistics.example.co.jp/webhook/expense-template` |
| ヘッダー | `Content-Type: application/json` |
| ヘッダー | `X-Auth-Token: {{#env.N8N_WEBHOOK_TOKEN#}}` |
| ボディ（JSON） | 下記参照 |
| タイムアウト | 10秒 |
| リトライ | 2回（指数バックオフ） |

**リクエストボディ（JSON）：**
```json
{
  "intent": "request_expense_template",
  "user_id": "{{#sys.user_id#}}",
  "user_query": "{{#sys.query#}}",
  "conversation_id": "{{#sys.conversation_id#}}",
  "requested_at": "{{#sys.current_time#}}",
  "metadata": {
    "source": "dify-chatflow",
    "template_key": "expense_template_v3"
  }
}
```

#### ノード⑥のレスポンスを使った最終回答（⑧ Answer ノード）

```text
経費精算テンプレートをご用意しました。Slack（#general またはDM）にダウンロードリンクをお送りしました。

【お送りしたファイル】
- 経費精算テンプレート_v3.xlsx
- 保管場所：社内共有ドライブ ➔ 02_総務部 ➔ 経費精算テンプレート_v3.xlsx

【ご注意】
- 提出期限：毎月25日17:00必着（規程第8条）
- マクロを必ず有効化してください（規程第9条第4項）

【引用元】
規程：DL-HR-RG-2024-007 第8条・第9条
```

---

### 4-2. n8n 側ワークフロー設計（フロー図テキスト）

```
┌─────────────────────────────────────────────────────────────┐
│  n8n Workflow: "Dify-Expense-Template-Dispatcher"            │
│                                                              │
│  [Node 1: Webhook]                                          │
│    Method: POST                                              │
│    Path: /webhook/expense-template                          │
│    Auth: Header Auth (X-Auth-Token)                         │
│       ↓                                                      │
│  [Node 2: Set Variables]                                    │
│    user_id     = {{$json.user_id}}                          │
│    intent      = {{$json.intent}}                           │
│    template_key= {{$json.metadata.template_key}}            │
│       ↓                                                      │
│  [Node 3: Switch (intent別ルーティング)]                     │
│    ├─ "request_expense_template"  → Node 4                  │
│    ├─ "request_taxi_form"         → 将来拡張                 │
│    └─ default                     → Node 99 (エラー応答)     │
│       ↓                                                      │
│  [Node 4: Google Drive - Get Shared Link]                   │
│    File ID: <経費精算テンプレート_v3.xlsx の固定ID>          │
│    Mode: Generate shareable link (anyone with link, viewer) │
│    Output: $json.webViewLink                                │
│       ↓                                                      │
│  [Node 5: Lookup Slack User ID]                             │
│    (HRシステムまたはGoogle Workspace Directory経由で          │
│     dify user_id → Slack user_id を解決)                     │
│       ↓                                                      │
│  [Node 6: Slack - Send Direct Message]                      │
│    Channel: {{$node["Node 5"].json.slack_user_id}}          │
│    Text: (下記テンプレ参照)                                   │
│    Blocks: Block Kit形式（後述）                              │
│       ↓                                                      │
│  [Node 7: Log to Google Sheets]                             │
│    Sheet: "DifyBot_FileRequest_Log"                         │
│    Append: timestamp, user_id, intent, file, status         │
│       ↓                                                      │
│  [Node 8: Respond to Webhook]                               │
│    Body: { "status": "success",                              │
│            "delivered_at": "{{$now}}",                       │
│            "slack_user": "{{...}}" }                         │
└─────────────────────────────────────────────────────────────┘
```

### 4-3. Slack Block Kit ペイロード（Node 6）

```json
{
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "経費精算テンプレートをお届けします"
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*ファイル名:* 経費精算テンプレート_v3.xlsx\n*提出期限:* 毎月25日17:00必着\n*規程:* DL-HR-RG-2024-007 第8条・第9条"
      }
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": { "type": "plain_text", "text": "ダウンロード" },
          "style": "primary",
          "url": "{{$node[\"Node 4\"].json.webViewLink}}"
        },
        {
          "type": "button",
          "text": { "type": "plain_text", "text": "規程を確認" },
          "url": "https://drive.example.co.jp/regulations/DL-HR-RG-2024-007.pdf"
        }
      ]
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": ":robot_face: Demo-Logi-Bot より自動送信 ｜ 不明点は総務部 佐藤（内線1234）まで"
        }
      ]
    }
  ]
}
```

### 4-4. エラーハンドリング（Node 99）

| エラーケース | 対処 |
|---|---|
| Slackユーザー解決失敗 | 総務部チャンネル `#admin-bot-alert` に通知し、`#general` にパブリック投稿でフォールバック |
| Google Drive取得失敗 | 30秒後に1回リトライ。失敗時はDify側にHTTP 500を返し、Dify側で「総務部に直接ご連絡ください」とフォールバック |
| Webhook認証失敗 | 即時 401 を返し、ログに記録 |

### 4-5. セキュリティ

- **Webhook URL は推測困難なランダム文字列**を含むパス（例：`/webhook/expense-template-9d7f3a2c`）にする
- **X-Auth-Token** ヘッダーによる共有秘密での認証（Dify環境変数 → n8n Credentials）
- n8n 側は **IP Allowlist** で Dify インスタンスからのアクセスのみ許可（Self-host時）
- ログには PII（個人情報）を残さない（user_id のみ、氏名・メールは記録しない）

---

## 5. 拡張ロードマップ（クライアントへの提案フック）

| 段階 | 拡張内容 | 工数感（技術的観点） |
|---|---|---|
| Phase 1（本デモ） | 規程Q&A + テンプレート配布 | Dify×1 + n8n×1ワークフロー |
| Phase 2 | 交通費の写真OCR → 自動入力（Vision API + n8n） | Vision LLM + Excel書込ノード追加 |
| Phase 3 | 申請承認フロー連携（Slack承認ボタン → ワークフローシステム自動更新） | n8n Slack interactive + Coconala-Flow API |
| Phase 4 | 規程改訂版の自動取り込み（Driveに新版PDFアップ → Embedding再生成） | Drive Trigger + Dify Knowledge API |
| Phase 5 | 多言語対応（英語・ベトナム語）：技能実習生向け | 規程の自動翻訳パイプライン＋言語別Chatflow |

---

## 6. デモ動画のシナリオ（撮影台本）

### Scene 1（00:00-00:20）課題提示
- ナレーション：「経費規程30ページ、毎月総務に同じ質問が30件…うちの会社、こんな状態ありませんか？」
- 画面：分厚いPDFを開いて目視で探す様子

### Scene 2（00:20-01:00）Dify Bot で質問
- ユーザー入力：「深夜帰りのタクシー代いくら？」
- Bot応答：規程の該当条文を【結論】【詳細】【引用元】で構造化回答
- 画面右側で Hybrid Search のヒット箇所をハイライト

### Scene 3（01:00-01:30）ガードレール検証
- ユーザー入力：「猫を飼ったら手当出る？」
- Bot応答：「規程内に記載がありません。総務部 佐藤までお問い合わせください」と突っぱね
- → 「嘘をつかない」を強調

### Scene 4（01:30-02:30）n8n連携デモ
- ユーザー入力：「経費精算のフォーマットちょうだい」
- Dify → n8n Webhook 発火
- Slackにダウンロードリンクが即座にポン！と届く様子（画面分割）

### Scene 5（02:30-03:00）クロージング
- 「Dify × n8n で、社内問い合わせの 70%自動化。御社にも導入しませんか？」
- CTA：ココナラ / Upwork のリンク

---

## 7. 納品物チェックリスト（クライアント引渡し時）

- [ ] Dify Chatflow DSL（YAMLエクスポート）
- [ ] ナレッジ用 PDF（本デモでは規程PDF）
- [ ] n8n ワークフロー（JSONエクスポート）
- [ ] 環境変数一覧（`.env.example`）
- [ ] Slack App マニフェスト（YAML）
- [ ] Google Drive サービスアカウント JSON（クライアント取得分）
- [ ] 運用マニュアル（規程改訂時の再Embedding手順）
- [ ] テストクエリ集とRecall@4測定結果
- [ ] Postman / curl サンプルコレクション

---

（以上）
