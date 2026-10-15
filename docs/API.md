# API Reference — DinusNexus Backend


## Vision Twin — Uploaded pedestrian frame analysis

### POST /api/vision/pedestrians

Memproses **satu gambar yang diunggah**, bukan stream CCTV. Endpoint memerlukan autentikasi yang sama dengan workspace (X-API-Key atau bearer session) dan menerima multipart/form-data.

| Field | Type | Wajib | Batas |
|---|---|---|---|
| file | file | yes | JPEG, PNG, WebP; maksimum 8 MiB |
| zone_id | string | yes | 1–80 karakter; konteks zona yang dipilih user |
| camera_label | string | no | 1–80 karakter; default Uploaded frame |

Contoh:

~~~bash
curl -X POST http://127.0.0.1:8000/api/vision/pedestrians \
  -H "X-API-Key: $DINUSNEXUS_API_KEY" \
  -F "file=@frame.jpg" \
  -F "zone_id=zone-A1" \
  -F "camera_label=Koridor utara"
~~~

Respons sukses berisi people_count, koordinat bounding box dalam piksel, frame beranotasi sebagai JPEG data URL, detector, timestamp, ukuran gambar, dan daftar keterbatasan. data_label=OBSERVED_FROM_UPLOADED_IMAGE menjelaskan provenance: observasi dari satu unggahan, bukan telemetry live.

Detector default adalah **OpenCV HOG pedestrian detector** (baseline klasik; tidak memerlukan bobot eksternal). Untuk model detector yang lebih kuat, VISION_MODEL_PATH dapat menunjuk ke ekspor YOLOv8/YOLOv5 COCO ONNX yang kompatibel dengan OpenCV DNN; threshold konfigurasi VISION_CONFIDENCE_THRESHOLD default 0.25. Ekspor model ONNX harus disediakan dan divalidasi oleh operator. Endpoint tidak mengunduh model secara otomatis.

Error utama: 401 auth invalid, 413 unggahan/resolusi terlalu besar, 415 tipe konten tidak didukung, 400 file bukan gambar valid, 503 model/pipeline tidak tersedia. Frame tidak ditulis ke disk atau database, tidak membangun histori, dan tidak otomatis memperbarui occupancy atau status gedung; pengaitan zone_id hanya konteks yang dikirim pemakai. Jumlah deteksi bukan identitas unik maupun occupancy terkalibrasi. Pertimbangkan izin, retensi, keamanan data, dan batas penggunaan sebelum menghubungkan kamera sebenarnya.


> Status: **implemented and tested** for the IT Helpdesk deterministic flow.
> Base URL in local development: `http://127.0.0.1:8000`.
> Interactive schema: `http://127.0.0.1:8000/docs` (Swagger UI) and
> `/openapi.json`.

## Authentication

Protected endpoints require a backend API key sent in the `X-API-Key` header.
The value is read from the `DINUSNEXUS_API_KEY` environment variable.

Alternatif untuk akun workspace: `Authorization: Bearer <access_token>` dari
`POST /api/auth/login`. Sesi dan akun diverifikasi ke database pada setiap request
task/conversation/event. Bearer invalid/expired tidak fallback ke API key.
API key existing tetap kompatibel; `/health` tetap publik. Semua akun aktif
mengakses workspace operasional bersama; belum ada RBAC/isolasi history per akun.

### Login PostgreSQL

Jalankan migrasi `alembic upgrade head` (revision `0004_user_sessions`), lalu
buat akun secara lokal dengan `python -m src.create_user --email staff@example.test
--name "Campus Staff"`. Password diminta tersembunyi, minimal 12/maksimal 128 karakter;
tidak ada password default atau registrasi publik. URL harus memakai driver
`postgresql+psycopg://…` dan port service yang benar (container lokal README: 5434).

| Method | Path | Auth | Respons |
|---|---|---|---|
| POST | `/api/auth/login` | email/password | `200`: user, access_token, token_type, expires_at |
| GET | `/api/auth/me` | bearer session | `200`: user; `401`: sesi expired/invalid |
| POST | `/api/auth/logout` | bearer token | `204`: sesi token dicabut (idempotent) |

Body login: `{"email":"staff@example.test","password":"<password-akun>"}`.
Email dinormalisasi trim/lowercase; input/field tambahan invalid → `422`.
Password tidak di-trim. Password tersimpan PBKDF2-SHA256 dengan salt acak dan
600.000 iterasi; token acak hanya disimpan sebagai digest SHA-256 di database.
Sesi berlaku 8 jam; user inactive/expired ditolak. Lima login salah mengunci
akun 15 menit. Error akun tidak dikenal/password salah/akun nonaktif sama (`401`),
database tidak tersedia → `503`. Respons autentikasi menggunakan `Cache-Control: no-store`.

Token tidak memberi role admin; pembuatan akun hanya CLI dengan akses database lokal.
Bearer token browser tersimpan di sessionStorage dan bisa dibaca JavaScript.
HTTPS, hardening XSS, rate-limit global, reset-password aman, RBAC dan desain
cookie HttpOnly/BFF masih diperlukan sebelum penggunaan produksi.

- Missing or wrong key → `401`.
- Server key not configured → `500` (the API fails closed rather than exposing
  endpoints).

`GET /health` is public.

```bash
# The key is read from your local .env; never commit or paste it into docs.
curl -s http://127.0.0.1:8000/api/history \
  -H "X-API-Key: $DINUSNEXUS_API_KEY"
```

## Endpoints

### `POST /api/event-plans`

Workflow Campus Operations: input event → inventory AP/insiden sintetis →
kalkulasi dampak → deteksi risiko/rekomendasi → review AI opsional → task persisten.
Memerlukan `X-API-Key`; response `201` menggunakan [Task object](#task-object)
dengan `worker: campus_operations`. Tidak ada migrasi/tabel event baru.

Body JSON (semua field wajib):

```json
{
  "name": "Wisuda kampus",
  "attendance": 39000,
  "concurrentOccupancy": 18000,
  "durationHours": 6,
  "venueCapacity": 20000,
  "venues": 3,
  "availablePowerKw": 3200,
  "availableNetworkMbps": 5000
}
```

- Server menolak field tambahan, nilai nol/negatif/non-finite, concurrent occupancy
  melebihi attendance, dan nama kosong (`422`). Attendance/concurrent/capacity
  maksimal 100.000; durasi maksimal 168 jam; venues 1–100; daya/jaringan ≤1.000.000.
- Event dimasukkan pengguna; bukan deteksi otomatis kalender/live telemetry.
  Inventory dibaca dari `data_adapter.load_data`, bukan status hasil karangan AI.
- `result.event_input` menyimpan asumsi; `result.forecast` menyimpan kalkulasi
  backend. `facts`/`evidence` berisi AP dan insiden aktif dari dataset sintetis,
  **campus-wide**, belum membuktikan relasi ke venue event/gedung OSM.
- Formula dasar mengikuti `frontend/src/data/eventSimulation.ts`; tambahan kapasitas
  akses adalah asumsi **200 Mbps/AP online**, bukan throughput terukur. Forecast
  memiliki `onlineAccessPoints`, `estimatedAccessCapacityMbps`, dan
  `additionalAccessPoints` selain metrik daya, energi, okupansi, dan uplink.
- LangGraph steps: `inspect_event_records`, `calculate_event_impact`,
  `prepare_event_assessment`, `analyze_event_evidence`. JSON steps menyimpan
  timestamp dan `duration_ms` terukur; normalized steps menyimpan durasi dalam
  `detail`. `/api/history`, `/api/tasks/{id}`, `/api/tasks/{id}/runs` juga membaca
  task Campus Operations. Setiap langkah yang selesai dipersistenkan.
- Default `analysis_mode: deterministic`; langkah review AI `skipped`.
  `LLM_ENABLED=true` memakai `src/llm/analysis.py` yang sudah ada (bounded digest,
  OpenAI Structured Outputs, maksimum 700 output tokens/request, bounded retries).
  Review disimpan terpisah di `result.analysis`, mode menjadi `llm_assisted`,
  usage masuk kolom task/token metrics. Tidak mengubah evidence atau fakta.
- Database gagal sebelum task tersimpan → `503`. Data/kalkulasi/provider gagal →
  `500` dengan task/run ID dan kode aman `EVENT_ASSESSMENT_FAILED`; task dan
  langkah gagal dipersistenkan. Hasil kalkulasi yang sudah disimpan tetap tersedia.
- Tidak ada restart perangkat, deployment AP, perubahan konfigurasi, atau aksi
  sensitif yang dieksekusi. Tidak menambah API key Azure/provider baru.

### `POST /api/event-plans/{task_id}/helpdesk`

Follow-up yang diminta manusia untuk AP tidak online dalam evidence event.
Memerlukan `X-API-Key`; body `{"device_id": "device-AP-A2-02"}`.

- `201`: task IT Helpdesk baru dari workflow existing, dengan zone/device type
  yang diambil server dari evidence dan ID event sumber dalam description.
- `404`: event tidak ada; `409`: assessment belum completed; `422`: ID bukan AP
  tidak online dalam evidence event; `503`: database tidak tersedia.
- `requested_action` tidak diisi; hanya investigasi, bukan aksi perangkat. Bila
  `LLM_ENABLED=true`, analisis IT Helpdesk existing juga dapat memakai OpenAI.
- Endpoint `/api/tasks` tetap hanya menerima `it_helpdesk`; Campus Operations
  dibuat lewat `/api/event-plans`, bukan memperluas kontrak worker lama.

### `GET /health`

Public liveness probe.

**200**
```json
{ "status": "ok", "service": "dinusnexus-api" }
```

### `POST /api/tasks`

Create a task, persist it, run the helpdesk workflow, and return the final task.

**Headers:** `X-API-Key` (required), `Content-Type: application/json`

**Request body**

| Field | Type | Required | Constraints | Default |
|---|---|---|---|---|
| `worker` | string | no | must be `it_helpdesk` | `it_helpdesk` |
| `description` | string | yes | 5–2000 chars | — |
| `location` | string | no | zone id, e.g. `zone-A1` | `null` |
| `device_type` | string | no | e.g. `access_point`, `gateway` | `null` |
| `requested_action` | string | no | ≤100 chars; sensitive values (`reset_account`, `restart_device`, `change_config`, `network_change`) trigger the approval gate | `null` |

```bash
curl -s -X POST http://127.0.0.1:8000/api/tasks \
  -H "X-API-Key: $DINUSNEXUS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Wi-Fi di Laboratorium Komputer 1 mengalami gangguan koneksi.",
    "location": "zone-A1",
    "device_type": "access_point"
  }'
```

**201** — the serialized task (see [Task object](#task-object)).

**422** — validation error (Pydantic), for example a description shorter than 5
characters or an unknown worker.

**503** — database unavailable; the task could not be saved.

**500** — workflow failure. The task is still persisted with `status: "failed"`:

```json
{
  "detail": {
    "task_id": "…",
    "run_id": "…",
    "error": { "code": "WORKFLOW_FAILED", "message": "The workflow could not complete." }
  }
}
```

### `GET /api/tasks/{task_id}`

Read a single persisted task.

**Headers:** `X-API-Key` (required)

- **200** — task object.
- **404** — `{ "detail": "Task not found" }`
- **503** — database unavailable.

### `GET /api/tasks/{task_id}/runs`

Read the normalized execution record(s) for a task. Each run lists its ordered
steps from the `task_runs` / `execution_steps` tables.

**Headers:** `X-API-Key` (required)

**200**
```json
{
  "items": [
    {
      "run_id": "…",
      "task_id": "…",
      "worker": "it_helpdesk",
      "status": "completed",
      "created_at": "…",
      "finished_at": "…",
      "steps": [
        {
          "step_id": "inspect_report",
          "order": 1,
          "name": "Search synthetic helpdesk data",
          "status": "completed",
          "source_ids": ["device-AP-A1-01"],
          "detail": null,
          "error": null,
          "model": null,
          "usage": null
        }
      ]
    }
  ]
}
```

- **404** — task not found.
- **503** — database unavailable.

### `POST /api/tasks/{task_id}/approval`

Record a human approve/reject decision for a task in `waiting_for_approval`.
The backend **does not execute the sensitive action**; it only stores the
authorization decision (human-in-the-loop).

**Headers:** `X-API-Key` (required)

**Request body**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `decision` | string | yes | `approve` or `reject` |
| `note` | string | no | ≤500 chars |

```bash
curl -s -X POST http://127.0.0.1:8000/api/tasks/$TASK_ID/approval \
  -H "X-API-Key: $DINUSNEXUS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "decision": "approve", "note": "Disetujui oleh leader shift." }'
```

- `approve` → task `status: "completed"`, `approval.status: "approved"`.
- `reject` → task `status: "cancelled"`, `approval.status: "rejected"`.
- **200** — updated task object.
- **404** — task not found.
- **409** — task is not waiting for approval.
- **422** — invalid `decision`.
- **503** — database unavailable.

### `GET /api/history`

List persisted tasks, newest first.

**Headers:** `X-API-Key` (required)

**200**
```json
{ "items": [ { /* task object */ } ] }
```

### `GET /api/metrics/tokens`

Aggregate LLM token usage across persisted tasks (official token-efficiency
metric). Tasks without LLM usage are reported as `unavailable`.

**Headers:** `X-API-Key` (required)

**200**
```json
{
  "totals": {
    "tasks": 5,
    "tasks_with_usage": 2,
    "input_tokens": 1224,
    "output_tokens": 362,
    "unavailable": 3
  },
  "by_model": [
    { "model": "gpt-4o-mini", "tasks": 2, "input_tokens": 1224, "output_tokens": 362 }
  ],
  "items": [
    { "task_id": "…", "model": "gpt-4o-mini", "input_tokens": 612, "output_tokens": 181, "created_at": "…" }
  ]
}
```

**503** — database unavailable.

## CORS

The API allows browser calls from origins configured in `CORS_ORIGINS`
(comma-separated; default `http://localhost:3000,http://127.0.0.1:3000`).
Preflight (`OPTIONS`) requests return `Access-Control-Allow-Origin` for allowed
origins. Add your frontend origin to `CORS_ORIGINS` in `.env` before deploying.

## Task object

```json
{
  "task_id": "a046ba4d-…",
  "run_id": "…",
  "worker": "it_helpdesk",
  "description": "Wi-Fi di Laboratorium Komputer 1 mengalami gangguan koneksi.",
  "location": "zone-A1",
  "device_type": "access_point",
  "requested_action": null,
  "status": "completed",
  "created_at": "2026-10-09T11:27:25.699147+00:00",
  "steps": [
    {
      "step_id": "inspect_report",
      "name": "Search synthetic helpdesk data",
      "status": "completed",
      "source_ids": ["device-AP-A1-01", "device-AP-A1-02", "incident-001", "incident-008", "zone-A1", "building-A"]
    },
    {
      "step_id": "analyze_evidence",
      "name": "Analyze evidence with LLM",
      "status": "completed",
      "model": "gpt-4o-mini",
      "usage": { "input_tokens": 612, "output_tokens": 181 }
    },
    {
      "step_id": "prepare_result",
      "name": "Prepare result from synthetic data",
      "status": "completed",
      "source_ids": ["device-AP-A1-01", "device-AP-A1-02", "incident-001", "incident-008", "zone-A1", "building-A"]
    }
  ],
  "result": {
    "facts": [
      { "dataset": "devices", "record": { "id": "device-AP-A1-01", "…": "…" } }
    ],
    "evidence": [
      { "source_id": "device-AP-A1-01", "dataset": "devices" }
    ],
    "analysis": {
      "summary": "Gangguan koneksi Wi-Fi di Laboratorium Komputer 1 telah dilaporkan.",
      "findings": ["…"],
      "recommendations": ["…"],
      "uncertainty": ["Data bersifat sintetis."],
      "model": "gpt-4o-mini",
      "usage": { "input_tokens": 612, "output_tokens": 181 }
    },
    "interpretation": ["Found 8 matching records in synthetic datasets.", "…"],
    "uncertainty": ["These records are synthetic and do not represent verified live campus conditions."],
    "recommendations": ["Verify the relevant device and incident details before taking action."],
    "data_label": "SYNTHETIC"
  },
  "error": null,
  "approval": null,
  "llm_model": "gpt-4o-mini",
  "input_tokens": 612,
  "output_tokens": 181
}
```

### Field notes

- `steps` — execution timeline. Every step carries an explicit `status`. The
  `analyze_evidence` step is `skipped` when `LLM_ENABLED` is not `true`.
- `requested_action` — normalized (lower-cased) action requested by the client;
  `null` when none. Sensitive values trigger the approval gate.
- `approval` — `null` unless the task required approval. When set, it contains
  `required`, `status` (`pending`/`approved`/`rejected`), `action`, `decision`,
  `note`, and `decided_at`.
- `llm_model` / `input_tokens` / `output_tokens` — per-task LLM usage; `null`
  when the LLM step did not run or usage was unavailable.
- `result.facts` — original dataset records. `result.evidence` — `source_id` +
  `dataset`, de-duplicated. Both are **always derived from the data adapter**; the
  LLM cannot add or invent them.
- `result.analysis` — validated LLM output (`summary`, `findings`,
  `recommendations`, `uncertainty`, `model`, `usage`), or `null` when the LLM step
  is disabled.
- `result.interpretation` / `uncertainty` / `recommendations` — user-facing arrays;
  deterministic baseline plus LLM additions when enabled.
- `result.data_label` — always `SYNTHETIC`.
- `error` — populated (`{code, message}`) only for failed tasks.

## LLM analysis (optional)

When `LLM_ENABLED=true`, the workflow runs `inspect_report → analyze_evidence →
prepare_result` (then `request_approval` when a sensitive action is requested).
The model:

- receives only a bounded digest of already-retrieved records (max 6 per dataset,
  allow-listed fields, truncated), never the whole dataset;
- is not asked for, and cannot produce, source IDs;
- returns Structured Output validated with Pydantic.

If the provider fails, times out, or returns invalid output, the API responds:

- HTTP `500`, and
- the task is persisted with `status: "failed"`, `error.code: "LLM_ANALYSIS_FAILED"`,
  and an `analyze_evidence` step marked `failed`.

A failed LLM step is **never** reported as `completed`.

Token usage from the provider is stored in `result.analysis.usage` when available;
otherwise it is `{"status": "unavailable"}`. No prompt content or credentials are
logged.

### Retry and timeout

The provider call uses a bounded retry policy:

- Each request has a timeout (`LLM_TIMEOUT_SECONDS`, default 30s).
- Transient errors — connection/timeout, HTTP 408/409/429, and 5xx — are retried
  with exponential backoff + jitter, up to `LLM_MAX_ATTEMPTS` (default 3, capped
  at 5).
- Non-transient errors (e.g. 400/401) and structurally invalid output are **not**
  retried; they fail fast as `LLM_ANALYSIS_FAILED`.
- The OpenAI SDK's own retry loop is disabled so the total number of attempts is
  exactly the configured bound.

## Status values

Implemented: `queued`, `running`, `waiting_for_approval`, `completed`, `failed`,
`cancelled`.

- `waiting_for_approval` — a sensitive `requested_action` paused the workflow;
  resolve it via `POST /api/tasks/{task_id}/approval`.
- `cancelled` — the approval decision was `reject`.

## Endpoint implementation status

| Endpoint | Implemented | Tested | Notes |
|---|---|---|---|
| `GET /health` | yes | yes | public |
| `POST /api/tasks` | yes | yes | auth + validation + persistence |
| `GET /api/tasks/{id}` | yes | yes | reads from PostgreSQL |
| `GET /api/tasks/{id}/runs` | yes | yes | normalized run/steps |
| `POST /api/tasks/{id}/approval` | yes | yes | human-in-the-loop gate |
| `GET /api/history` | yes | yes | reads from PostgreSQL |
| `GET /api/metrics/tokens` | yes | yes | aggregates persisted LLM usage |
| LLM-backed analysis | yes | yes (mock) + live 1x | optional via `LLM_ENABLED=true` (`analyze_evidence`) |
