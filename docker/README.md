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

> ⚠️ **Dify のクローンは1箇所だけにすること。** compose のプロジェクト名は
> カレントディレクトリ名から決まり、Dify は必ず `docker/` 配下で操作するため、
> **どこにクローンしてもプロジェクト名は `docker`** になります。
> 2箇所にクローンすると、どちらから `docker compose up -d` しても同じコンテナ群を
> 操作する一方で、読み込まれる compose ファイル・`.env`・テンプレートは
> 叩いたディレクトリ側のものになります。片方で直した設定が、もう片方から
> `up -d` した瞬間に元に戻ります（設計書 §4-8 ⑫）。
>
> 現在どこから起動されているかの確認：
> ```bash
> docker inspect docker-api-1 \
>   --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
> ```
> PostgreSQL と Weaviate のデータは bind mount でこのディレクトリ配下に置かれます。

> ⚠️ `docker-compose.override.yaml` は Docker Compose が自動で本体の YAML に重ねて読み込みます（手動マージ不要）。
>
> このoverrideは `api` / `worker` に加えて **`ssrf_proxy` にも** `demo-rag-net` を追加し、
> さらに `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS: n8n_local` を設定します。
> Dify は HTTP Request ノードの通信を squid（ssrf_proxy）経由で送出するため、
> この2つが揃っていないと Chatflow から n8n に到達できません。
> 見落とすと「疎通テストは通るのに Chatflow だけ動かない」という状態になります（設計書 §4-8 ⑩）。

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

### Step 7：n8n ワークフローのインポート

エクスポート済みの JSON を `docker/n8n/workflows/` に同梱しています。

| ファイル | 内容 |
|---|---|
| `workflow_1_intent_dispatcher.json` | POST受け → Switch → JSON応答（`download_url` を返す） |
| `workflow_2_file_server.json` | GET受け → ファイル読込 → バイナリ応答（xlsx） |

n8n UI（<http://localhost:5678>）の右上メニュー → **Import from File** で読み込みます。
CLI からでも可能です：

```bash
docker cp docker/n8n/workflows/workflow_1_intent_dispatcher.json n8n_local:/tmp/
docker exec n8n_local n8n import:workflow --input=/tmp/workflow_1_intent_dispatcher.json
```

インポート後に必要な作業は2つです。

1. **Header Auth Credential の作成と再リンク**
   JSON には認証情報の**参照のみ**が含まれ、トークン本体は含まれません（当然です）。
   Workflow 1 の Webhook ノードを開き、Credential を作り直してください。
   - Credential 種別：`Header Auth`
   - **`Name` 欄にはヘッダー名 `X-Auth-Token` を入れます**（Credential の管理名ではありません。
     ここを間違えると `Authorization data is wrong!` になります。§4-8 ①の隣の罠）
   - `Value` 欄に共有シークレット（任意のランダム文字列）
   - 同じ値を Dify 側の環境変数 `N8N_WEBHOOK_TOKEN` にも設定します
     （`scripts/.dify_admin.env` に書いて `provision_chatflow.py` を流すのが確実）

2. **両ワークフローを Active にする**

> 💡 自分の環境から書き出し直す場合は `python3 scripts/export_n8n_workflows.py` を使ってください。
> `n8n export:workflow` の生出力には `shared` ブロックに**所有者のメールアドレス**が
> 含まれるため、そのままコミットできません。このスクリプトが除去します。

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
| **疎通テストは全部PASSするのに Chatflow だけ `Reached maximum retries for URL http://n8n_local:5678/...`** | **`ssrf_proxy` が `demo-rag-net` に参加していない。** Dify の HTTP Request は squid 経由で送出されるため、名前解決するのは api ではなく squid。override 適用後 `docker compose up -d ssrf_proxy` |
| **`Access to '...' was blocked by SSRF protection`** | squid の ACL が private 宛先を拒否している。override の `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS: n8n_local` が効いているか確認：`docker exec docker-ssrf_proxy-1 cat /etc/squid/dify_allow_private.conf` |
| **Bot が毎回「規程に記載が見当たりません」と返す** | ①ナレッジ検索が0件（Rerank APIのレート超過など）②LLMノードのコンテキスト変数が `{{#context#}}` でない。設計書 §4-8 ⑦ ⑧ |
| **ファイル要求の回答が空文字で返る** | HTTP Request の `body` は文字列なので `body.message` では参照不可。JSONパース用の Code ノードが必要。設計書 §4-8 ⑨ |
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
