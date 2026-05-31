# Local Docker Stack — Dify Self-Hosted × n8n × ローカルファイル配信

> **完全社内完結構成**：データを一切外部クラウドに出さずに、Dify高精度RAGとn8n業務自動化を組み合わせた中小企業向けPoC環境一式。設計書 `02_dify_chatflow_design.md` §4-7 / §4-8 の参照実装。

## なぜこの構成？

中小企業の経営者が一番気にするのは **「自社のデータがクラウドに吸い取られないか」** という不安です。本構成では：

- **規程PDF・経費テンプレート・会話ログ**：すべて社内サーバー内のDocker volumeに格納
- **DifyからNを叩く通信**：Docker内部ネットワーク（`demo-rag-net`）経由、外に出ない
- **ファイルダウンロードURL**：`http://localhost:5678/...`（社内）
- **唯一の外部通信**：LLM API呼び出し（OpenAI / Anthropic）。これすら Ollama 等のローカルLLMに置換可能（拡張ロードマップ Phase 5）

→ 「データは外に出ません」と言い切れる。これが受注確度を分けます。

## アーキテクチャ

```
┌────────────────────────────────────────────────────────────────┐
│  Docker Host（社内サーバー or 開発Mac）                          │
│                                                                  │
│  ┌─────────── demo-rag-net (external bridge) ──────────────┐    │
│  │                                                           │    │
│  │  [Dify Self-Hosted]            [n8n Self-Hosted]          │    │
│  │  - api / worker / web          - Workflow 1: Dispatcher   │    │
│  │  - postgres / redis            - Workflow 2: File Server  │    │
│  │  - weaviate / sandbox          - port 5678                │    │
│  │  - nginx (port 80)             - templates/ (bind mount)  │    │
│  │                                                           │    │
│  └───────────────────────────────────────────────────────────┘    │
│        ↑ Browser:80                  ↑ Browser:5678              │
└────────┼──────────────────────────────┼──────────────────────────┘
         │                              │
    [社員のブラウザ]                  [社員のブラウザ]
                                      （ファイルクリックでDL）
```

## ディレクトリ構成

```
docker/
├── README.md                       ← このファイル
├── n8n/
│   ├── docker-compose.yml          ← n8n本体 + templates volume + 共有network参加
│   └── templates/
│       └── (expense_template_v3.xlsx をここに置く)
├── dify/
│   └── docker-compose.override.yaml ← Dify公式に重ねるネットワーク追加だけの差分
└── test/
    └── test_webhook.sh             ← 4段階の疎通テストスクリプト
```

## クイックスタート（一括セットアップ）

### 前提
- Docker Desktop がインストール済み（メモリ最低4GB、推奨8GB）
- Mac / Linux いずれも動作確認済み（Windows未検証）
- ポート `80` と `5678` がホスト側で空いていること

### Step 1：共有ネットワークを作成（一度だけ）

```bash
docker network create demo-rag-net
```

### Step 2：Dify Self-Hosted を準備

```bash
# Dify公式リポジトリをホームディレクトリにクローン
git clone https://github.com/langgenius/dify.git ~/dify-local

# このリポジトリの override ファイルを Dify の docker/ ディレクトリへコピー
cp docker/dify/docker-compose.override.yaml ~/dify-local/docker/

# Dify の環境設定ファイルを準備
cd ~/dify-local/docker
cp .env.example .env
```

> ⚠️ `docker-compose.override.yaml` は Docker Compose が自動で本体の YAML に重ねて読み込みます（手動マージ不要）。

### Step 3：xlsx テンプレートを配置

このリポジトリのルートにある `経費精算テンプレート_v3.xlsx` を、英語ファイル名で `docker/n8n/templates/` にコピーします：

```bash
# このリポジトリのルートに戻って
cp 経費精算テンプレート_v3.xlsx docker/n8n/templates/expense_template_v3.xlsx

# macOS で Google Drive 同期フォルダ経由のファイルだった場合は拡張属性を除去（重要）
xattr -c docker/n8n/templates/expense_template_v3.xlsx
```

> 💡 `xattr -c` をスキップすると、Mac上のn8nが「Operation not permitted」(EPERM)で読めません。詳細は設計書 §4-8 ③ を参照。Linux環境ではこの問題は発生しません。

### Step 4：両stackを起動

```bash
# n8n を起動
cd docker/n8n
docker compose up -d

# Dify を起動（5〜10分かかります、初回はイメージ pull のため）
cd ~/dify-local/docker
docker compose up -d
```

### Step 5：動作確認

```bash
# 全コンテナが healthy か確認
cd ~/dify-local/docker && docker compose ps
cd <この repo>/docker/n8n && docker compose ps
```

各コンテナが `running` または `(healthy)` になっていればOK。

### Step 6：UIアクセス

| サービス | URL | 用途 |
|---|---|---|
| Dify | <http://localhost/install> | 初回はadminアカウント作成 |
| n8n | <http://localhost:5678> | ワークフロー編集・モニタリング |

### Step 7：n8n ワークフローのインポート（後日）

n8n UIで以下の2ワークフローを設計書 §4-7 ② の構成に沿って作成します。設計書に沿って手で組むか、n8nエクスポートJSONがある場合はインポートします（本リポジトリでは手順を文書化、JSONエクスポートは§7チェックリストの納品物として用意する想定）。

### Step 8：疎通テスト

n8nワークフローが Active になったら、本リポジトリ提供のスクリプトで4段階の疎通確認：

```bash
# 環境変数を設定（n8nのHeader Auth Credentialに登録した値）
export N8N_WEBHOOK_TOKEN="<your token>"
export INTENT_DISPATCHER_PATH="<workflow1 webhook UUID>"

# 実行
./docker/test/test_webhook.sh
```

期待される出力：

```
[INFO] Test 1/4: n8n /healthz from host
[PASS] n8n is reachable on host port 5678

[INFO] Test 2/4: n8n /healthz from inside Dify api container
[PASS] Dify api can reach n8n via internal Docker DNS (n8n_local)

[INFO] Test 3/4: Workflow 1 (Intent Dispatcher) returns success JSON
[PASS] Workflow 1 returned success JSON

[INFO] Test 4/4: Workflow 2 (File Server) returns xlsx binary
[PASS] Workflow 2 returned 16464 bytes (HTTP 200)
```

4つすべてPASSなら、Dify→n8nのフルチェーンが完全動作している状態です。

## 「URLの二刀流」設計（重要な設計判断）

| 通信パス | 使うURL | 理由 |
|---|---|---|
| Dify → n8n（内部呼び出し） | `http://n8n_local:5678/webhook/<UUID>` | Dockerネットワーク内のサービス名解決 |
| ブラウザ → ファイルダウンロード | `http://localhost:5678/webhook/files/expense-v3` | ブラウザはDockerネットワークを認識しないので、ホストにpublishされたport経由 |

n8nがDifyに返す `download_url` フィールドには **必ず `localhost:5678` のURL** を入れること。`n8n_local:5678` を入れるとブラウザで `ERR_NAME_NOT_RESOLVED` になります。

## トラブルシュート

| 症状 | 対処 |
|---|---|
| `docker compose up` でメモリエラー | Docker Desktop → Settings → Resources → Memory を 8GB 以上に |
| Difyの `/install` が表示されない | `docker compose ps` で nginx と api が healthy か確認 |
| 疎通テスト Test 2 で connection refused | `docker network inspect demo-rag-net` で両コンテナが参加しているか確認 |
| n8n Read/Write Files で EPERM | xlsxの拡張属性を `xattr -c` で除去（macOSのみ） |
| n8n Read/Write Files で Allowed paths エラー | ファイル配置先が `/home/node/.n8n-files` 配下か確認 |
| Webhook で `Unused Respond to Webhook node found` | Webhookノードの Respond を `Using 'Respond to Webhook' Node` に変更、かつ全Switch分岐に Respond ノードを配置 |

## 本番デプロイ時の追加考慮事項

このPoC構成は**開発・社内デモ前提**です。本番納品時は以下の差分を加える必要があります：

| 項目 | PoC | 本番 |
|---|---|---|
| ホスト | Mac / 開発機 | 社内オンプレサーバー or プライベートVPS |
| ポート公開 | `localhost:80` `localhost:5678` | リバースプロキシ + 社内DNS（`https://dify.example.co.jp/` 等） |
| TLS | なし（HTTP） | Let's Encrypt 等で必須 |
| n8n認証 | Header Auth + 推測困難パス | + IP Allowlist（社内NW限定） |
| バックアップ | 任意 | postgres + n8n_data + Weaviate vector storeの定期スナップショット |
| 監視 | docker compose ps | Prometheus + Grafana / Uptime Kuma |
| ログ集約 | docker compose logs | Loki / Datadog 等 |

これらは設計書 §7 納品物チェックリストに含まれます。

## 関連ドキュメント

- [`../02_dify_chatflow_design.md`](../02_dify_chatflow_design.md) — 設計書（§4-7 §4-8 が本構成のソース）
- [`../01_dummy_manual_demo_logistics.md`](../01_dummy_manual_demo_logistics.md) — Bot に食わせるダミー規程PDF用テキスト
- [`../scripts/build_expense_template.py`](../scripts/build_expense_template.py) — xlsx 再生成スクリプト

## ライセンス

ダミー素材としての提供です。実在の企業・人物・住所・電話番号とは無関係です。
