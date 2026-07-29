# Phase 2：PostgreSQL、Alembic 與 Edge Outbox

## 正式 schema

`src/autocamtracker/cloud/postgres_schema.py` 是 SQLAlchemy metadata，
`migrations/versions/20260729_0001_phase2_schema.py` 是不可變的初始
Alembic revision。正式資料表如下：

- `nodes`
- `vehicles`
- `vehicle_id_mappings`
- `sessions`
- `events`
- `vehicle_features`
- `gallery_rollback_events`
- `idempotency_keys`

`vehicle_id_mappings` 使用 `(node_id, local_id, cloud_id)` composite foreign
key，資料庫本身會拒絕把 local identity 指到另一筆 cloud vehicle。所有外部
mutation 與 event 都以 idempotency key/event ID 去重。

## 啟動 PostgreSQL

Compose 使用開發用預設密碼；非本機環境應先由 `.env.example` 建立 `.env`。

```bash
docker compose up -d postgres
docker compose run --rm migrate
```

執行真 PostgreSQL integration tests：

```bash
docker compose --profile test run --rm integration-tests
```

## SQLite → PostgreSQL import

Importer 以 `mode=ro` 開啟既有 SQLite，不會修改 edge database。cloud ID
由 `(node_id, local_id)` 使用固定 namespace UUIDv5 產生，因此可重跑且不會
建立重複 vehicle、feature 或 rollback audit。Telemetry JSONL 也使用
`(node_id, source_file, line_number)` 產生穩定 event ID。

```bash
ai-vision-director-import \
  --node-id edge-mac-01 \
  --database-url postgresql+psycopg://... \
  --upgrade \
  --telemetry-dir outputs/telemetry
```

## Edge outbox

`EdgeOutbox` 是獨立 SQLite store，不與 Vehicle Database 共用 transaction。
enqueue 使用 event ID 去重；worker 以 `BEGIN IMMEDIATE` claim batch，並使用
lease 防止 process crash 造成永久卡住。失敗採 exponential backoff，超過
上限移入 `dead` 狀態。

`CloudEventRouter` 先以 event ID 作為 command idempotency key 投影
`vehicle.upsert`／`vehicle.delete`，再保存 source event。若第二步失敗，
retry 不會重複執行 vehicle mutation。

```bash
ai-vision-director-sync \
  --database-url postgresql+psycopg://... \
  --watch
```

Compose 版本：

```bash
docker compose --profile sync up edge-sync
```
