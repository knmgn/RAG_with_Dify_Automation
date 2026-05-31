# Dify × n8n ポートフォリオデモ素材

ココナラ／Upwork向けポートフォリオ（見本）として、「Dify（高精度RAG）×n8n（実務自動化）」のデモ動画を撮影するための素材一式。

---

## Targeted Use Case for Japanese SMEs (English Summary for Global Clients)

> The portfolio below is intentionally localized to **Japanese small and medium-sized enterprises (SMEs)** and their back-office (HR / expense / labor compliance) operations. This English section exists so international buyers (Upwork) can evaluate the portfolio without reading Japanese.

**Problem domain — why Japanese SMEs?**
Japanese SMEs (especially in logistics, manufacturing, construction, and professional services) operate under an unusually heavy back-office burden:

- **Hyper-detailed internal rules** that no employee can memorize — e.g. taxi reimbursement only after 23:00, JPY 15,000 caps with a dedicated "excess justification form (F-021)" requiring two-manager approval, distinct lodging caps for the 23 wards of Tokyo vs. other cities, last-train screenshots as evidence.
- **Hard deadlines enforced by social cost** — late expense submissions trigger formal incident reports (始末書 / *shimatsu-sho*) and HR performance deductions, which discourages employees from asking clarifying questions and increases compliance errors.
- **Single-point-of-failure ownership** — one named individual in the General Affairs department (*Soumu-bu*) typically owns dozens of unrelated workflows (insurance card reissuance, shift filings, template distribution).
- **Severe orthographic variation** — employees ask in colloquial Japanese ("深夜帰りのタクシー代いくら？") while policies are written in formal legal-style Japanese ("業務終了時刻が23:00を超え"), making naïve keyword search useless.
- **Tool fragmentation** — files on Google Drive / shared drives, conversations on Slack / Teams / Chatwork, approvals in yet another workflow system.

**What this portfolio demonstrates**
A reusable architecture (**Dify high-precision RAG + n8n executable automation**) that:

1. Deflects 60–80% of repetitive HR / expense questions away from the General Affairs bottleneck, *while preserving citation trails required for Japanese audit and labor-compliance culture*.
2. Enforces a **zero-hallucination boundary** — when the policy is silent, the bot refuses to improvise and instead names the responsible owner (in this demo: "Mr. Sato, ext. 1234"), matching the Japanese cultural expectation of clear accountability (責任の所在 / *sekinin no shozai*).
3. Goes beyond Q&A — the "send me the expense template" intent triggers n8n to fetch the file from a local share, log the request, and respond to the user with a download URL. **Chatbot → automation system.**
4. **Ships an all-local, closed-network deployment option** (`docker/`) where every byte stays inside the customer's server. For Japanese SMEs paranoid about data leaving the building, this is decisive — see deliverable #4 below.

**Reusability beyond Japan**
The same Chatflow topology (Classifier → Hybrid Retrieval → Score Gate → Guardrailed LLM → Webhook) ports to US/EU SMEs, multilingual manufacturing in Southeast Asia, and healthcare/legal firms. Only three layers need localization: the knowledge corpus, the system-prompt language and deflection contact, and the rerank model (e.g. `cohere/rerank-multilingual-v3.0` → `cohere/rerank-english-v3.0`). The graph topology, intent classifier, n8n integration pattern, and Slack Block Kit payload remain unchanged — and this portability is the core value proposition.

---

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
pandoc 01_dummy_manual_demo_logistics.md \
  -o 01_dummy_manual_demo_logistics.pdf \
  --pdf-engine=wkhtmltopdf \
  -V CJKmainfont="Noto Sans CJK JP"
```
または、VSCode / Typora / Obsidian で開いて「PDFエクスポート」でも可。

### 2. Dify Chatflow 設計書
[`02_dify_chatflow_design.md`](./02_dify_chatflow_design.md)

上記マニュアルをナレッジに食わせる Dify Bot の設計書。
- **Targeted Use Case for Japanese SMEs**（冒頭の英文セクション — 海外クライアント向け）
- システムプロンプト（ハルシネーション抑制ガードレール、Citation強制）
- ハイブリッド検索（Vector + Keyword）× Rerank の設定
- Question Classifier による Intent 検出
- **3つのn8n連携パターン**：
  - §4-1 フル版（Drive + Slack API連携、50名以上の組織向け）
  - §4-6 シンプル版（Google Drive リンク共有のみ、PoC向け）
  - **§4-7 完全ローカルDocker版（中小企業向け本命、データ外部流出ゼロ）** ← 推奨
- §4-8 実装中に発見した運用ノウハウ4件（n8n allowlist / Webhook Respond モード / macOS xattr / RFC 5987）
- テストクエリ集、デモ動画台本、納品チェックリスト

### 3. ダミー経費精算テンプレート（Excel）
[`経費精算テンプレート_v3.xlsx`](./経費精算テンプレート_v3.xlsx) ／ [`scripts/build_expense_template.py`](./scripts/build_expense_template.py)

規程 DL-HR-RG-2024-007 に準拠したダミーの Excel テンプレート。Question Classifier が「ファイル要求」を検出した際に Dify が返す、Google Drive 上の配布対象ファイル。

含まれるシート：
- **経費精算書**：申請者情報、9件のサンプル明細、SUM 数式での自動集計、仮払金控除、5者承認欄
- **タクシー利用明細**：規程第5条準拠の乗車時刻・降車時刻・F-021 ステータス記録欄
- **仮払い精算**：仮払金と実費の差額自動計算
- **区分マスタ**：ドロップダウン用の13区分と勘定科目・規程参照
- **記入要領**：提出期限・タクシー上限・領収書ルール・問い合わせ窓口

#### 再生成手順
```bash
pip install openpyxl
python3 scripts/build_expense_template.py
```

#### Google Drive へのアップロード手順（シンプル運用版）
1. `経費精算テンプレート_v3.xlsx` を社内共有ドライブにアップロード
2. 「共有」→「リンクを知っている全員」→ 権限「閲覧者」に設定
3. コピーした URL を Dify の環境変数 `EXPENSE_TEMPLATE_URL` に登録
4. 設計書 §4-6 の Answer ノード文言をコピペで投入

### 4. ローカルDocker環境一式（完全社内完結 PoC スタック）
[`docker/`](./docker/) ディレクトリ

**中小企業案件の本命**：Dify Self-Hosted + n8n + 共有Dockerネットワークで、データを一切外部に出さずに動作する完全ローカル構成のPoC環境。設計書 §4-7 / §4-8 の参照実装。

含まれるファイル：
- `docker/README.md` ─ `git clone` → `docker compose up -d` 一発で動く手順書
- `docker/n8n/docker-compose.yml` ─ n8n 本体 + xlsx volume + 共有network参加済み
- `docker/n8n/templates/.gitkeep` ─ xlsx 配置先（設計書 §4-8 ① の allowlist 制約に準拠）
- `docker/dify/docker-compose.override.yaml` ─ Dify公式に重ねるネットワーク追加だけの差分（Dify本体は触らない）
- `docker/test/test_webhook.sh` ─ 4段階の疎通テストスクリプト（host→n8n / Dify→n8n / Workflow1全体 / Workflow2バイナリ応答）

#### クイックスタート（要約）
```bash
docker network create demo-rag-net

# Dify Self-Hosted 起動
git clone https://github.com/langgenius/dify.git ~/dify-local
cp docker/dify/docker-compose.override.yaml ~/dify-local/docker/
cd ~/dify-local/docker && cp .env.example .env && docker compose up -d

# n8n 起動
cd <この repo>/docker/n8n
cp ../../経費精算テンプレート_v3.xlsx ./templates/expense_template_v3.xlsx
xattr -c ./templates/expense_template_v3.xlsx   # macOS のみ
docker compose up -d

# 疎通テスト
export N8N_WEBHOOK_TOKEN="<your token>"
./docker/test/test_webhook.sh
```

詳細は [`docker/README.md`](./docker/README.md) を参照。

## 使い方

1. `01_dummy_manual_demo_logistics.md` を PDF化してDifyのナレッジにアップロード
2. `経費精算テンプレート_v3.xlsx` を配布手段に応じて配置
   - 完全ローカル（推奨）：`docker/n8n/templates/expense_template_v3.xlsx` に配置
   - シンプル版：Google Drive にアップロード（リンク共有設定）
   - フル版：Google Drive + Slack 連携の API 設定
3. `02_dify_chatflow_design.md` の設定値をもとに Dify Chatflow を組み立て
4. n8n のワークフローを設計書 §4-7 ②（完全ローカル）or §4-2（フル版）の通り構築
5. `docker/test/test_webhook.sh` で4段階の疎通テスト
6. デモ動画台本（設計書の第6章）に沿って撮影

## ライセンス

このダミー素材は架空のものです。実在の企業・人物・住所・電話番号とは一切関係ありません。
