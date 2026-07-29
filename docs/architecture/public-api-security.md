# Phase 3：Auth 與 Public Write API

Public write API 與本機 read-only API 是兩個獨立的 application factory：

- `autocamtracker.api.app.create_app()`：本機 read-only，不註冊 mutation。
- `autocamtracker.api.public_app.create_public_app()`：Firebase/RBAC 保護的
  public API，目前唯一 mutation 是 `PATCH /api/v3/vehicles/{cloud_id}`。

## Firebase Auth / JWT

Client 透過 HTTPS 傳送 Firebase ID token：

```http
Authorization: Bearer <firebase-id-token>
```

Server 使用 Firebase Admin SDK `verify_id_token(..., check_revoked=True)`，
驗證簽章、issuer、audience、有效期、revocation 與 disabled user。不要把
Firebase custom token 傳給此 endpoint，也不要自行信任未驗證 claims。

RBAC 從 verified custom claims 讀取：

- `viewer`：無寫入權限。
- `operator`：`vehicle:write`。
- `admin`：所有權限與所有 node scope。

非 admin 使用者另需 `node_ids` claim，且只能修改所屬 edge node 的 vehicle。

## PATCH vehicle

Request 必須包含：

- `Authorization: Bearer ...`
- `Idempotency-Key`：8–128 字元；相同 key 安全 replay。
- `expected_updated_at`：optimistic concurrency token。
- `display_name` 或 `metadata` 至少一項。

成功的 vehicle update 與 audit insert 位於同一 PostgreSQL transaction。
stale update 回覆 `409`，重複 idempotency key 回傳第一次的結果。

`audit_logs` 有 PostgreSQL trigger，任何 UPDATE/DELETE 都會被資料庫拒絕。
Audit 保存 actor UID/roles、request ID、來源 IP、user agent、before/after，
但永遠不保存 bearer token 或 service-account secret。

## Rate limit 與 CORS

Rate limit state 存於 PostgreSQL `api_rate_limits`，因此所有 API instances
共享同一 fixed window。超限回覆 `429` 與 `Retry-After`。

CORS 必須是明確的 `http/https` allowlist；設定 `*` 會在啟動時失敗。
允許的 mutation method 只有 `PATCH`。

## Secrets 與部署

下列值不得提交到 Git：

- PostgreSQL URL/password
- Firebase service-account JSON

Public API 支援 `AIVD_DATABASE_URL_FILE`，Compose 使用 Docker secrets。
Firebase Admin SDK 使用 `GOOGLE_APPLICATION_CREDENTIALS` 指向唯讀 secret。
專案已忽略整個 `secrets/` 目錄。

建立 secret files 與 `.env` 後才可明確啟動 public profile：

```bash
mkdir -p secrets
cp .env.example .env
# 寫入 secrets/database_url.txt
# 放置 secrets/firebase-service-account.json
docker compose --profile public up public-api
```

Compose 只將 API 綁定到 `127.0.0.1:8080`。正式環境應由 TLS reverse proxy
對外提供 HTTPS。Uvicorn 只信任 `AIVD_FORWARDED_ALLOW_IPS` 指定的 proxy
來源，且拒絕 wildcard trusted proxies；不可直接暴露 Uvicorn port。

Firebase 驗證依據：[Verify ID Tokens](https://firebase.google.com/docs/auth/admin/verify-id-tokens)；
RBAC claims 依據：[Control Access with Custom Claims](https://firebase.google.com/docs/auth/admin/custom-claims)。
