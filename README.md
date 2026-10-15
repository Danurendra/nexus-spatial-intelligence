# DinusNexus

**Unified AI Digital Campus Worker** — satu workspace untuk membantu berbagai peran operasional kampus menjalankan pekerjaan berbasis workflow, sumber data, dokumen, dan AI.

> Prototype hackathon. **Workflow IT Helpdesk adalah vertical slice pertama yang berjalan end-to-end.** Dataset yang dipakai bersifat **sintetis** dan selalu diberi label `SYNTHETIC`. Jangan menganggapnya sebagai kondisi kampus nyata.

## Status saat ini (faktual)

| Area | Status |
|---|---|
| IT Helpdesk deterministic flow (input → retrieval → evidence → persist → history) | implemented, tested |
| PostgreSQL persistence + Alembic migration | implemented, tested |
| API key authentication (`X-API-Key`) | implemented, tested |
| CORS untuk frontend + token metrics | implemented, tested |
| Approval gate (`waiting_for_approval` + approve/reject) | implemented, tested |
| Normalisasi `task_runs`/`execution_steps` | implemented, tested |
| CI (GitHub Actions: compile, data check, migrasi, pytest) | implemented (workflow) |
| Input validation & error handling | implemented, tested |
| LLM `analyze_evidence` (opsional, `LLM_ENABLED=true`) | implemented, tested (mock) + diverifikasi live 1x |
| Campus Twin OSM + scenario → Campus Operations assessment → IT Helpdesk follow-up | implemented; synthetic/planning data, verification details in workflow docs |
| OpenCV 5 video-to-zone state → agent trace | implemented in a feature branch; tests/CI review pending, not yet merged |
| Upload dokumen, workflow penuh role lainnya | planned |
| API/DB/Testing/Development docs | implemented |

Detail verifikasi ada di [`docs/TESTING.md`](docs/TESTING.md) dan [`docs/DEVELOPMENT_LOG.md`](docs/DEVELOPMENT_LOG.md).

Demo terbaru: di Campus Twin buka **Scenario → Run Simulation → Jalankan workflow
event**. Assessment backend menyimpan risiko/evidence/history dan dapat membuat
investigasi IT Helpdesk dari AP tidak online. Alternatif: `/workspace/operations`.
Panduan, angka baseline, konfigurasi tanpa biaya LLM, dan keterbatasan ada di
[`docs/WORKFLOWS.md`](docs/WORKFLOWS.md#demo-campus-twin--campus-operations--it-helpdesk).

## Vision Twin — OpenCV 5 video MVP

Route `/workspace/vision-twin` kini menjalankan vertical slice berbasis video. Backend menegakkan OpenCV 5.x, membaca video pendek, mengambil sampel frame, mendeteksi pejalan kaki, memetakan titik bawah bounding box ke polygon zona, dan menyimpan observasi ke SQLite. State zona, event, trace keputusan agent, frame bukti, job history, dan draf tiket yang memerlukan human review tersedia setelah refresh.

Detector default adalah OpenCV HOG (baseline klasik tanpa bobot eksternal); model COCO YOLO ONNX kompatibel dapat dikonfigurasi lewat `VISION_MODEL_PATH`. Konfigurasikan polygon dan ambang berdasarkan video kamera uji. Polygon default hanya membagi frame kiri/kanan dan bukan peta kampus terkalibrasi.

**Batasan MVP:** video diproses secara batch setelah diunggah, bukan CCTV live. Hitungan frame bukan orang unik atau occupancy keselamatan yang terkalibrasi. Agent memakai policy deterministik; ia tidak memanggil LLM atau mengubah sistem eksternal. Draf tiket harus disetujui/ditolak manusia. Artifact, state, event, dan trace disimpan lokal; kebijakan retensi otomatis, evaluasi ground-truth, dan integrasi kamera nyata belum selesai. Lihat [docs/VISION_TWIN.md](docs/VISION_TWIN.md), [docs/API.md](docs/API.md), dan [docs/WORKFLOWS.md](docs/WORKFLOWS.md).

## Fitur IT Helpdesk

1. Client mengirim laporan ke `POST /api/tasks` (dengan `X-API-Key`).
2. Backend memvalidasi input dan menyimpan task (`queued`) ke PostgreSQL.
3. LangGraph menjalankan `inspect_report → analyze_evidence → prepare_result`
   secara deterministik (langkah LLM opsional).
4. Data adapter mencari perangkat, insiden, zona, dan gedung yang relevan dari
   dataset sintetis (dengan filter zona dan tipe perangkat).
5. Hasil memuat `facts` (record asli), `evidence` (source id + dataset),
   `interpretation`, `uncertainty`, dan `recommendations`, semuanya berlabel
   `SYNTHETIC`.
6. Task, steps, dan hasil tersimpan persisten (tabel `tasks` + `task_runs` +
   `execution_steps`); history bertahan setelah restart.
7. Bila `requested_action` termasuk aksi sensitif, workflow berhenti di
   `waiting_for_approval` dan menunggu keputusan manusia via
   `POST /api/tasks/{task_id}/approval`. Backend **tidak** mengeksekusi aksi
   sensitif secara otomatis.

## Arsitektur singkat

```text
FastAPI (src/main.py) → LangGraph (inspect_report, analyze_evidence,
      prepare_result, request_approval)
      → data adapter (src/data_adapter.py) → JSON datasets (src/data/)
      → PostgreSQL (src/db/: tasks, task_runs, execution_steps) → response + history
```

Lihat [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (bagian "Implemented Architecture") dan [`docs/API.md`](docs/API.md).

## Stack

Python 3.12 · FastAPI · LangGraph · PostgreSQL 16 · SQLAlchemy 2.x · Alembic ·
Pydantic · pytest + httpx · Docker. OpenAI SDK dipakai untuk langkah LLM
opsional (`analyze_evidence`).

## Prasyarat

- Ubuntu/Linux, Python 3.12, Git, Docker.
- Virtual environment `.venv`.

## Setup lokal

```bash
# 1. Virtual environment.
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Konfigurasi environment.
cp .env.example .env
# Isi DATABASE_URL, DINUSNEXUS_API_KEY, dan (opsional) OPENAI_API_KEY di .env.
# JANGAN commit .env.
```

### Menjalankan PostgreSQL

```bash
docker run -d --name dinusnexus-postgres \
  -e POSTGRES_USER=dinusnexus \
  -e POSTGRES_PASSWORD=<password-lokal-anda> \
  -e POSTGRES_DB=dinusnexus \
  -p 127.0.0.1:5434:5432 \
  -v dinusnexus_pgdata:/var/lib/postgresql/data \
  postgres:16

# Terapkan skema.
alembic upgrade head
```

### Login akun workspace (PostgreSQL)

Halaman `/login` memakai email/password akun lokal; UI juga menyediakan API key
demo sebagai mode alternatif. Akun/sesi disimpan di PostgreSQL, password di-hash,
sesi berlaku 8 jam dan dicabut saat keluar. Belum terhubung SSO atau RBAC kampus.

Dengan venv aktif dari root, pastikan `DATABASE_URL` memakai
`postgresql+psycopg://…` dan port PostgreSQL yang benar (container lokal di atas: **5434**), lalu:

```bash
alembic upgrade head
python -m src.create_user --email staff@example.test --name "Campus Staff"
# Masukkan password baru pada prompt tersembunyi, minimal 12 karakter.
```

Tidak ada akun/password default. Set `NEXT_PUBLIC_API_BASE_URL` pada
`frontend/.env.local` ke backend, lalu restart backend/frontend dan buka `/login`.
Login akun tidak memerlukan key backend di bundle browser. Hapus konfigurasi key
publik bila ingin memakai akun saja; key demo build-time tetap tersedia setelah logout
jika sebelumnya dikonfigurasi. Workspace masih bersama, bukan isolasi data per akun.
Kontrak dan keterbatasan: [`docs/API.md`](docs/API.md#login-postgresql).

### Menjalankan API

```bash
source .venv/bin/activate
uvicorn src.main:app --reload
```

- Base URL: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

### Environment variables

| Variable | Wajib | Keterangan |
|---|---|---|
| `DATABASE_URL` | ya | koneksi `postgresql+psycopg://…` |
| `DINUSNEXUS_API_KEY` | ya | API key backend (header `X-API-Key`) |
| `CORS_ORIGINS` | tidak | origin frontend yang diizinkan (default `http://localhost:3000,http://127.0.0.1:3000`) |
| `TEST_DATABASE_URL` | tidak | database terpisah untuk test |
| `LLM_ENABLED` | tidak | `true` untuk mengaktifkan langkah LLM (default `false`) |
| `LLM_PROVIDER` | tidak | `primary` untuk provider hackathon atau `openai` untuk memakai OpenAI sebagai provider utama |
| `OPENAI_API_KEY` | tidak | fallback provider dan wajib bila `LLM_ENABLED=true` |
| `OPENAI_MODEL` | tidak | model analisis OpenAI, default `gpt-5-nano` |
| `OPENAI_BASE_URL` | tidak | endpoint OpenAI, default `https://api.openai.com/v1` |
| `LLM_FALLBACK_ENABLED` | tidak | gunakan OpenAI jika provider utama gagal, default `true` |
| `LLM_MODEL` | tidak | model provider utama, default `qwen3-coder-flash` |
| `LLM_MAX_ATTEMPTS` | tidak | batas percobaan provider (default `3`, maks `5`) |
| `LLM_TIMEOUT_SECONDS` | tidak | timeout per request (default `30`) |
| `LLM_RETRY_BASE_DELAY` | tidak | basis backoff detik (default `0.5`) |

Nilai asli tidak boleh masuk source code, dokumentasi, log, atau Git.

## Endpoint

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| GET | `/health` | publik | liveness |
| POST | `/api/tasks` | `X-API-Key` | buat task + jalankan workflow |
| GET | `/api/tasks/{task_id}` | `X-API-Key` | baca task |
| GET | `/api/tasks/{task_id}/runs` | `X-API-Key` | run & step ternormalisasi |
| POST | `/api/tasks/{task_id}/approval` | `X-API-Key` | approve/reject (`waiting_for_approval`) |
| GET | `/api/history` | `X-API-Key` | daftar task (terbaru dulu) |
| GET | `/api/metrics/tokens` | `X-API-Key` | agregat penggunaan token LLM |

Kontrak lengkap: [`docs/API.md`](docs/API.md). Langkah LLM bersifat opsional
(`LLM_ENABLED=true`); ketika aktif, node `analyze_evidence` menganalisis bukti
dengan OpenAI dan hasilnya divalidasi (Structured Outputs). Jika gagal, task
tetap tercatat sebagai `failed`.

## Menjalankan test

```bash
source .venv/bin/activate
pytest
```

Test berjalan terhadap database terpisah (`<db>_test`), tidak menyentuh data
demo. Hasil terakhir: **62 passed, 1 skipped**. Skenario dan fixture: [`docs/TESTING.md`](docs/TESTING.md).

## Known limitations

- **Data sintetis**: seluruh dataset adalah fixture JSON, bukan integrasi live.
- **Keyword search, bukan semantic search**: pencarian berbasis kata kunci +
  sinonim. Kata seperti `tidak` belum menjadi stop word sehingga bisa muncul
  kecocokan insidental.
- **Sinkron, tanpa background worker**: workflow berjalan di dalam request dan
  belum ada eksekusi asinkron/queue.
- **Approval gate, bukan eksekusi aksi**: keputusan `approve` menandai task
  `completed` dan mencatat otorisasi manusia, tetapi backend tidak menjalankan
  aksi sensitif apa pun. Ini disengaja (human-in-the-loop).
- **LLM opsional**: default deterministik. Langkah `analyze_evidence` hanya jalan
  bila `LLM_ENABLED=true`; kegagalan LLM membuat task `failed` (tidak pernah
  `completed`). Fakta/evidence tetap berasal dari dataset, bukan dari model.
- **Retry terbatas**: error provider transien (rate limit, timeout, 5xx) di-retry
  dengan exponential backoff + jitter, dibatasi `LLM_MAX_ATTEMPTS`. Error
  non-transien (mis. 400/401) dan output tidak valid tidak di-retry.
- **Steps JSON tetap dipertahankan**: respons task masih memuat `steps` (JSON)
  untuk kompatibilitas; `task_runs`/`execution_steps` adalah store terkueri.
- **`create_all` saat startup**: masih dipakai untuk kenyamanan dev; Alembic
  adalah jalur migrasi resmi. Jalankan `alembic upgrade head`.

## Campus roles (target)

1. Admissions Staff (PMB) · 2. Finance Staff · 3. Academic Administration (BAAK)
· 4. PDDikti Operator · 5. IT Helpdesk · 6. Quality Assurance Staff ·
7. Career Center Staff · 8. Digital Archive Staff.

## Dokumen proyek

Persiapan demo Azure: [`docs/AZURE_DEPLOYMENT.md`](docs/AZURE_DEPLOYMENT.md).
`deploy-azure.ps1` default hanya preflight lokal; deployment berbiaya memerlukan
persetujuan eksplisit dan resource existing. Frontend Docker dibangun dari root
repo dengan `-f frontend/Dockerfile`, memakai login akun tanpa key di browser.

- [`AGENTS.md`](AGENTS.md): instruksi untuk coding agent/OpenCode.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): branching, commit, dan pull request.
- [`docs/PRODUCT_SCOPE.md`](docs/PRODUCT_SCOPE.md): produk, delapan role, batas MVP.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): arsitektur konseptual + implementasi.
- [`docs/API.md`](docs/API.md): referensi endpoint.
- [`docs/DATABASE.md`](docs/DATABASE.md): model, migrasi, persistence.
- [`docs/TESTING.md`](docs/TESTING.md): perintah test, skenario, hasil.
- [`docs/DEVELOPMENT_LOG.md`](docs/DEVELOPMENT_LOG.md): log milestone.
- [`docs/UI_UX.md`](docs/UI_UX.md): aturan UX dan tampilan.
- [`docs/WORKFLOWS.md`](docs/WORKFLOWS.md): alur stateful workflow dan MVP Helpdesk.
- [`docs/DATA_SECURITY.md`](docs/DATA_SECURITY.md): sumber data, dokumen, keamanan, dan human approval.
- [`docs/TOKEN_EFFICIENCY.md`](docs/TOKEN_EFFICIENCY.md): pencatatan dan optimasi token.
- [`docs/AZURE_DEPLOYMENT.md`](docs/AZURE_DEPLOYMENT.md): prinsip deployment Azure dan batas biaya.
- [`docs/DOCUMENTATION_POLICY.md`](docs/DOCUMENTATION_POLICY.md): aturan file Markdown dan pemeliharaannya.
- [`docs/DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md): urutan implementasi dan Definition of Done.
- [`docs/TEAM_DEVELOPMENT_PLAN.md`](docs/TEAM_DEVELOPMENT_PLAN.md): pembagian tiga role, kerja paralel, checkpoint, dan workflow GitHub.
- [`docs/FEATURE_TASK_ASSIGNMENT.md`](docs/FEATURE_TASK_ASSIGNMENT.md): breakdown tugas per fitur untuk tiga anggota tim.
- [`docs/TECH_STACK_RECOMMENDATION.md`](docs/TECH_STACK_RECOMMENDATION.md): analisis dan rekomendasi tech stack.
- [`docs/MCP_PLUGINS.md`](docs/MCP_PLUGINS.md): plugin OpenCode dan tools development.
- [`docs/DECISIONS.md`](docs/DECISIONS.md): keputusan final versus hal yang belum ditentukan.
- [`docs/UI_COMPONENTS.md`](docs/UI_COMPONENTS.md): dokumentasi komponen UI DinusNexus.
- [`docs/CHATBOT_FEATURE.md`](docs/CHATBOT_FEATURE.md): dokumentasi fitur chatbot AI.
- [`docs/CAMPUS_TWIN_DESIGN.md`](docs/CAMPUS_TWIN_DESIGN.md): spesifikasi visual Campus Twin 2D.

## Cara menggunakan dokumen ini

1. Salin dokumen ke repository DinusNexus dengan mempertahankan struktur foldernya.
2. Audit kode yang sudah ada sebelum mengganti stack atau membuat ulang komponen.
3. Perbarui `docs/DECISIONS.md` hanya ketika keputusan `TBD` sudah dikonfirmasi.
4. Semua implementasi, data simulasi, keterbatasan, dan hasil test harus dijelaskan secara jujur dalam README dan demo.

## Catatan integritas

Dokumen adalah acuan, bukan klaim fitur. Gunakan status `implemented`, `tested`,
`partial`, atau `planned` secara jujur. Cantumkan penggunaan OpenCode, model/API,
library, dan kontribusi tim pada disclosure submission sesuai aturan hackathon.
