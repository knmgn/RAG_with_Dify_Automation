# Dify Chatflow (Workflow Mode) & Prompt Design Document
## Internal Policy Knowledge Bot for Demo Logistics Inc.

> Project code: DEMO-RAG-001
> Design version: v1.5 (updated with results from the live build)
> LLM: OpenAI gpt-4o-mini (cost-optimized); gpt-4o or Claude 3.5 Sonnet when promoted to production
> Embedding model: text-embedding-3-large (dimension: 3072)
> Retrieval: Hybrid Search + **Weighted Score** (Semantic 0.7 / Keyword 0.3)
> Note: an external Rerank API (Cohere) was not adopted. See §3-3 ④ for the reasons and measurements
> Front ends: Dify standard WebApp / Slack / iframe embed in an internal portal
> Integrations: n8n (self-hosted on Docker) → Slack bot or internal file server (see §4-7)

> **About v1.5:** up to v1.4 this document was a paper design, partly verified on Dify Cloud.
> For v1.5 the fully local setup in §4-7 was built end to end on real hardware, and every
> statement that turned out not to work has been corrected in place. What was wrong, and why, is
> recorded in **§4-8 ⑤–⑪**. The entire build is scripted against the API (`scripts/`, see §7).

> **Language note:** the demo targets Japanese-speaking employees, so the knowledge corpus, the
> prompts and the bot's replies are in Japanese. Copy-paste blocks that the bot uses at runtime
> are kept in the original Japanese, with English explanations around them. An English translation
> of the system prompt is in the [README](./README.md#prompt-engineering-system-message).

---

## Targeted Use Case for Japanese SMEs (English Summary for Global Clients)

> This section is intentionally written in English for international clients (e.g. Upwork buyers) who evaluate this portfolio without reading Japanese. It clarifies **why** the demo targets Japan-specific back-office pain points and how the same architecture is reusable across other linguistic and regulatory contexts.

### Why this demo targets Japanese SMEs

Japanese small and medium-sized enterprises (SMEs) carry an unusually heavy back-office burden compared to their Western counterparts. The dummy regulation bundled with this portfolio (`01_dummy_manual_demo_logistics.md`) is a faithful caricature of the operational reality faced by tens of thousands of Japanese SMEs in logistics, manufacturing, construction, and professional services.

1. **Hyper-granular internal rules.** Expense policies routinely encode dozens of edge cases — taxi reimbursement only after 23:00, per-route last-train screenshots required as evidence, a JPY 15,000 cap with a separate "excess justification form (F-021)" requiring two-manager approval, distinct lodging caps for the 23 wards of Tokyo vs. other ordinance-designated cities, kilometer-based reimbursement for personal-car business use, and so on. These rules are rarely digitized in a searchable form; they live in 30-page PDFs on a shared drive.
2. **Strict deadlines enforced by social cost.** Late expense submissions trigger an "incident report" (始末書 / *shimatsu-sho*) and HR performance deductions. The social cost of asking a human (the General Affairs department, *Soumu-bu*) the same question repeatedly is high, which paradoxically *suppresses* healthy clarification and increases compliance errors.
3. **Single points of failure.** A named individual — in this demo, "Mr. Sato in General Affairs, ext. 1234" — becomes the human bottleneck for health-insurance-card reissuance, shift filings, expense-template distribution, and dozens of unrelated requests. This is the canonical Japanese SME bottleneck.
4. **Specialized vocabulary and severe orthographic variation.** A Japanese employee asks "深夜帰りのタクシー代いくら？" (colloquial), while the policy is written as "業務終了時刻が23:00を超え" (formal). Bridging this gap requires **Hybrid Search**: pure semantic search alone misses form identifiers (`F-021`, `DL-HR-RG-2024-007`), and pure keyword search misses the colloquial-to-formal gap.
5. **Tool fragmentation typical of Japanese workplaces.** Files live on Google Drive or a "社内共有ドライブ" (internal shared drive), conversations happen on Slack/Teams/Chatwork, approvals run through a separate workflow tool ("Coconala-Flow" in this demo), and HR records sit in yet another system. **n8n is the glue** that turns "request → file delivery → audit log" into a single conversational action.

### What this architecture solves

By combining **Dify (high-precision RAG with anti-hallucination guardrails)** and **n8n (executable back-office automation)**, this demo demonstrates:

- **Deflection of 60–80% of repetitive questions** away from the General Affairs bottleneck (Mr. Sato), while preserving the citation trail required for Japanese audit and labor-compliance culture.
- **Zero-hallucination boundary.** When the policy is silent, the bot does not improvise. It returns a strict, fixed deflection message naming the responsible department and contact — matching the cultural expectation of clear accountability (責任の所在 / *sekinin no shozai*).
- **End-to-end automation, not just Q&A.** The "give me the expense template" intent is not answered by the LLM. It triggers an authenticated n8n webhook that resolves the file, serves it from the company's own server, and returns a download link with the submission deadline and policy reference. The full cloud variant (§4-1) extends the same webhook to Drive, a Slack Block Kit card and an audit log in Google Sheets. This is the difference between a chatbot and a back-office automation system.

### Reusability beyond Japan

The same Chatflow topology (Classifier → Hybrid Retrieval → Guardrailed LLM → Webhook) generalizes to:

- US/EU SMEs with similarly fragmented HR policies and SOPs (PTO, expense, compliance training, OSHA filings).
- Multi-site manufacturing firms in Southeast Asia where regulatory documents are bilingual.
- Healthcare and legal firms where citation and refusal-to-hallucinate are non-negotiable.

To localize this architecture for another region, only two layers need to change:

1. **Knowledge corpus** — replace the regulation document.
2. **System-prompt language and deflection contact** — substitute the responsible department / named owner.

Retrieval needs no change: ranking is a Weighted Score computed inside Weaviate (§3-3 ④), so
there is no language-specific reranking model to swap out — and no third-party reranking
service in the data path.

The Chatflow graph, the intent classifier, and the n8n integration pattern remain unchanged. **This portability is the core value proposition** we sell to clients evaluating us on Coconala (domestic Japan) and Upwork (global).

> **On the guardrail.** Earlier revisions of this document placed a score gate between
> retrieval and the LLM. Measurement showed that in-scope and out-of-scope similarity scores
> overlap (0.3623–0.6438 vs 0.2144–0.3849), so no threshold separates them and the gate was
> removed. The zero-hallucination boundary is enforced by the system prompt, and verified by
> an automated test rather than asserted (§2-4, §3-4).

---

## 0. Overall architecture (bird's-eye view)

```
┌────────────────────────────────────────────────────────────────────┐
│  [User]                                                             │
│   ⇣ asks in natural language                                        │
│  ┌──────────────────────────────────────────┐                       │
│  │     Dify Chatflow (workflow mode)         │                       │
│  │ ┌──────────────────────────────────────┐ │                       │
│  │ │ ①START (sys.query)                   │ │                       │
│  │ │   ↓                                  │ │                       │
│  │ │ ②Question Classifier (Intent Detect) │ │                       │
│  │ │   ├─ Policy Q&A → ③                 │ │                       │
│  │ │   └─ File request → ⑥               │ │                       │
│  │ │   ↓                                  │ │                       │
│  │ │ ③Knowledge Retrieval                 │ │                       │
│  │ │   (Hybrid + Weighted Score 0.7/0.3)  │ │                       │
│  │ │   ↓                                  │ │                       │
│  │ │ ⑤LLM answer + Citation               │ │                       │
│  │ │   (fixed refusal if no grounding)    │ │                       │
│  │ │   ↓                                  │ │                       │
│  │ │ ⑧Answer (Streaming)                  │ │                       │
│  │ │                                      │ │                       │
│  │ │ ⑥HTTP Request → n8n Webhook         │ │ ─── Webhook ──┐       │
│  │ │   ↓                                  │ │              ⇣       │
│  │ │ ⑥'Code (JSON parse)                  │ │     ┌─────────────┐  │
│  │ │   ↓                                  │ │     │   n8n        │  │
│  │ │ ⑧'Answer (file reply)                │ │     │ ┌──────────┐ │  │
│  │ └──────────────────────────────────────┘ │     │ │Webhook In│ │  │
│  └──────────────────────────────────────────┘     │ │  ↓       │ │  │
│                                                    │ │Switch    │ │  │
│  Knowledge Base:                                   │ │  ↓       │ │  │
│   - 01_dummy_manual_demo_logistics.txt             │ │Read File │ │  │
│     (Parent-Child, vectorized, BM25 indexed)       │ │  ↓       │ │  │
│                                                    │ │Respond   │ │  │
│                                                    │ └──────────┘ │  │
│                                                    └──────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

---

## 1. System prompt (controlling LLM behavior)

### 1-1. Where it goes
Paste the following into the **System Message** of the "LLM" node in the Chatflow (node ID: `llm_answerer`).

### 1-2. Prompt text (copy-paste)

The prompt is in Japanese because the bot answers in Japanese. In summary: answer only from
`<context>`; if the context does not contain the answer, reply with the fixed fallback message
naming Mr. Sato in General Affairs; no general legal or tax commentary; quote amounts and
deadlines verbatim; refer exception requests to General Affairs; use the three-block format
(Conclusion / Details / Source); no hedging, no invented article numbers. The full English
translation is in the [README](./README.md#prompt-engineering-system-message).

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
{{#context#}}
</context>
```

> ⚠️ **It must be `{{#context#}}`.** The only placeholder Dify substitutes with the retrieved
> context is `{{#context#}}` (`graphon/nodes/llm/llm_utils.py: CONTEXT_PLACEHOLDER`).
> The `{{#context.result#}}` used up to v1.4 is never replaced, so the LLM receives that literal string.
> Nothing errors; you silently end up with "a bot that never looks at the knowledge base". This was
> the most dangerous typo in the document. Details in §4-8 ⑧.

### 1-3. Design rationale
- Wrapping the knowledge in a `<context>` tag tells the LLM explicitly "this is the source of truth". Both OpenAI and Anthropic models follow instructions more reliably when inputs are given in XML-tag structure.
- Making the model reproduce the "not covered" message **word for word** suppresses hallucination and makes accountability (Sato) explicit.
- The three-block answer format is designed so executives can read "conclusion first" (an application of the PREP method).

---

## 2. Chatflow node design (detail)

### 2-1. Node list

| # | Node name | Type | Node ID | Role |
|---|---|---|---|---|
| ① | START | Start node | `start` | Receives user input (`sys.query`) |
| ② | Intent classifier (インテント分類) | Question Classifier | `intent_classifier` | Decides "Q&A" vs. "file request" |
| ③ | Knowledge retrieval (ナレッジ検索) | Knowledge Retrieval | `kb_retrieval` | Hybrid Search + Weighted Score |
| ⑤ | Answer generation (回答生成) | LLM | `llm_answerer` | Generates the answer under the system prompt |
| ⑥ | Webhook call | HTTP Request | `n8n_webhook` | POST request to n8n |
| ⑥' | Response parsing (レスポンス解析) | Code (python3) | `parse_response` | Expands n8n's JSON string into variables |
| ⑧ | Final output | Answer | `final_answer` | LLM output |
| ⑧' | File reply (ファイル回答) | Answer | `file_answer` | Formats and outputs the n8n response |

**Nodes dropped (changes from v1.4)**

| # | Node name | Why it was dropped |
|---|---|---|
| ④ | Score check (IF/ELSE) | Measurement showed a score threshold cannot separate in-scope from out-of-scope (§2-4, §3-3 ⑤) |
| ⑦ | Refusal answer (fixed-text Answer) | With ④ gone, nothing routes to it. Refusal is handled by the §1-2 system prompt |

Actual graph:

```
[① START] → [② Intent classifier] ─ Class 1 ─→ [③ Knowledge retrieval] → [⑤ LLM] → [⑧ Answer]
                                  └ Class 2 ─→ [⑥ HTTP Request] → [⑥' Code] → [⑧' Answer]
```

### 2-2. Node ② Question Classifier settings

**Classifier prompt** (Japanese, used as-is). It defines Class 1 "policy Q&A" (questions about policy
content, e.g. "What is the taxi cap?", "When is the expense deadline?") and Class 2 "file request"
(requests to send or download the expense template, e.g. "Send me the expense format", "I want the
template link"), and says to choose Class 1 when in doubt.

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

**Routing:**
- Class 1 → ③
- Class 2 → ⑥ (n8n Webhook)

### 2-3. Node ③ Knowledge Retrieval settings

This node inherits the Retrieval Setting configured when the knowledge base was created (§3-3 ③–⑤), so **selecting the knowledge base is all that is needed**. The effective values in this demo:

| Item | Value | Notes |
|---|---|---|
| Search mode | **Hybrid Search** (Vector + Full-Text) | Select the `Hybrid Search` card in the UI |
| Hybrid submode | **Weighted Score** | No external Rerank API. See §3-3 ④ |
| Weights | Semantic `0.7` / Keyword `0.3` | |
| Top K | `4` | Final number of chunks passed to the prompt |
| Score Threshold | `0.3` (ON) | **A noise filter**, not a guardrail (§3-3 ⑤) |
| Metadata filter | `disabled` (this demo) | Single-document setup. With multiple knowledge sources, use `doc_type = "regulation"` |

### 2-4. Node ④ IF/ELSE (**dropped**)

v1.4 branched on "Rerank score > 0.5" and returned the fixed refusal below the threshold.
**Measurement showed this design does not work, so it was dropped in v1.5.**

Measurements (`scripts/measure_recall.py`, Weighted Score, Top K=4):

| Query set | Range of top score |
|---|---|
| In-scope queries (the 10 in §3-4) | **0.3623 – 0.6438** |
| Out-of-scope queries (4, e.g. "Do I get an allowance for adopting a cat?") | **0.2144 – 0.3849** |

The ranges overlap, so **no threshold can separate in-scope from out-of-scope**.
Raise it and correct questions are dropped; lower it and out-of-scope ones get through.
The approach of "preventing hallucination with a score gate" therefore does not hold.

**Instead, the guardrail is the §1-2 system prompt (non-negotiable rule 2):**
refuse with the fixed message when `<context>` contains no grounding. The live test
(`scripts/test_e2e.py` Test 2) confirms that "猫を飼ったら手当出る？" (allowance for adopting a cat?)
returns the fixed message, the contact name and the extension.

> Reference: the fixed refusal message (written in the system prompt). In English: "No explicit
> provision covering your question was found in the internal rules (DL-HR-RG-2024-007). Please
> contact Mr. Sato in General Affairs directly (ext. 1234 / sato.kenichi@…)."
> ```text
> ご質問の件について、社内規程（DL-HR-RG-2024-007）内に明示的な記載が見当たりませんでした。
> 詳細については総務部の佐藤（内線1234／sato.kenichi@demo-logistics.example.co.jp）まで直接お問い合わせください。
> ```

---

## 3. Why hybrid search (Vector + Keyword) matters, and how it is designed

### 3-1. Why hybrid, in one line each
- **Vector search alone** catches **semantically similar phrasing** such as "late-night ride home", "late at night", "after the last train", but is weak on **specific numbers and codes** like "F-021" and "DL-HR-RG-2024-007".
- **Keyword search (BM25) alone** is strong on specific numbers and article numbers, but weak on colloquial variation.
- **Combining both** makes retrieval robust to both phrasing variation and proper nouns. (A Rerank model can further re-score contextual relevance; this demo uses Weighted Score instead, see §3-3 ④.)

### 3-2. Expected phrasing variation (common real-world patterns)

| Colloquial user phrasing | Formal wording in the policy | Countermeasure |
|---|---|---|
| "深夜帰りのタクシー代いくら？" (late-night taxi home, how much?) | "業務終了時刻が23:00を超え" (work ends after 23:00), "タクシー代の支給要件" (taxi fare eligibility) | Vector catches the semantic similarity |
| "経費の締め切りいつ？" (expense deadline?) | "経費精算書の提出期限" (submission deadline), "毎月25日17:00必着" (must arrive by 17:00 on the 25th) | Vector catches the intent |
| "テンプレ v3" (template v3) | "経費精算テンプレート_v3.xlsx" | BM25 catches the file name |
| "保険証なくした" (lost my insurance card) | "健康保険被保険者証" (health insurance card), "再交付申請書（F-031）" (reissue form) | Hybrid (both needed) |
| "F-021って何？" (what is F-021?) | "タクシー代超過利用理由書" (taxi excess justification form) | BM25 required |
| "夜勤の申込いつまで？" (night-shift filing deadline?) | "深夜シフトの申請期日" (night-shift application deadline), "前々週金曜日17:00" (17:00 Friday two weeks before) | Vector + ranking narrows to the clause |

### 3-3. Dify knowledge settings (recommended parameters)

#### ① Chunking

> **Important unit note:** chunk lengths in the Dify UI are in **`characters`**. This document originally used `tokens`; to match the UI, the values below give **`characters` first, with the `tokens` equivalent in parentheses**. For Japanese with `text-embedding-3-large` (cl100k_base tokenizer), roughly **1 Japanese character ≈ 1–1.5 tokens**.

> ⚠️ **Upload a `.txt` file, not `.md`.** Dify's Markdown extractor splits the document at every
> heading matching `^#+\s` **before** the chunk settings are applied. Upload the `.md` as-is and
> every `#### 第N項` (clause item) becomes its own Parent, so the Delimiter and Maximum chunk
> length set here are **effectively ignored**. Details in §4-8 ⑥.
> In this demo, `scripts/provision_knowledge.py` generates a `.txt` with only the `#### ` headings
> flattened and uploads that (the `### 第N条` article headings are kept because they serve as the Delimiter).

- **Chunk mode: hierarchical (Parent-Child)** (shown in the UI as `Parent-child`)
  - **Parent-chunk for Context: `Paragraph`** mode (not `Full Doc`)
    - Delimiter: **`\n### `** (splits on article headings `### 第N条（...）`)
      - ⚠️ **The delimiter must not contain Japanese.** Dify runs the delimiter through
        `codecs.decode(sep, "unicode_escape")`, so `\n第` is mangled into `\nç¬¬` and can never
        match. v1.4's `\n### \n#### \n第` does not work (§4-8 ⑤).
      - The delimiter is stripped from the chunk text, so each Parent starts with `第N条（...）`.
    - Maximum chunk length: **`1,400` characters**
      - v1.4 used 1,200, but the longest clause, Article 5 (taxi fare eligibility), is **1,287
        characters**, so 1,200 splits it in the middle. The real damage: for "深夜帰りのタクシー代いくら？"
        clause 2 matched, but the returned Parent no longer contained clause 1 (the actual answer) and
        fell out of the Top 4. At 1,400, all 21 articles fit whole in one Parent each (measured: 21
        Parents, Article 5 = 1,254 characters).
  - **Child-chunk for Retrieval** (what gets embedded; controls semantic granularity)
    - Delimiter: `\n` (newline)
    - Maximum chunk length: **`250` characters** (≈ 300–375 tokens)
      - Larger values such as 512 tend to mix several items into one chunk and reduce hit accuracy against phrasing variation. If the Recall@4 test (§3-4) falls below 90%, lower it to 200 and re-evaluate.
- **About overlap:** in Dify's Parent-Child mode **there is no overlap setting in the UI** (it appears only in General / single-chunk mode). Dify manages child-chunk overlap internally, so **nothing needs to be set** in this mode.
- **Text Pre-processing Rules**
  - ✅ **Replace consecutive spaces, newlines and tabs**: ON (recommended)
  - ❌ **Delete all URLs and email addresses**: **must stay OFF**. In this demo the fixed refusal cites the e-mail address of Sato in General Affairs (`sato.kenichi@demo-logistics.example.co.jp`). Turning this on deletes the contact details from the policy, and the cited "please contact Sato in General Affairs" refusal no longer works.

#### ② Indexing
- **Embedding model:** `text-embedding-3-large` (excellent Japanese performance, 3072 dimensions)
  - If cost matters, `text-embedding-3-small` (1536 dimensions) is also fine. For policy documents the accuracy difference is negligible (about 1/6.5 of the cost).
  - ⚠️ In High Quality mode the embedding model cannot be changed once embedding finishes. Changing it requires a rebuild, so **decide it at initial setup**.
- **Index method:** High Quality (Economy mode is prohibited, and is not selectable in Parent-Child mode anyway)

#### ③ Retrieval Setting

The `Retrieval Setting` card in the UI offers three options. **Choose `Hybrid Search`.**

| Option | Adopted | Reason |
|---|---|---|
| Vector Search | ❌ | Misses specific numbers (`F-021`, `DL-HR-RG-2024-007`) and file names (`経費精算テンプレート_v3.xlsx`) |
| Full-Text Search | ❌ | Weak on colloquial variation ("深夜帰り" late-night ride → "23:00を超え" after 23:00) |
| **Hybrid Search** | ✅ | Runs Vector + Full-Text in parallel so each covers the other's weakness |

#### ④ Hybrid Search submode (Weighted Score vs. Rerank Model)

Choosing `Hybrid Search` reveals two further submodes. **Choose `Weighted Score`** (changed from v1.4).

| Submode | Ranking logic | Adopted |
|---|---|---|
| **Weighted Score** | Linear combination with **fixed weights** for Semantic / Keyword (Semantic `0.7` / Keyword `0.3`) | ✅ **Used in this demo** |
| Rerank Model | A rerank model **re-orders results dynamically per query** using context | ❌ More data egress, zero accuracy gain in this case |

**Why Weighted Score (two reasons, both measured)**

1. **No additional data egress.** The selling point of §4-7 is "your data never leaves the building".
   Cohere rerank sends **the user's question and the matching policy text itself** to a third party
   other than the LLM provider. For a setup pitched to SME owners as "fully in-house", that is a clear hole.
   Weighted Score is computed inside Weaviate, so the only egress is OpenAI (embeddings and LLM).
2. **No loss of accuracy.** On the 10 queries in §3-4, **both scored Recall@4 = 100%**.
   When the document is small (21 articles, about 6,400 characters) and Parents are cut per
   article, as here, there is almost nothing left for a reranker to reorder.

> 💡 In addition, Cohere's trial key is rate-limited to **about 10 requests per minute**, and when
> it is exceeded Dify returns **zero search results without an error**. The bot simply refuses with
> "not found in the policy", which makes the cause hard to find. Hitting this while recording a demo
> is fatal (§4-8 ⑦).
>
> If the document volume grows and reranking becomes necessary, the recommended approach for keeping
> the setup fully closed is to run `jina-reranker-v2-base-multilingual` or similar locally with
> Xinference / TEI and register it as a Dify model provider (rather than calling the Cohere API directly).

#### ⑤ Retrieval parameters

| Item | Value |
|---|---|
| **Semantic Weight** | `0.7` |
| **Keyword Weight** | `0.3` |
| **Top K** | `4` (final number passed to the LLM) |
| **Score Threshold** | `0.3` (ON) |

> ⚠️ **A Score Threshold of `0.5` is wrong** (as written in v1.4). Measured Weighted Score values
> for in-scope queries are 0.3623–0.6438, so 0.5 drops most correct questions.
>
> More importantly, **the threshold does not work as a guardrail**. Out-of-scope queries score up to
> 0.3849, above the lowest in-scope score of 0.3623 (table in §2-4).
> `0.3` is set as a noise filter that cuts the clearly irrelevant, and hallucination prevention is
> the job of the §1-2 system prompt.
>
> To re-measure: `python3 scripts/measure_recall.py --threshold 0.3`

#### ⑥ Metadata

> ⚠️ Dify metadata is **a two-step setup**. "Defining the fields (schema)" and "assigning values to each document" are separate screens and separate operations.

##### Step 1: Define custom metadata fields (schema)

Knowledge screen → top-right `Metadata` button → `+ Add Metadata`, and define the following six fields as **string**.

| Field name | Type | Purpose |
|---|---|---|
| `doc_id` | string | Policy number (e.g. `DL-HR-RG-2024-007`) / audit trace |
| `doc_title` | string | Policy title (human-readable) |
| `doc_version` | string | Version (e.g. `v3`) / filter key when old and new versions run side by side |
| `last_revised` | string | Revision date (`YYYY-MM-DD`) / change detection for Phase 4 automatic re-embedding |
| `doc_type` | string | Document type (`regulation` / `manual` / `faq`, etc.) / filter when running multiple knowledge sources |
| `category` | string | Department category (`総務` General Affairs / `経理` Accounting / `物流` Logistics, etc.) |

> 💡 `last_revised` can also be defined as `time` in Dify (enables range filters). This demo uses `string` to stay consistent with the JSON spec in this document. Consider switching to `time` for production use where several versions run in parallel for a period.

##### Step 2: Assign values to the document

`Documents` tab → the policy document row → `︙` → `Edit Metadata` (or click the row → `Metadata` section), and enter:

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

(`doc_title` = "Travel & Expense and HR Procedures Policy", `category` = General Affairs.)

To confirm: back on the Metadata screen, each field should change from `0 Values` to **`1 Value`**.

##### Step 3 (recommended): Enable built-in metadata

Turning **ON** the `Built-in` toggle at the bottom of the Metadata screen gives you these five fields **filled in automatically, for free**. Useful as an audit log too.

| Field | Type | Contents |
|---|---|---|
| `document_name` | string | File name |
| `uploader` | string | Who uploaded it |
| `upload_date` | time | Upload timestamp |
| `last_update_date` | time | Last update timestamp |
| `source` | string | Source type (PDF/TXT, etc.) |

##### When metadata matters (not needed for a single document)

| Scenario | Metadata needed? |
|---|---|
| One policy document only (this demo recording) | **Not needed** (no effect on behavior without it) |
| Multiple documents: policy + procedures + FAQ | Filter by `doc_type` |
| Policy v3 and v2 running side by side for a limited period | Filter by `doc_version` + `last_revised` |
| Per-department bots (separate General Affairs / Accounting / Logistics bots) | Filter by `category` |
| Phase 4 (automatic re-embedding) | Change detection via `last_revised` |
| Audit requirement (record which version an answer referenced) | Keep `doc_id` + `doc_version` in the answer log |

> Citations are designed to be extracted by the LLM from the **policy text header** ("文書番号：DL-HR-RG-2024-007", document number), not from metadata, so citations work even without metadata.

### 3-4. Test queries for verification (10)
Check Recall@4 with these queries before any production release.

| # | Test query | Meaning | Expected clause |
|---|---|---|---|
| 1 | 深夜帰りのタクシー代いくら？ | Late-night taxi home: how much? | Art. 5 §1 |
| 2 | クライアントとタクシー乗っていいの？ | Can I take a taxi with a client? | Art. 5 §2 |
| 3 | タクシー上限超えた | I went over the taxi cap | Art. 5 §4 (F-021) |
| 4 | 経費の締め切りいつ？ | When is the expense deadline? | Art. 8 §1 |
| 5 | テンプレ v3 どこ？ | Where is template v3? | Art. 9 §2 |
| 6 | 25日過ぎちゃった | I missed the 25th | Art. 8 §3–4 |
| 7 | 保険証なくした | I lost my health insurance card | Art. 15 |
| 8 | 夜勤手当いくら？ | How much is the night-shift allowance? | Art. 13 |
| 9 | 深夜シフトいつまでに申請？ | When must I file for a night shift? | Art. 14 §1 |
| 10 | 新幹線グリーン車乗れる？ | Can I ride Shinkansen first class? | Art. 4 §2 |

If the expected clause is in the Top 4 for every query, Recall@4 = 100%. The production-quality bar is Recall@4 >= 90%.

#### Measured results (2026-08-06, `scripts/measure_recall.py`)

Configuration: Hybrid Search + Weighted Score (0.7 / 0.3) / Top K = 4 / Score Threshold = 0.3
/ Embedding: text-embedding-3-large / Parent-Child (Parent 1,400 / Child 250)

```
Recall@4 = 10/10 = 100%   (target: >= 90%)

  in-scope     top-score  0.3623 .. 0.6438
  out-of-scope top-score  0.0000 .. 0.3849   (3 of 4 return zero hits)
```

For all 10 questions the expected clause was in the Top 4. With the 0.3 threshold applied, 3 of the
4 out-of-scope queries return zero hits, and only one ("有給休暇は何日もらえますか？", how many days of
paid leave, an HR question the policy does not cover) gets through at 0.3849. The §1-2 system prompt
refuses that one with the fixed message.

To reproduce:
```bash
python3 scripts/measure_recall.py --threshold 0.3
```

---

## 4. n8n webhook integration logic

### 4-1. Intent detection logic (Dify side)

When node ② Question Classifier assigns **"Class 2: file request"**, the following happens.

#### Node ⑥ HTTP Request settings

| Item | Value |
|---|---|
| Method | POST |
| URL | `https://n8n.demo-logistics.example.co.jp/webhook/expense-template` |
| Header | `Content-Type: application/json` |
| Header | `X-Auth-Token: {{#env.N8N_WEBHOOK_TOKEN#}}` |
| Body (JSON) | See below |
| Timeout | 10 seconds |
| Retries | 2 (exponential backoff) |

**Request body (JSON):**
```json
{
  "intent": "request_expense_template",
  "user_id": "{{#sys.user_id#}}",
  "user_query": "{{#sys.query#}}",
  "conversation_id": "{{#sys.conversation_id#}}",
  "requested_at": "{{#sys.timestamp#}}",
  "metadata": {
    "source": "dify-chatflow",
    "template_key": "expense_template_v3"
  }
}
```

> ⚠️ **It must be `{{#sys.timestamp#}}`.** The `{{#sys.current_time#}}` system variable used in v1.4
> does not exist in Dify (`SystemVariableKey` defines `query` / `files` / `conversation_id` /
> `user_id` / `dialogue_count` / `app_id` / `workflow_id` / `workflow_run_id` / `timestamp`, etc.).
> A nonexistent variable just becomes an empty string without an error, so it is easy to miss.

#### Final answer using node ⑥'s response (⑧ Answer node)

Japanese reply text for the full cloud variant. In English: "Your expense template is ready. A
download link has been sent to you on Slack (#general or DM). [File sent] expense template v3,
stored at shared drive → 02_General Affairs. [Note] Deadline: 17:00 on the 25th of each month
(Art. 8). Always enable macros (Art. 9 §4). [Source] DL-HR-RG-2024-007 Arts. 8 and 9."

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

### 4-2. n8n workflow design (flow diagram)

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
│  [Node 3: Switch (route by intent)]                         │
│    ├─ "request_expense_template"  → Node 4                  │
│    ├─ "request_taxi_form"         → future extension        │
│    └─ default                     → Node 99 (error reply)   │
│       ↓                                                      │
│  [Node 4: Google Drive - Get Shared Link]                   │
│    File ID: <fixed ID of 経費精算テンプレート_v3.xlsx>        │
│    Mode: Generate shareable link (anyone with link, viewer) │
│    Output: $json.webViewLink                                │
│       ↓                                                      │
│  [Node 5: Lookup Slack User ID]                             │
│    (resolve dify user_id → Slack user_id via the HR system  │
│     or the Google Workspace Directory)                      │
│       ↓                                                      │
│  [Node 6: Slack - Send Direct Message]                      │
│    Channel: {{$node["Node 5"].json.slack_user_id}}          │
│    Text: (see template below)                               │
│    Blocks: Block Kit format (see below)                     │
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

### 4-3. Slack Block Kit payload (Node 6)

The card's texts are Japanese: header "Here is your expense template", fields for file name,
deadline and policy reference, buttons "Download" and "View policy", and a footer "Sent
automatically by Demo-Logi-Bot | Questions: Sato, General Affairs (ext. 1234)".

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

### 4-4. Error handling (Node 99)

| Error case | Handling |
|---|---|
| Slack user lookup fails | Notify the General Affairs channel `#admin-bot-alert` and fall back to a public post in `#general` |
| Google Drive fetch fails | Retry once after 30 seconds. On failure return HTTP 500 to Dify, which falls back to "please contact General Affairs directly" |
| Webhook authentication fails | Return 401 immediately and log it |

### 4-5. Security

- Use a webhook path containing **a hard-to-guess random string** (e.g. `/webhook/expense-template-9d7f3a2c`)
- Authenticate with a shared secret in the **X-Auth-Token** header (Dify environment variable → n8n credentials)
- On the n8n side, use an **IP allowlist** so only the Dify instance can connect (when self-hosted)
- Keep no PII in logs (user_id only; never record names or e-mail addresses)

---

### 4-6. Simple pattern: replying with a Google Drive URL directly (recommended starter setup)

Before building n8n, Slack and per-user resolution, or for small deployments, a simple version in which **Dify just returns a Google Drive URL shared as "anyone with the link can view"** is perfectly usable. This repository ships the dummy Excel file to distribute, `経費精算テンプレート_v3.xlsx`.

#### ① Preparing Google Drive

1. Upload `経費精算テンプレート_v3.xlsx` to the internal shared drive (e.g. the `02_総務部` / General Affairs folder).
2. Right-click the file → "Share" → change to **"Anyone with the link"** and set the permission to **"Viewer"**.
   - For internal use only, it is better to restrict it to "anyone in the organization's domain with the link (demo-logistics.example.co.jp)".
3. Register the URL from "Copy link" (e.g. `https://drive.google.com/file/d/1aBcDEFghiJKLmnOPqrSTuvWxyz0123456/view?usp=sharing`) as the Dify environment variable `EXPENSE_TEMPLATE_URL`.

> Note: "anyone with the link" security relies on the File ID being hard to guess. It is not suitable for truly confidential files. This template is a blank form with no sensitive information, so this approach is acceptable.

#### ② Dify flow (simplified)

When node ② Question Classifier assigns **"Class 2: file request"**, skip the n8n webhook and return fixed text plus the URL **directly from an Answer node**.

```
[② Question Classifier]
   └─ Class 2 (file request) → [⑥' Answer (fixed text + URL)]  ← does not go through n8n
```

Body of node ⑥' Answer (copy-paste). In English it says: the template can be downloaded from
the Google Drive link; lists the five sheets (expense report, taxi log for Art. 5, advance
settlement for Art. 12, category master, instructions); the deadline (17:00 on the 25th, Art. 8);
that old v2 forms are rejected (Art. 9 §3); that taxi rides over JPY 15,000 require form F-021
(Art. 5 §4); and the source and contacts.

```text
経費精算テンプレートはこちらのGoogle Driveリンクからダウンロードできます。

📎 経費精算テンプレート_v3.xlsx
{{#env.EXPENSE_TEMPLATE_URL#}}

（社内ドライブ上のパス：02_総務部 ➔ 経費精算テンプレート_v3.xlsx）

【含まれるシート】
- 経費精算書（メイン）
- タクシー利用明細（規程第5条 詳細記録用）
- 仮払い精算（規程第12条）
- 区分マスタ（ドロップダウン用）
- 記入要領（提出期限・タクシー上限などの解説）

【提出期限・注意事項】
- 提出期限：毎月25日17:00必着（規程第8条）
- v2以前の旧フォーマットでの申請は受理されません（規程第9条第3項）
- タクシー代1回15,000円超過時は F-021 超過理由書 が必要です（規程第5条第4項）

【引用元】
規程：DL-HR-RG-2024-007 第8条・第9条
窓口：総務部 佐藤（内線1234）／ 経理部 鈴木（内線1456）
```

#### ③ Dify environment variable

Add the following under `Settings ➔ Environment Variables`:

| Key | Value | Type |
|---|---|---|
| `EXPENSE_TEMPLATE_URL` | `https://drive.google.com/file/d/<FILE_ID>/view?usp=sharing` | Secret (masked display recommended) |

#### ④ Simple version vs. full version (through n8n)

| Aspect | Simple version (4-6) | Full version (4-1 to 4-5) |
|---|---|---|
| Implementation effort | Low (Dify only, one extra Answer node) | Medium to high (n8n + Slack + Drive API + Sheets log) |
| Audit log | Dify conversation logs only | Structured records in n8n's Sheets log |
| Delivery channel | URL in the chat (copy-paste) | Block Kit button in a Slack DM |
| User identification | Not needed | Must resolve dify user_id → Slack user_id |
| When the file is updated | Overwrite on Drive; the URL stays the same | Overwrite on Drive; the URL stays the same |
| Recommended for | PoC, small internal use, tight budgets | 50+ employees, audit requirements, established Slack culture |

#### ⑤ Dummy file `経費精算テンプレート_v3.xlsx` (included in this repository)

The repository's `経費精算テンプレート_v3.xlsx` complies with policy DL-HR-RG-2024-007 and contains the following. In the demo video you can actually upload it to Drive and record the bot returning the link.

- "Expense report" sheet: applicant header, 9 sample line items (train, Shinkansen, day and night taxi, lodging, client entertainment, supplies), automatic totals with SUM formulas, advance-payment deduction, a five-person approval block, F-021 / F-007 notes
- "Taxi log" sheet: boarding time, drop-off time, pick-up and drop-off locations and F-021 status, per Article 5
- "Advance settlement" sheet: automatic calculation of the difference between advance and actual cost
- "Category master" sheet: 13 categories for drop-downs with account codes and policy references
- "Instructions" sheet: deadline, taxi cap, receipt rules and contacts in one place

Regenerate the file with `python3 scripts/build_expense_template.py` (requires `openpyxl`).

---

### 4-7. Fully local Docker setup (the primary pattern for SME projects)

A third pattern that sits between §4-1 to 4-5 (the full cloud-API version) and §4-6 (the simple
Drive-URL version): **everything runs on the company's own server**. Because it lets you tell SME
owners "your data never leaves the building" and mean it, it is the recommended default for this demo.

#### ① Architecture overview

```
┌────────────────────────────────────────────────────────────────┐
│  On-prem server / development Mac (Docker host)                  │
│                                                                  │
│  Shared network: demo-rag-net (external bridge)                  │
│  ┌─────────────────────────┬──────────────────────────────────┐ │
│  │  [Dify Self-Hosted]      │  [n8n Self-Hosted]                │ │
│  │  - api / worker / web    │  - n8n_local container            │ │
│  │  - postgres / redis      │  - Workflow 1: Intent Dispatcher  │ │
│  │  - weaviate / sandbox    │  - Workflow 2: File Server        │ │
│  │  - nginx (port 80)       │  - port 5678                       │ │
│  │                          │  - templates/ (bind mount)         │ │
│  └─────────────────────────┴──────────────────────────────────┘ │
│           ↑ Browser:80              ↑ Browser:5678              │
│           │                         │ (file download click)     │
└───────────┼─────────────────────────┼──────────────────────────┘
            │                         │
       [Employee's Browser]      [Employee's Browser]

  Dify→n8n internal call:  http://n8n_local:5678/webhook/<UUID>  (Docker DNS)
  Browser→file download:   http://localhost:5678/webhook/files/expense-v3 (host port)
```

> 💡 **The key is the "two URLs" design:** from Dify, n8n is the internal DNS name `n8n_local`; from the browser, n8n is `localhost`. The `download_url` in the JSON returned to Dify must be **the URL the browser will open** (`localhost:5678`). With `n8n_local:5678` the browser cannot resolve it and fails with "ERR_NAME_NOT_RESOLVED".

#### ② n8n workflows (two)

##### Workflow 1: Intent Dispatcher (receives POST)

```
[Webhook] → [Edit Fields] → [Switch] ─Output 0 (expense)─→ [Respond to Webhook (JSON)]
                                      ├─Output 1 (taxi)──→ [Respond to Webhook (501)]
                                      └─Fallback───────────→ [Respond to Webhook (400)]
```

| Node | Settings |
|---|---|
| Webhook | Method: POST / Path: hard-to-guess UUID / Auth: Header Auth (`X-Auth-Token`) / Respond: **`Using 'Respond to Webhook' Node`** ⚠️ required |
| Edit Fields | Manual Mapping: `user_id={{$json.body.user_id}}`, `intent={{$json.body.intent}}`, `template_key={{$json.body.metadata.template_key}}` |
| Switch | Mode: Rules / Output 0 = `intent equals "request_expense_template"` / Output 1 = `intent equals "request_taxi_form"` / Fallback Output = **Extra Output** ⚠️ |
| Respond to Webhook (Output 0) | JSON, code 200, body as in §4-7 ④ (includes `download_url`) |
| Respond to Webhook (Fallback) | JSON, code 400, "Unknown intent" message |

##### Workflow 2: File Server (receives GET, binary response)

```
[Webhook (GET)] ─→ [Read/Write Files from Disk] ─→ [Respond to Webhook (Binary)]
```

| Node | Settings |
|---|---|
| Webhook | Method: GET / Path: `files/expense-v3` / Auth: None (the path itself acts as the token) / Respond: **`Using 'Respond to Webhook' Node`** |
| Read/Write Files from Disk | Operation: `Read File(s) From Disk` / File Selector: **`/home/node/.n8n-files/expense_template_v3.xlsx`** ⚠️ allowlist restriction (see §4-8) |
| Respond to Webhook | Respond With: **`Binary`** / Input Field Name: `data` / Headers: `Content-Type` + `Content-Disposition` (RFC 5987 form, see §4-8) |

#### ③ Dify HTTP Request node settings (self-hosted)

| Item | Value |
|---|---|
| Method | POST |
| **URL** | **`http://n8n_local:5678/webhook/<Workflow 1 UUID>`** (Docker internal DNS name) |
| Header | `Content-Type: application/json` |
| Header | `X-Auth-Token: {{#env.N8N_WEBHOOK_TOKEN#}}` |
| Body (JSON) | Same as §4-1 |

> ⚠️ When calling from Dify Cloud, `http://n8n_local:...` does not work; use a URL exposed with ngrok or similar, such as `https://xxxx.ngrok-free.app/webhook/<UUID>` (the cloud-style URL in §4-1). This setup **assumes self-hosting**.

#### ④ JSON returned by Workflow 1 Output 0 (copy-paste)

The user-facing values are Japanese: `message` = "Your expense template is ready; download it from
the URL below", `deadline` = "must arrive by 17:00 on the 25th of each month", `macro_warning` =
"always enable macros (Art. 9 §4)".

```json
{
  "status": "success",
  "intent": "request_expense_template",
  "filename": "経費精算テンプレート_v3.xlsx",
  "download_url": "http://localhost:5678/webhook/files/expense-v3",
  "message": "経費精算テンプレートをご用意しました。下記URLからダウンロードしてください。",
  "regulation_ref": "DL-HR-RG-2024-007 第8条・第9条",
  "deadline": "毎月25日17:00必着",
  "macro_warning": "マクロを必ず有効化してください（規程第9条第4項）"
}
```

#### ⑤ Formatting the answer in the Dify Answer node

> ⚠️ **A Code node is required right after the HTTP Request node.** The HTTP Request node's
> `body` output is a **JSON string**, not an object
> (`graphon/nodes/http_request/node.py`: `outputs["body"] = response.text`).
> So neither `{{#n8n_webhook.body.message#}}` nor v1.4's
> `{{#http_request.response.message#}}` resolves, and the Answer **renders an empty string**.
> No error is raised, so the cause is hard to see (§4-8 ⑨).

**Node ⑥' Code (python3)** — expands n8n's JSON into variables:

```python
import json


def main(body: str) -> dict:
    data = json.loads(body) if body else {}
    keys = ("message", "filename", "download_url", "deadline", "macro_warning", "regulation_ref")
    return {key: str(data.get(key, "")) for key in keys}
```

| Item | Value |
|---|---|
| Input variable | `body` ← `n8n_webhook / body` |
| Output variables | `message` `filename` `download_url` `deadline` `macro_warning` `regulation_ref` (all string) |

> The Code node runs inside Dify's `sandbox` container, so it adds no external traffic.

**Node ⑧' Answer** — formats the user-facing text (labels: 【ご注意】 Note, 提出期限 Deadline,
【引用元】 Source, 規程 Policy, 窓口 Contacts):

```text
{{#parse_response.message#}}

📎 **{{#parse_response.filename#}}**
{{#parse_response.download_url#}}

【ご注意】
- 提出期限：{{#parse_response.deadline#}}
- {{#parse_response.macro_warning#}}

【引用元】
規程：{{#parse_response.regulation_ref#}}
窓口：総務部 佐藤（内線1234）／ 経理部 鈴木（内線1456）
```

#### ⑥ Shared network strategy: the external-network approach

The `docker-compose.yml` files for n8n and Dify are **managed independently**, and communication works by **sharing the external network `demo-rag-net`**. This is a standard Docker pattern, with the advantage that each stack can go up and down on its own.

##### Setup (summary)

```bash
# 1. Create the shared network (once)
docker network create demo-rag-net

# 2. Add network settings to n8n's docker-compose.yml (services + networks sections)
# 3. On the Dify side, add networks to api / worker / ssrf_proxy
#    (layered with an override file; see docker/dify/docker-compose.override.yaml in this repository)

# 4. Restart both
cd ~/n8n-local && docker compose down && docker compose up -d
cd ~/dify-local/docker && docker compose down && docker compose up -d

# 5. Connectivity check (with curl)
docker exec docker-api-1 curl -s http://n8n_local:5678/healthz
# → success if it returns {"status":"ok"}
```

> ⚠️ **Do not forget `ssrf_proxy`. And Step 5 above cannot be trusted.**
> Dify does not let the HTTP Request node open sockets directly; it sends traffic **through the
> squid proxy (`SSRF_PROXY_HTTP_URL=http://ssrf_proxy:3128`)**. So the container that needs to
> resolve `n8n_local` is **squid**, not api / worker.
>
> If only api and worker join the shared network, Step 5's `docker exec docker-api-1 curl`
> **returns 200 and succeeds**, while the Chatflow alone fails with
> `Reached maximum retries for URL http://n8n_local:5678/...`.
> That is the worst possible triage situation: "the connectivity check passes, but it doesn't work".
>
> Joining the network is not enough either: squid's ACL
> (`http_access deny to_private_networks`) returns 403, which Dify reports as
> "Access to '...' was blocked by SSRF protection". Dify's official escape hatch is the
> `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS` environment variable, which is inserted as an
> `acl ... dstdomain` allow rule before the deny. Allowing a single host name rather than a whole
> subnet keeps SSRF protection in place for every other destination. Details in §4-8 ⑩.
>
> ```yaml
> # docker-compose.override.yaml
> services:
>   ssrf_proxy:
>     networks: [ssrf_proxy_network, default, demo-rag-net]
>     environment:
>       SSRF_PROXY_ALLOW_PRIVATE_DOMAINS: n8n_local
> ```

See the `docker/` directory in this repository for the exact YAML edits and the finished files.

#### ⑦ Comparison with §4-1 / §4-6

| Aspect | §4-1 full version (Drive + Slack API) | §4-6 Drive URL reply | **§4-7 fully local** |
|---|---|---|---|
| External API dependencies | Google Drive API + Slack API + LLM + Rerank | Google Drive + LLM | **LLM (OpenAI) only** |
| Data leakage concern | Yes (the files themselves sit on Google) | Yes | **Only policy excerpts and questions go to OpenAI. Files, conversation logs and routing logic stay in-house** |
| Installation effort | High (GCP / Slack App setup) | Low | Medium (docker-compose edits) |
| Persuasiveness for SME clients | △ (owners worry) | ○ | **◎ (you can show it stays in-house)** |
| Audit log | Structured via n8n → Sheets | Dify logs only | n8n logs + optionally an internal DB |
| Recommended for | 50+ employees, already on Slack/Drive | PoC, tight budgets | **Production delivery for SMEs** |

#### ⑧ Demo video line that lands the "two URLs" point

The line is delivered in Japanese. In English: "Take a look. The download URL for this expense
template says 'localhost'. In other words, this process never touched the internet. The file and
the bot's logic all stay inside your own server."

```
「ご注目ください。この経費精算テンプレートのダウンロードURL、
 よく見ると "localhost" になっています。
 つまり、この処理は一度もインターネットに出ていません。
 ファイルも、Botの判断ロジックも、すべて貴社サーバー内で完結しています」
```

→ The moment in an owner-facing presentation that visually proves "your data doesn't leave".

---

### 4-8. Operational lessons found during implementation (verified on real hardware)

This section records the **traps you will never learn from the documentation or official material**,
hit while actually building the §4-7 setup on a macOS development machine. Some of them recur on the
client's production environment (Linux), so it is worth clearing them out during the PoC.

- **①–④:** n8n / Docker / macOS side (found during the initial build)
- **⑤–⑪:** Dify side (found during the v1.5 live verification; the affected sections have been corrected)

> What ⑤ onward have in common: **none of them raise an error; they leave things "silently wrong"**.
> Configuration mistakes show up not as exceptions but as "empty string", "zero results" or "split at
> every heading", so everything appears to work while only the quality drops. Every one of them could
> only be found by measuring (`scripts/measure_recall.py`, `scripts/test_e2e.py`).

#### ① n8n files must live under `/home/node/.n8n-files/`

n8n's `Read/Write Files from Disk` node has a sandbox restriction: by default it **can only access a specific path**.

| Symptom | Error message |
|---|---|
| Any other path specified (e.g. `/home/node/files/`) | `Access to the file is not allowed. Allowed paths: /home/node/.n8n-files` |

**Fix:**
- Point the bind mount at **`/home/node/.n8n-files`** (recommended)
- If you really need another path, extend the allowlist with the environment variable `N8N_RESTRICT_FILE_ACCESS_TO=/home/node/.n8n-files,/home/node/files`

```yaml
# docker-compose.yml
services:
  n8n:
    volumes:
      - ./templates:/home/node/.n8n-files    # ✅ recommended path
```

#### ② The Webhook node's Respond mode must be `Using 'Respond to Webhook' Node`

To return a custom JSON or binary response, **you must change the Webhook node's `Respond` setting from the default `Immediately`**. Forget this and n8n raises a validation error:

> `Unused Respond to Webhook node found in the workflow`

Meaning: "there is a Respond to Webhook node in the workflow, but the Webhook responds immediately, so it can never be reached — a contradictory configuration".

**Fix:**
1. Open the Webhook node's parameter panel
2. Change the `Respond` drop-down to **`Using 'Respond to Webhook' Node`**
3. If there is a Switch or other branching, **put a Respond to Webhook node on every output path** (including Fallback)

```
[Switch] ─ Output 0 ─→ [Respond to Webhook (success 200)]
        ├─ Output 1 ─→ [Respond to Webhook (501)]
        └─ Fallback ─→ [Respond to Webhook (400)]
```

#### ③ On a macOS development machine, extended attributes on Google Drive-synced files must be removed

If a client hands you a file with "the policy is on Google Drive, use that" and you try to use it through a Docker bind mount on a Mac, it fails with **`EPERM: operation not permitted`**.

##### Cause
Files synced by Google Drive (drivefs) get their own ID as a macOS extended attribute:

```bash
$ xattr -l 経費精算テンプレート_v3.xlsx
com.apple.quarantine: ...
com.google.drivefs.item-id#S: 1u0IuXsFRaDlb9CvKmlUvWcClvXEBH7Sf  ← the main culprit
com.apple.provenance: ...
```

`com.google.drivefs.item-id` adds its own permission control at the macOS VFS layer. It propagates into the container through the Docker Desktop bind mount as a "specially managed file", and Node.js's `lstat` system call fails with EPERM.

##### Fix
Strip every extended attribute before placing the file under the bind mount:

```bash
xattr -c <file path>
```

To confirm:
```bash
xattr -l <file path>   # nothing (or only com.apple.macl) is normal
ls -la <file path>      # the trailing @ mark is gone
```

> 💡 `com.apple.macl` is a security attribute macOS adds automatically, and `xattr -c` does not remove it. It **does not affect Docker bind mounts**, so ignore it.

##### Note for production delivery

This does not happen on a Linux server (the client's production server), because extended attributes of this kind are macOS-specific. Treat it as **a development / PoC (Mac) problem** and clear it during the PoC.

#### ④ RFC 5987 form of the Content-Disposition header (Japanese file names)

When Workflow 2 (File Server) returns a binary response from its `Respond to Webhook` node and you want the file saved **with its Japanese name**, the `Content-Disposition` header needs **both forms side by side**.

##### Value

```text
Content-Disposition: attachment; filename="expense_template_v3.xlsx"; filename*=UTF-8''%E7%B5%8C%E8%B2%BB%E7%B2%BE%E7%AE%97%E3%83%86%E3%83%B3%E3%83%97%E3%83%AC%E3%83%BC%E3%83%88_v3.xlsx
```

| Part | Role | Clients |
|---|---|---|
| `filename="expense_template_v3.xlsx"` | ASCII fallback | Older clients without RFC 5987 support, such as curl 8.x (macOS) |
| `filename*=UTF-8''<percent-encoded>` | RFC 5987 standard | **All browsers**: Chrome / Safari / Firefox / Edge |

##### Behavior

| Client | Saved file name |
|---|---|
| Browsers (Chrome, etc.) | `経費精算テンプレート_v3.xlsx` (Japanese) |
| `curl -OJ` (macOS curl 8.x) | `expense_template_v3.xlsx` (ASCII fallback) |

→ **End users click in a browser**, so in production the file is saved under its Japanese name. curl saving it in ASCII is a command-line quirk, not a server-side problem.

##### Generating the encoding

The RFC 5987 percent-encoding of "経費精算テンプレート_v3.xlsx" is:

```
%E7%B5%8C%E8%B2%BB%E7%B2%BE%E7%AE%97%E3%83%86%E3%83%B3%E3%83%97%E3%83%AC%E3%83%BC%E3%83%88_v3.xlsx
```

For other file names, generate it with Python:

```python
from urllib.parse import quote
quote("経費精算テンプレート_v3.xlsx")
# → '%E7%B5%8C%E8%B2%BB%E7%B2%BE%E7%AE%97%E3%83%86%E3%83%B3%E3%83%97%E3%83%AC%E3%83%BC%E3%83%88_v3.xlsx'
```

#### ⑤ Japanese characters in the chunk delimiter get mangled

Dify runs the chunk delimiter through `codecs.decode(separator, "unicode_escape")`
(`core/rag/splitter/fixed_text_splitter.py`). That codec destroys non-ASCII characters.

```python
>>> import codecs
>>> codecs.decode("\n第", "unicode_escape")
'\nç¬¬'          # ← the UTF-8 bytes are reinterpreted as latin-1
>>> codecs.decode("\n### ", "unicode_escape")
'\n### '         # ← ASCII survives intact
```

v1.4's delimiter `\n### \n#### \n第` becomes `\n### \n#### \nç¬¬` at this point.
On top of that, Dify's delimiter is **a single string, not a list**, used as
`text.split(separator)`. So it does not mean "split on ###, ####, or 第"; it means "split on the
contiguous string `\n### \n#### \nç¬¬`", which of course matches nowhere.

**Fix:** use an ASCII-only, single-pattern delimiter. In this demo, `\n### `.
As long as articles are headed `### 第N条（...）`, this splits per article.

#### ⑥ Uploading as `.md` silently ignores the chunk settings

Dify's Markdown extractor splits the document at **every heading** matching
`re.match(r"^#+\s", line)` **before** the chunk settings are applied
(`core/rag/extractor/markdown_extractor.py`). It does not distinguish heading levels.

So when you upload a `.md`:

| Expected | Actual |
|---|---|
| `### 第5条` (Art. 5) is one Parent containing §1–5 | `#### 第1項` to `#### 第5項` (§1–5) are **each a separate Parent** |
| 21 Parents (one per article) | 34 Parents |

The point of Parent-Child is "search on fine-grained children, give the LLM the parent with its
context". When parents split per clause item, **that design falls apart**. The real damage: for
"深夜帰りのタクシー代いくら？" (late-night taxi home, how much?), items 2, 4 and 5 were hit while
item 1, which contains the answer, fell outside the Top 4.

**Fix:** upload a `.txt`. The TextExtractor passes it through as one document without splitting,
so the specified Delimiter and Maximum chunk length take effect correctly.
In this demo, `scripts/provision_knowledge.py` generates a `.txt` with only the `#### ` headings
flattened and uploads it (`### ` is kept because it is used as the Delimiter).

> 💡 A PDF upload avoids this particular problem, but text extraction from Japanese PDFs has its own
> quality issues. Keeping the Markdown as the source of truth in the repository and converting to
> `.txt` only at upload time proved the safest.

#### ⑦ Cohere rerank returns "zero results, not an error" when rate-limited

Cohere's trial key allows roughly **10 requests per minute**. Beyond that it returns 429, but
Dify swallows it and returns the search results as **an empty array**.

How it shows up:
- It works when you try once. Run tests back to back and it suddenly returns zero.
- On the bot side the symptom is **a perfectly normal refusal**: "not found in the policy".
- If you hit it while tuning the score threshold, you misdiagnose it as "the threshold is too strict".

This actually produced the contradictory measurement "zero results even at threshold 0.01", and
time was lost assuming the threshold was the cause. Waiting 45 seconds and re-running returned one
result at 0.9986, revealing the rate limit.

**Fix:**
- Space out requests when measuring in batches (`scripts/measure_recall.py --delay`)
- Switch to a paid key before recording a demo or presenting to a client
- Better still, as in §3-3 ④, do not use an external reranker here, since Weighted Score is just as accurate

#### ⑧ The LLM node's context variable can only be `{{#context#}}`

The placeholder into which Dify inserts the knowledge-retrieval result is fixed as `{{#context#}}`
(`graphon/nodes/llm/llm_utils.py`: `CONTEXT_PLACEHOLDER = "{{#context#}}"`).

Writing `{{#context.result#}}` is **not substituted; the literal string goes to the LLM**.
The LLM sees `<context>{{#context.result#}}</context>`, concludes the reference knowledge is empty,
and refuses with the fixed message as the system prompt instructs. The result is
**"a bot that never looks at the knowledge base, but refuses so politely it looks normal"**.

On the Knowledge Retrieval side, the context is set via the `variable_selector` of `context`
(`kb_retrieval / result` in this demo).

#### ⑨ The HTTP Request node's `body` is a string, not an object

```python
# graphon/nodes/http_request/node.py
outputs={
    "status_code": response.status_code,
    "body": response.text if not files.value else "",   # ← str
    ...
}
```

So `{{#n8n_webhook.body.message#}}` does not resolve, and the Answer node
**outputs an empty string** (without an error).

**Fix:** put a Code node (python3) right after the HTTP Request, `json.loads` the body, and expand
the needed fields into separate output variables (code in §4-7 ⑤).
The Code node runs in Dify's `sandbox` container, so it adds no external traffic.

#### ⑩ Traffic from Dify to internal services goes through squid (ssrf_proxy)

**The hardest item in this section to diagnose.**

Dify does not let the HTTP Request node open sockets directly. As an SSRF countermeasure, all
outbound traffic goes through squid at `SSRF_PROXY_HTTP_URL=http://ssrf_proxy:3128`.
So the container that needs to resolve `n8n_local` is **squid**, not api / worker.

**Why it is easy to miss:** the connectivity check from the official instructions **succeeds**.

```bash
docker exec docker-api-1 curl -s http://n8n_local:5678/healthz
# → {"status":"ok"}   ← api can connect. But the Chatflow still doesn't work
```

The Chatflow error is `Reached maximum retries for URL http://n8n_local:5678/...`, which says
nothing about DNS or networking.

Joining the network is not enough either; it takes a two-stage fix:

| Stage | Symptom | Fix |
|---|---|---|
| 1 | `Reached maximum retries` | Add `ssrf_proxy` to `demo-rag-net` (so it can resolve the name) |
| 2 | `Access to '...' was blocked by SSRF protection` | Blocked by squid's ACL `http_access deny to_private_networks`. Allow it with `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=n8n_local` |

`SSRF_PROXY_ALLOW_PRIVATE_DOMAINS` is an official Dify extension point:
`ssrf_proxy/docker-entrypoint.sh` generates an `acl ... dstdomain` allow rule and `include`s it
before the deny rule. **Allowing a single host name rather than a subnet
(`SSRF_PROXY_ALLOW_PRIVATE_IPS`)** keeps SSRF protection in place for every other destination.

To check the generated configuration:
```bash
docker exec docker-ssrf_proxy-1 cat /etc/squid/dify_allow_private.conf
# acl dify_allowed_private_domains dstdomain n8n_local
# http_access allow client_localnet dify_allowed_private_domains
```

#### ⑪ Weaviate full-text search (BM25) does not tokenize Japanese

The keyword side of Hybrid Search is Weaviate's BM25, whose default tokenizer splits on
whitespace. Japanese has no spaces, so **Japanese keywords never match**.

Measured (Full-Text Search alone, Top K=5):

| Query | Hits |
|---|---|
| `F-021` | 3 |
| `DL-HR-RG-2024-007` | 5 |
| `タクシー` (taxi) | **0** |

This is not a defect; it matches the division of labor in §3-1. What BM25 is expected to do is
exact-match **form numbers, policy numbers and alphanumeric file names**, while absorbing colloquial
variation is the vector side's job. The keyword weight of `0.3` is set on that basis.

But if you design under the misconception that "it's hybrid, so Japanese keywords will match too",
you will be let down when you expect searches on Japanese article numbers like `第5条` to work.
For requirements that need Japanese morphological analysis, set `tokenization: kagome_ja` in
Weaviate, or choose Elasticsearch (kuromoji) as the vector store.

#### ⑫ Two Dify clones make compose projects collide

Docker Compose derives the project name from **the current directory name** by default.
Dify's compose files live under `docker/`, so wherever you clone it,
**the project name is always `docker`**.

So if you clone Dify in two places:

- Running commands from either `~/dify-local/docker` or `~/Desktop/dify-local/docker` **controls the same set of containers**
- But the compose files, `.env` and bind-mounted templates that get read are
  **the ones in the directory you ran the command from**

**Symptom:** you fix the override in one directory, run `docker compose up -d`, and the problem
seems solved; the moment someone runs `docker compose up -d` from the other directory, the setting
reverts. Container names and states do not change, so it is hard to tell what happened. If the two
clones are on different Dify versions, the image versions can swap too.

**To check where it is currently running from:**

```bash
docker inspect docker-api-1 \
  --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
# → /Users/xxx/Desktop/dify-local/docker
```

`volumes/db/data` (PostgreSQL) and `volumes/weaviate` are bind mounts, so
**the real data lives under that directory**. If you consolidate, keep that one.

**Fix:**
- Clone in one place only (recommended)
- If you really need several, set an explicit name such as `COMPOSE_PROJECT_NAME=dify-demo`
  in each `.env` to avoid collisions

---

## 5. Extension roadmap (proposal hooks for clients)

| Stage | Extension | Effort (technical view) |
|---|---|---|
| Phase 1 (this demo) | Policy Q&A + template distribution | 1 Dify app + n8n workflows |
| Phase 2 | OCR on receipt photos → automatic entry (Vision API + n8n) | Add a vision LLM + an Excel-write node |
| Phase 3 | Approval-flow integration (Slack approval button → automatic update of the workflow system) | n8n Slack interactive + Coconala-Flow API |
| Phase 4 | Automatic ingestion of revised policies (new PDF uploaded to Drive → re-embedding) | Drive Trigger + Dify Knowledge API |
| Phase 5 | Multilingual support (English, Vietnamese) for technical intern trainees | Automatic policy translation pipeline + per-language Chatflows |

---

## 6. Demo video scenario (shooting script v2, short version)

> **Approach for v2:** v1 was three minutes with narration, but on Coconala / Upwork listing pages
> viewers decide to leave within the first few seconds. v2 is **60 seconds, no narration, bilingual
> (Japanese/English) captions**, drops the problem statement and **opens with the screen already moving**.
> Bilingual captions mean there is no need to produce separate videos for domestic and overseas audiences.

### Basis for the timing (measured)

The timings in the script are not guesses; they match response times measured on the live system.

| Action | Total time | Time to first character | Output size |
|---|---|---|---|
| File request | **1.7 s** | 1.6 s | 237 characters |
| Guardrail (refusal) | 4.6 s | 3.9 s | 131 characters |
| Policy Q&A | 7.3 s | **4.5 s** | 322 characters, 10 lines |

Two decisions follow from this.

1. **Open with the file request.** It involves no LLM generation, so it is the fastest (1.7 s), and it
   gives the most surprising shot: "talk to the chat and an Excel file drops out".
   Opening with policy Q&A creates **4.5 seconds of silent waiting** and viewers leave.
2. **Cut the policy Q&A wait in editing.** The roughly 4.5 seconds from sending to text appearing is
   either jump-cut or fast-forwarded at 3–4× (if fast-forwarded, show a small `×4` in the top-right corner).

### Shot list (60 seconds total)

| # | Time | Screen | Action / direction |
|---|---|---|---|
| 1 | 0:00-0:08 | Dify chat screen (full screen) | **Cold open.** With no explanation, type "経費精算のフォーマットちょうだい" (send me the expense format) → send. The answer and URL appear in 1.7 s. Immediately click the URL → the Excel file downloads → open it (the five sheet tabs are visible) |
| 2 | 0:08-0:14 | Zoom on the download URL | Circle / highlight the **localhost** in `http://localhost:5678/...`. This is the video's main claim |
| 3 | 0:14-0:30 | Dify chat screen | "深夜帰りのタクシー代いくら？" (late-night taxi home, how much?) → **cut the wait** → the structured answer with Conclusion / Details / Source appears. Underline animation on `15,000円` and `第5条` (Art. 5) |
| 4 | 0:30-0:40 | Dify chat screen | "猫を飼ったら手当出る？" (allowance for adopting a cat?) → refusal. Emphasize "Sato in General Affairs (ext. 1234)" |
| 5 | 0:40-0:50 | Split screen (left: Dify / right: n8n Executions) | Replay shot 1 while n8n's execution log grows in real time on the right. Optionally a few seconds of the `docker ps` list |
| 6 | 0:50-1:00 | Architecture diagram (still) + CTA | The §4-7 architecture diagram. CTA (Coconala / Upwork) |

### Captions (Japanese and English)

- **Placement:** bottom center. Japanese on line 1, English on line 2.
- **Size ratio:** English at 75–80% of the Japanese size, in a slightly lighter color (e.g. Japanese `#FFFFFF` / English `#C8C8C8`).
  Making "Japanese primary, English secondary" obvious at a glance lets Japanese speakers skip the English.
- **Background:** semi-transparent black band (60–70% opacity). Place it so it does not overlap Dify's answer text.
- **Length:** no more than 20 Japanese characters / 40 English characters per line. Split longer lines.
- A ready-to-import caption file is provided at [`demo/demo_captions.srt`](./demo/demo_captions.srt).

| # | Time | Japanese | English |
|---|---|---|---|
| 1 | 0:01-0:05 | 社内チャットに話しかけるだけ | Just ask, in plain Japanese |
| 2 | 0:05-0:08 | 経費精算テンプレートが届く | The expense template arrives |
| 3 | 0:08-0:14 | このURL、`localhost` です<br>データは社外に出ていません | Note the URL: `localhost`<br>Nothing left the building |
| 4 | 0:14-0:20 | 30ページの規程から、根拠付きで即answer | Instant answers from a 30-page policy |
| 5 | 0:20-0:30 | 金額・条文番号は原文どおり引用 | Amounts and clause numbers quoted verbatim |
| 6 | 0:30-0:36 | 規程にない質問には答えません | It refuses questions the policy doesn't cover |
| 7 | 0:36-0:40 | 担当者に引き継ぐだけ。作り話はしない | It hands off to a human. No invented answers |
| 8 | 0:40-0:50 | Dify と n8n はすべて社内サーバー内 | Dify and n8n both run on your own server |
| 9 | 0:50-0:56 | 社内問い合わせを自動化。貴社サーバー内で完結 | Automate internal Q&A. Entirely on-premise |
| 10 | 0:56-1:00 | ご相談ください | Let's talk |

### Pre-recording checklist

```bash
python3 scripts/test_e2e.py     # confirm 3/3 PASS before recording
```

- [ ] `test_e2e.py` reports 3/3 PASS
- [ ] Open the browser with a **fresh profile** (no bookmarks bar, other tabs or extensions on screen)
- [ ] Empty the Downloads folder (so old files do not show up)
- [ ] Turn off macOS desktop notifications (Focus mode)
- [ ] Hide menu-bar icons other than the clock and Wi-Fi
- [ ] Record the screen at 1920×1080 / 60 fps
- [ ] Set browser zoom to 125–150% (large enough to read the text even with captions)
- [ ] Open the n8n Executions screen in advance and clear old execution history

### Editing notes

- **Leave no silence.** Always cut "seconds where nothing happens", like the wait in shot 3.
- **Keep background music subtle, or use none.** This is a business proposal video; flashy music undermines trust.
- **One message per cut.** It is tempting to pack in captions, but do not add more than the table above.
- **Shot 2 is the main claim.** Hold it about 0.5 seconds longer, almost as a still.
  What owners react to is not accuracy but one thing: "the data doesn't leave".

---

## 7. Deliverables checklist (at client handover)

### Common (all setups)
- [x] Dify Chatflow DSL (YAML export) → `dify/chatflow_dsl.yaml` (secrets excluded)
- [x] Source policy for the knowledge base → `01_dummy_manual_demo_logistics.md` (converted to `.txt` at upload, §4-8 ⑥)
- [x] n8n workflows (JSON export) → `docker/n8n/workflows/` (both Workflow 1 and 2, PII removed)
- [x] Environment variable list → `scripts/.dify_admin.env.example`
- [x] Operations manual → `03_operations_manual.md` (re-embedding / xlsx update / backup / first-line triage)
- [x] Test queries and Recall@4 results → `scripts/measure_recall.py` (measured values in §3-4)
- [x] Postman / curl sample collection → `04_api_examples.md` (every command verified on the live system)

### Build automation scripts (added in v1.5)

The environment can be rebuilt through the API without touching the admin GUI. Reproducing it in a
client environment, and rebuilding when the policy is revised, each take a single command.

| File | Role |
|---|---|
| `scripts/dify_console.py` | Dify Console API client (Python standard library only, no pip install) |
| `scripts/provision_knowledge.py` | Builds the §3-3 knowledge base. `--recreate` rebuilds it |
| `scripts/provision_chatflow.py` | Builds the §2 Chatflow. DSL generation → import → publish → export |
| `scripts/measure_recall.py` | Measures the §3-4 Recall@4 |
| `scripts/test_e2e.py` | End-to-end tests (policy Q&A / guardrail / file request) |
| `scripts/export_n8n_workflows.py` | Exports n8n workflows (strips the owner's e-mail address from `shared`) |

```bash
cp scripts/.dify_admin.env.example scripts/.dify_admin.env   # fill in DIFY_PASSWORD
python3 scripts/provision_knowledge.py
python3 scripts/provision_chatflow.py
python3 scripts/measure_recall.py --threshold 0.3
python3 scripts/test_e2e.py
```

### §4-7 fully local setup (the primary SME pattern)
- [x] `docker/n8n/docker-compose.yml` (templates volume + allowlisted path + joins the shared network)
- [x] `docker/dify/docker-compose.override.yaml` (overlay on the official Dify compose)
- [x] `docker/n8n/templates/expense_template_v3.xlsx` (extended attributes removed; placed at setup)
- [x] `docker/test/test_webhook.sh` (curl connectivity tests)
- [x] `docker/README.md` (instructions that work with `git clone` → `docker compose up -d`)
- [x] **§4-8 operational lessons** (n8n allowlist / Webhook Respond mode / macOS xattr / RFC 5987)

### Additional deliverables when adopting §4-1 / §4-6 (cloud-API variants)
- [ ] Slack App manifest (YAML)
- [ ] Google Drive service account JSON (obtained by the client)
- [ ] ngrok / Cloudflare Tunnel setup instructions (for Dify Cloud + local n8n)

---

(End of document)
