# 運用マニュアル — Demo-Logi-Bot（§4-7 完全ローカル構成）

> 対象：構築済み環境を**運用する人**（社内情報システム担当／総務部の管理者）
> 前提：`docker/README.md` の手順で環境が起動済みであること
> 関連：設計値の根拠は [`02_dify_chatflow_design.md`](./02_dify_chatflow_design.md)

このマニュアルは「作った後」の話だけを扱います。日々の起動停止、規程が改訂された
ときの入れ替え、Excelテンプレートの差し替え、バックアップ、そして調子が悪いときの
一次切り分けです。

---

## 0. この環境の構成（1分で把握する）

```
ブラウザ ──80──→ [Dify]  ──社内ネットワーク──→ [n8n] ──→ templates/*.xlsx
                    │                              ↑
                    └── OpenAI API（唯一の外部通信）  └── ブラウザから 5678 で直接DL
```

| コンテナ | 役割 | 止まると何が起きるか |
|---|---|---|
| `docker-nginx-1` | Dify の入口（ポート80） | 画面が開かない |
| `docker-api-1` / `docker-worker-1` | Dify 本体 | Bot が応答しない |
| `docker-db_postgres-1` | 会話ログ・アプリ設定 | Bot が応答しない |
| `docker-weaviate-1` | ベクトルストア（規程の検索インデックス） | 検索が0件になり全部突っぱねる |
| `docker-ssrf_proxy-1` | Dify の外向き通信の中継 | ファイル要求だけ失敗する |
| `n8n_local` | ファイル配信 | ファイル要求だけ失敗する |

**外部に出るデータ**：ユーザーの質問文と、検索でヒットした規程本文の抜粋が OpenAI に
送信されます。それ以外（ファイル本体、会話ログ、判断ロジック）はすべて社内に残ります。

---

## 1. 日常運用

### 起動・停止

```bash
# 起動（Dify → n8n の順。どちらが先でも動くが、この順が無難）
cd ~/dify-local/docker && docker compose up -d
cd <このリポジトリ>/docker/n8n && docker compose up -d

# 停止（データは残る）
cd ~/dify-local/docker && docker compose down
cd <このリポジトリ>/docker/n8n && docker compose down
```

> ⚠️ `docker compose down -v` は**使わないこと**。`-v` はボリュームを削除し、
> 会話ログもナレッジも消えます。

> ⚠️ Dify のディレクトリは**常に同じ場所から**操作してください。理由は §4-8 ⑫。
> 現在どこから起動されているかは次で確認できます：
> ```bash
> docker inspect docker-api-1 --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
> ```

### 稼働確認

```bash
# 全コンテナの状態
docker ps --format 'table {{.Names}}\t{{.Status}}'

# エンドツーエンドで健全性を確認（3テスト、約1分）
python3 scripts/test_e2e.py
```

`test_e2e.py` が 3/3 PASS なら、検索・LLM・n8n連携・ファイル配信のすべてが生きています。
**朝一番にこれを流すだけで、その日の稼働確認は完了**と考えて構いません。

### ログを見る

```bash
docker compose logs -f api          # Dify（~/dify-local/docker で実行）
docker logs -f n8n_local            # n8n
```

n8n の実行履歴は UI（<http://localhost:5678> → Executions）のほうが読みやすいです。

---

## 2. 規程を改訂したとき（再Embedding）

規程が第4版になった、条文が追加された、といった場合の手順です。**所要時間は5分程度**、
うち Embedding が1〜2分です。

### 手順

```bash
# 1. 規程本文を更新する
#    01_dummy_manual_demo_logistics.md を編集
#    （見出しは ### 第N条（...） の形式を必ず維持すること。後述）

# 2. ナレッジを作り直す
python3 scripts/provision_knowledge.py --recreate

# 3. 検索品質を実測する
python3 scripts/measure_recall.py --threshold 0.3

# 4. Chatflow を新しいナレッジに向け直す
python3 scripts/provision_chatflow.py --recreate

# 5. 通しで確認する
python3 scripts/test_e2e.py
```

### なぜ Chatflow まで作り直すのか

`--recreate` はナレッジを削除して作り直すため、**dataset_id が変わります**。
Chatflow の Knowledge Retrieval ノードは dataset_id を直接持っているので、
そのままでは古い（削除済みの）ナレッジを参照し続けます。
手順4を飛ばすと、Bot が全質問に対して突っぱね応答を返すようになります。

### 規程を編集するときの注意

| 守ること | 理由 |
|---|---|
| 条文の見出しは `### 第N条（...）` 形式を維持 | この見出しでチャンクを分割している（§3-3 ①） |
| 1つの条文は 1,400 文字以内に収める | 超えると条文が途中で分断され、検索精度が落ちる |
| 連絡先のメールアドレスを本文に残す | 突っぱね応答で Citation する設計のため |

条文が 1,400 文字を超える場合は、`scripts/provision_knowledge.py` の
`PARENT_MAX_CHARS` を引き上げてください。文字数は次で確認できます：

```bash
python3 -c "
import re
text = open('01_dummy_manual_demo_logistics.md', encoding='utf-8').read()
for part in re.split(r'(?m)^(?=### )', text):
    if part.strip():
        print(len(part), part.splitlines()[0][:40])
" | sort -rn | head -5
```

### 改訂後に必ず確認すること

`measure_recall.py` が **Recall@4 >= 90%** を保っていること。
下回った場合は、新しい条文に合わせて `scripts/measure_recall.py` の `TEST_QUERIES` を
更新したうえで再測定してください。テストクエリ自体が古くなっている可能性もあります。

---

## 3. 経費精算テンプレート（xlsx）を差し替えるとき

### 手順

```bash
# 1. テンプレートを更新（スクリプトから再生成する場合）
pip install openpyxl
python3 scripts/build_expense_template.py

# 2. n8n が配信するファイルを差し替え
cp 経費精算テンプレート_v3.xlsx docker/n8n/templates/expense_template_v3.xlsx

# 3. macOS のみ：拡張属性を除去（重要）
xattr -c docker/n8n/templates/expense_template_v3.xlsx

# 4. 配信を確認
curl -s -o /tmp/dl.xlsx -w "%{http_code} %{size_download}\n" \
  http://localhost:5678/webhook/files/expense-v3
file /tmp/dl.xlsx    # → Microsoft Excel 2007+
```

**コンテナの再起動は不要です。** `docker/n8n/templates/` は bind mount なので、
ホスト側のファイルを置き換えた瞬間に反映されます。

### ファイル名を変える場合

ファイル名を変えると3箇所の修正が必要です。**1箇所でも漏れると配信が壊れます。**

1. `docker/n8n/templates/` 内の実ファイル名
2. n8n Workflow 2 の `Read/Write Files from Disk` ノードの File Selector
   （`/home/node/.n8n-files/<新しい名前>`）
3. n8n Workflow 2 の `Respond to Webhook` の `Content-Disposition` ヘッダー
   （日本語名なら RFC 5987 形式。生成方法は §4-8 ④）

変更後は `python3 scripts/export_n8n_workflows.py` でリポジトリ側の JSON も更新してください。

> ⚠️ 配置先は必ず `/home/node/.n8n-files` 配下にすること。n8n の allowlist 制約です（§4-8 ①）。

---

## 4. Bot の応答内容を変えたいとき

| 変えたいもの | 編集する場所 |
|---|---|
| 回答のトーン・フォーマット・突っぱね文 | `scripts/provision_chatflow.py` の `SYSTEM_PROMPT` |
| 質問の振り分け基準 | 同 `CLASSIFIER_INSTRUCTION` |
| ファイル要求時の回答文面 | 同 `FILE_ANSWER_TEMPLATE` |
| 使用する LLM | 同 `LLM_MODEL` |
| 検索件数・閾値 | `scripts/provision_knowledge.py` の `TOP_K` / `SCORE_THRESHOLD` |

編集後：

```bash
python3 scripts/provision_chatflow.py --recreate
python3 scripts/test_e2e.py
```

> 💡 Dify の管理画面から直接編集することもできますが、その変更はスクリプトに残りません。
> 次に `--recreate` を流した時点で失われます。**画面で試して、確定したらスクリプトに反映する**
> という運用を推奨します。画面で作った状態は
> 「アプリ → 右上メニュー → DSLをエクスポート」で吸い出せます。

---

## 5. バックアップとリストア

### バックアップ対象

| 対象 | 場所 | 中身 |
|---|---|---|
| Dify PostgreSQL | `<Difyディレクトリ>/docker/volumes/db/data` | アプリ設定・会話ログ・ナレッジのメタデータ |
| Dify Weaviate | `<Difyディレクトリ>/docker/volumes/weaviate` | ベクトルインデックス |
| Dify ストレージ | `<Difyディレクトリ>/docker/volumes/app/storage` | アップロードした原本ファイル |
| n8n | Docker volume `n8n-local_n8n_data` | ワークフロー・認証情報 |
| テンプレート | `docker/n8n/templates/` | 配信する xlsx |

Dify 側は bind mount なので**ディレクトリごとコピーするだけ**です。

### 手順（コールドバックアップ推奨）

```bash
DIFY_DIR=~/dify-local/docker
STAMP=$(date +%Y%m%d)

# 1. 停止（整合性を確保するため）
cd $DIFY_DIR && docker compose down
cd <このリポジトリ>/docker/n8n && docker compose down

# 2. Dify のデータをコピー
tar czf ~/backup_dify_$STAMP.tar.gz -C $DIFY_DIR volumes

# 3. n8n のボリュームをコピー
docker run --rm -v n8n-local_n8n_data:/data -v ~:/backup alpine \
  tar czf /backup/backup_n8n_$STAMP.tar.gz -C /data .

# 4. 再起動
cd $DIFY_DIR && docker compose up -d
cd <このリポジトリ>/docker/n8n && docker compose up -d
```

### リストア

上記の逆順で展開したあと `docker compose up -d` します。
リストア後は必ず `python3 scripts/test_e2e.py` で健全性を確認してください。

> 💡 **ナレッジと Chatflow はバックアップが無くても再構築できます**
> （`provision_knowledge.py` → `provision_chatflow.py`）。
> 本当に失って困るのは**会話ログ**と**n8n の認証情報**です。
> 最低限この2つが守れていれば復旧できます。

---

## 6. 困ったときの一次切り分け

まず `python3 scripts/test_e2e.py` を流してください。どのテストが落ちるかで原因が絞れます。

| 落ちたテスト | 疑う場所 |
|---|---|
| Test 1（規程Q&A）だけ | ナレッジ検索、または OpenAI API |
| Test 2（ガードレール）だけ | システムプロンプト（意図せず書き換わっていないか） |
| Test 3（ファイル要求）だけ | n8n、ネットワーク、xlsx の配置 |
| 全部 | Dify 本体（api / postgres）が落ちている |

### 症状別

| 症状 | 確認すること |
|---|---|
| **全質問に「規程に記載が見当たりません」と返る** | ①ナレッジが空になっていないか（`measure_recall.py`）②Chatflow が古い dataset_id を見ていないか（§2の手順4を実行）③OpenAI の Embedding が失敗していないか |
| **ファイル要求だけ失敗する** | ①`docker ps` で `n8n_local` が動いているか ②ワークフローが Active か ③`ssrf_proxy` が `demo-rag-net` に居るか（§4-8 ⑩） |
| **ファイル要求の回答が空文字** | Chatflow の Code ノード（`parse_response`）が消えていないか（§4-8 ⑨） |
| **画面が開かない** | `docker ps` で `docker-nginx-1` と `docker-api-1` が healthy か |
| **応答が異常に遅い** | OpenAI 側の遅延。`docker compose logs -f api` でリクエスト時間を確認 |
| **ダウンロードURLが `ERR_NAME_NOT_RESOLVED`** | n8n が返す `download_url` が `localhost:5678` になっているか（`n8n_local:5678` では不可。§4-7） |

### 復旧の最終手段

コンテナは壊れてもデータは bind mount / volume に残ります。

```bash
cd ~/dify-local/docker && docker compose down && docker compose up -d
```

それでも直らない場合は、ナレッジと Chatflow を作り直してください（データ損失なし・約5分）：

```bash
python3 scripts/provision_knowledge.py --recreate
python3 scripts/provision_chatflow.py --recreate
python3 scripts/test_e2e.py
```

---

## 7. 定期点検（推奨頻度）

| 頻度 | 作業 |
|---|---|
| 毎営業日 | `python3 scripts/test_e2e.py`（3/3 PASS を確認） |
| 毎月 | バックアップ取得。`measure_recall.py` で Recall@4 を確認 |
| 規程改訂時 | §2 の再Embedding手順 |
| 四半期 | Dify / n8n のバージョン更新を検討（更新前に必ずバックアップ） |
| 随時 | OpenAI API の利用額を確認 |

### コストの目安

外部課金は OpenAI のみです。

- **Embedding**：規程1本（約6,400文字）の再構築で1回あたり数円程度。改訂時のみ発生
- **LLM（gpt-4o-mini）**：1質問あたり、システムプロンプト＋検索結果4件で
  概ね2,000〜4,000トークンの入力。質問数に比例します

正確な単価は OpenAI の料金ページで確認してください。
