# API サンプル集（curl / Postman）

> 対象：この Bot を既存の社内システム（ポータル、Slack、業務アプリ）に組み込む開発者
> 前提：`docker/README.md` の手順で環境が起動済みであること
> 関連：[`02_dify_chatflow_design.md`](./02_dify_chatflow_design.md) ／ [`03_operations_manual.md`](./03_operations_manual.md)

このドキュメントのコマンドは**すべて実機で実行して応答を確認したもの**です。
社内ポータルへの iframe 埋め込みではなく、**自前のUIから API で叩きたい**場合の参照実装として使ってください。

---

## 0. 準備：APIキーの発行

Dify の Service API を叩くにはアプリごとの API キーが必要です。

**画面から**：アプリを開く → 左メニュー「APIアクセス」 → 右上「APIキー」 → 「新しいシークレットキーを作成」

**スクリプトから**：

```bash
python3 -c "
import json
from dify_console import connect, load_env
from test_e2e import get_api_key
c = connect(load_env())
app_id = json.load(open('scripts/.provision_state.json'))['app_id']
print(get_api_key(c, app_id))
"
```

以降の例では環境変数に入れて使います。キーは `app-` で始まる28文字です。

```bash
export DIFY_API_KEY="app-xxxxxxxxxxxxxxxxxxxxxxxx"
export DIFY_BASE="http://localhost"
```

> ⚠️ このキーは**アプリへのフルアクセス権**を持ちます。フロントエンドの JavaScript に
> 埋め込まないでください。必ずサーバーサイドから呼び出します。

---

## 1. 規程Q&A（同期・blocking）

最も基本的な呼び出し。回答が完成してから一括で返ります。

```bash
curl -s -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "深夜帰りのタクシー代いくら？",
    "response_mode": "blocking",
    "user": "employee-0042"
  }'
```

**レスポンス（抜粋）**

```json
{
  "event": "message",
  "message_id": "…",
  "conversation_id": "…",
  "mode": "advanced-chat",
  "answer": "【結論】\n深夜帰宅時のタクシー代は、1回あたり15,000円（消費税込）が上限です。\n…",
  "metadata": {
    "usage": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_price": "…",
      "currency": "USD",
      "latency": 0.0
    },
    "retriever_resources": [
      {
        "position": 1,
        "dataset_name": "社内規程ナレッジ",
        "document_name": "DL-HR-RG-2024-007_旅費交通費・経費精算および労務手続き規定.txt",
        "score": 0.6438,
        "content": "第5条（タクシー代の支給要件）…",
        "doc_metadata": { "doc_id": "DL-HR-RG-2024-007", "doc_version": "v3", "…": "…" }
      }
    ]
  },
  "created_at": 1785965600
}
```

| フィールド | 用途 |
|---|---|
| `answer` | ユーザーに表示する回答本文 |
| `conversation_id` | 会話の継続に使う（§3） |
| `metadata.retriever_resources` | **引用元の表示・監査ログに使う。** `score` と `doc_metadata` が入っているので「どの規程の何版を根拠に答えたか」を記録できる |
| `metadata.usage` | トークン数と課金額。コスト按分に使える |

`user` は自社の社員IDを入れてください。Dify 側の会話ログがこの単位で分かれます。

---

## 2. 規程Q&A（ストリーミング）

チャットUIを作る場合はこちら。SSE（Server-Sent Events）で届きます。

```bash
curl -s -N -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "夜勤手当いくら？",
    "response_mode": "streaming",
    "user": "employee-0042"
  }'
```

**イベントの流れ**

```
event: ping

data: {"event":"workflow_started","conversation_id":"…","message_id":"…"}

data: {"event":"node_started","data":{"title":"インテント分類",…}}

data: {"event":"node_finished","data":{"title":"ナレッジ検索",…}}

data: {"event":"message","answer":"【結","…"}
data: {"event":"message","answer":"論】","…"}
      …

data: {"event":"message_end","metadata":{"usage":{…},"retriever_resources":[…]}}
```

| イベント | 扱い |
|---|---|
| `message` | `answer` を連結して画面に流す |
| `node_started` / `node_finished` | 進捗表示に使える（「規程を検索中…」など）。無視してもよい |
| `message_end` | ここで `retriever_resources` が届く。引用元の表示はこのタイミング |
| `error` | エラー内容が入る |

> 💡 デモ動画で「n8n の Executions がリアルタイムに流れる」画を撮る場合、
> Dify 側もストリーミングにしておくと処理の進行が視覚的に伝わります。

---

## 3. 会話を継続する

前回の応答に含まれる `conversation_id` を渡すと、文脈が引き継がれます。

```bash
curl -s -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "それって領収書いる？",
    "conversation_id": "前回のレスポンスの conversation_id",
    "response_mode": "blocking",
    "user": "employee-0042"
  }'
```

> ⚠️ `conversation_id` は `user` とセットで管理してください。別の `user` の
> `conversation_id` を渡すと 404 になります。

### 会話履歴を取得する

```bash
# 会話一覧
curl -s -G "$DIFY_BASE/v1/conversations" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  --data-urlencode "user=employee-0042" \
  --data-urlencode "limit=20"

# 特定会話のメッセージ
curl -s -G "$DIFY_BASE/v1/messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  --data-urlencode "user=employee-0042" \
  --data-urlencode "conversation_id=<conversation_id>"
```

---

## 4. ファイル要求（Dify → n8n → ダウンロード）

Bot に「フォーマットちょうだい」と言うと、n8n 経由でダウンロードURLが返ります。
**呼び出し方は §1 とまったく同じ**です。Chatflow が内部で振り分けます。

```bash
curl -s -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "経費精算のフォーマットちょうだい",
    "response_mode": "blocking",
    "user": "employee-0042"
  }' | python3 -c "import json,sys; print(json.load(sys.stdin)['answer'])"
```

**出力**

```
経費精算テンプレートをご用意しました。下記URLからダウンロードしてください。

📎 **経費精算テンプレート_v3.xlsx**
http://localhost:5678/webhook/files/expense-v3

【ご注意】
- 提出期限：毎月25日17:00必着
- マクロを必ず有効化してください（規程第9条第4項）

【引用元】
規程：DL-HR-RG-2024-007 第8条・第9条
窓口：総務部 佐藤（内線1234）／ 経理部 鈴木（内線1456）
```

---

## 5. n8n を直接叩く

Dify を介さず n8n だけをテストしたい場合。障害の切り分けに使います。

### Workflow 1：Intent Dispatcher（要認証）

```bash
export N8N_WEBHOOK_TOKEN="<Header Auth Credential に設定した値>"
export DISPATCHER_PATH="8ee2e0e7-1aa3-4c37-9444-47c34dd9d509"

curl -s -X POST "http://localhost:5678/webhook/$DISPATCHER_PATH" \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: $N8N_WEBHOOK_TOKEN" \
  -d '{
    "intent": "request_expense_template",
    "user_id": "employee-0042",
    "user_query": "経費精算のフォーマットちょうだい",
    "metadata": { "template_key": "expense_template_v3" }
  }'
```

**レスポンス**

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

| 応答 | 意味 |
|---|---|
| 200 + `"status":"success"` | 正常 |
| 401 / `Authorization data is wrong!` | `X-Auth-Token` が不一致。Credential の `Name` 欄にヘッダー名が入っているか確認（§4-8 ①） |
| 400 + `Unknown intent` | `intent` が未対応の値。Fallback 出力に落ちている |
| 404 | ワークフローが Active になっていない |

未対応 intent の確認：

```bash
curl -s -X POST "http://localhost:5678/webhook/$DISPATCHER_PATH" \
  -H "Content-Type: application/json" -H "X-Auth-Token: $N8N_WEBHOOK_TOKEN" \
  -d '{"intent":"request_unknown_thing","user_id":"t"}'
```

### Workflow 2：File Server（認証なし）

パス自体が推測困難な文字列としてトークン代わりになっています。

```bash
curl -s -o /tmp/template.xlsx -w "HTTP %{http_code} / %{size_download} bytes / %{content_type}\n" \
  http://localhost:5678/webhook/files/expense-v3

file /tmp/template.xlsx    # → Microsoft Excel 2007+
```

日本語ファイル名で保存する場合（ブラウザは自動で日本語名になります）：

```bash
curl -OJ http://localhost:5678/webhook/files/expense-v3
# curl は ASCII フォールバック名 expense_template_v3.xlsx で保存されます（§4-8 ④）
```

---

## 6. ヘルスチェック

監視ツール（Uptime Kuma 等）に登録する用。

```bash
# n8n
curl -s -o /dev/null -w "n8n: %{http_code}\n" http://localhost:5678/healthz

# Dify（Webアプリの入口）
curl -s -o /dev/null -w "dify: %{http_code}\n" http://localhost/

# Dify → n8n の内部疎通（Docker ネットワーク越し）
docker exec docker-api-1 curl -s -o /dev/null -w "internal: %{http_code}\n" \
  http://n8n_local:5678/healthz
```

> ⚠️ 3つ目が 200 でも Chatflow が n8n に到達できるとは限りません。
> 実際の送信は squid（ssrf_proxy）経由のためです。**本当の疎通確認は
> `python3 scripts/test_e2e.py`** です（§4-8 ⑩）。

---

## 7. ナレッジの検索だけを試す（チューニング用）

回答生成をせず、検索結果とスコアだけを見ます。閾値やチャンク設定の調整に使います。

```bash
python3 -c "
import json
from dify_console import connect, load_env
c = connect(load_env())
ds = json.load(open('scripts/.provision_state.json'))['dataset_id']
r = c.post(f'/datasets/{ds}/hit-testing', {'query': 'タクシー上限超えた'})
for rec in r.get('records', []):
    print(round(rec['score'], 4), '|', rec['segment']['content'][:60].replace(chr(10), ' '))
"
```

10問まとめて評価する場合は `python3 scripts/measure_recall.py --threshold 0.3` を使ってください。

---

## 8. Postman へ取り込む

上記の curl はそのまま Postman にインポートできます。

1. Postman → 左上「Import」→ 「Raw text」
2. curl コマンドを貼り付け → 「Continue」→「Import」

コレクション変数として `DIFY_BASE` / `DIFY_API_KEY` / `N8N_WEBHOOK_TOKEN` を定義しておくと、
環境（開発／本番）の切り替えが楽になります。

> ⚠️ **APIキーとトークンを含んだコレクションを共有・エクスポートしないでください。**
> Postman の「Environment」側に置き、コレクション本体には変数参照だけを残します。

---

## 9. 本番組み込み時の注意

| 項目 | PoC（この構成） | 本番 |
|---|---|---|
| プロトコル | HTTP | HTTPS 必須（APIキーが平文で流れるため） |
| APIキーの保管 | 環境変数 | シークレットマネージャ |
| 呼び出し元 | ローカル | サーバーサイドのみ。ブラウザから直接叩かない |
| `user` フィールド | 任意の文字列 | 社員IDに固定し、会話ログの単位を揃える |
| ダウンロードURL | `localhost:5678` | 社内DNS名（`n8n.example.co.jp` 等）。`WEBHOOK_URL` 環境変数で変更 |
| レート制限 | なし | 逆プロキシ側で実装 |
| 監査ログ | Dify の会話ログ | `retriever_resources` の `doc_id` / `doc_version` を自社ログに記録（§3-3 ⑥） |
