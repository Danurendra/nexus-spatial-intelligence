# Stateful Workflows

## Pola bersama

Semua campus worker harus dibangun menggunakan pola workflow yang bisa dilacak, walaupun isi langkahnya berbeda.

```text
User Input / Document
        ↓
Validate & Identify Intent
        ↓
Create Task + Task Run
        ↓
Execute Allowed Steps / Tools
        ↓
Persist Step Status + Evidence
        ↓
Analyze / Calculate / Retrieve
        ↓
Assemble Result with Sources & Uncertainty
        ↓
Approval Gate if a consequential action is requested
        ↓
Persist Final Result and Audit Events
        ↓
Display Result and History
```

Pekerjaan boleh menghasilkan partial result jika sebagian tools gagal, tetapi UI harus menjelaskan bagian yang gagal dan batas kesimpulannya.

## Task/run state

State machine konseptual:

- `queued`: diterima dan menunggu eksekusi.
- `running`: workflow sedang dieksekusi.
- `waiting_for_approval`: menunggu keputusan manusia.
- `completed`: langkah wajib berhasil dan hasil disimpan.
- `failed`: tidak dapat menghasilkan hasil yang valid.
- `cancelled`: dihentikan oleh pengguna/sistem.

Step status dapat lebih terperinci, termasuk `skipped` atau `retrying`, sesuai implementasi.

## Workflow prioritas: IT Helpdesk

### Input

- Deskripsi masalah.
- Lokasi/gedung atau zona, jika diketahui.
- Jenis perangkat atau layanan, jika diketahui.
- Waktu/indikasi kejadian, jika tersedia.
- Lampiran log/screenshot/dokumen yang didukung.

### Steps

1. Validasi laporan dan ekstrak field relevan.
2. Buat incident/task ID dan simpan permintaan.
3. Ambil record perangkat dan lokasi yang relevan dari database/tool.
4. Ambil histori insiden yang cocok jika tersedia.
5. Jalankan pemeriksaan jaringan hanya jika tool dan lingkungan memang tersedia serta aman.
6. Simpan output tiap tool sebagai evidence dengan sumber dan waktu bila tersedia.
7. Evaluasi bukti dan tandai hipotesis sebagai supported, contradicted, atau unknown jika logika aplikasi mendukungnya.
8. Susun diagnosis dengan confidence/ketidakpastian yang tidak menyesatkan.
9. Berikan rekomendasi berikut langkah verifikasi.
10. Minta approval sebelum tindakan yang berdampak (contoh reset akun/perubahan konfigurasi) bila tindakan tersebut benar-benar tersedia.
11. Simpan hasil akhir, status, dan audit event.
12. Kaitkan ke Campus Twin jika record insiden dan perangkat memiliki hubungan yang terverifikasi.

### Hasil

- Ringkasan insiden.
- Fakta/evidence yang ditemukan.
- Diagnosis atau status “belum cukup bukti”.
- Hipotesis dan bukti pendukung/penyangkal bila dievaluasi.
- Rekomendasi langkah berikutnya.
- Sumber/record ID.
- Status task/tiket.
- Waktu/durasi dan token usage apabila benar-benar terukur.

### Data demo

Gunakan dataset sintetis yang jelas diberi label. Contoh gedung/perangkat tidak mewakili kondisi kampus nyata kecuali terintegrasi dengan sumber yang sah dan diverifikasi.

## Demo Campus Twin → Campus Operations → IT Helpdesk

Alur ini memakai model/geometri OSM existing, bukan menggantinya. Di dashboard `/`:

1. Buka **Scenario** pada Campus Twin, lalu **Run Simulation**. Proyeksi visual
   tetap model lokal `scenarioModel.ts`, dengan label sintetis/asumsi.
2. Panel **Workflow Agent** muncul di bawah peta. Agregat peserta konkuren,
   jumlah venue, dan kapasitas skenario diteruskan sebagai **planning input**;
   daya 3.200 kW/uplink 5.000 Mbps adalah fixture. Model agregat backend terpisah
   dari distribusi gedung/pengali cuaca Twin; jangan mengklaim keduanya identik.
3. Isi nama event, tekan **Jalankan workflow event**. Backend memeriksa inventory
   dan insiden, menghitung ulang input, lalu menyimpan task Campus Operations.
4. Buka **Input & forecast tersimpan**, risiko, rekomendasi, execution steps,
   dan **Evidence**. Warna/animasi peta bukan bukti kondisi live.
5. Tekan **Investigasi device-AP-A2-02**. Server memvalidasi ID terhadap evidence
   event sebelum membuat task IT Helpdesk. Tidak ada restart atau perubahan
   perangkat. Buka **task & execution history**, lalu refresh untuk menunjukkan
   persistence. ID event sumber tercantum pada description task investigasi.

Alternatif demo angka yang mudah direproduksi: buka `/workspace/operations`,
pilih **Baseline**, gunakan input default 39.000 peserta, 18.000 konkuren,
6 jam, kapasitas 20.000, 3 venue, daya 3.200 kW/uplink 5.000 Mbps. Assessment
backend menghasilkan 2.805 kW, 12.118 kWh, 3.630 Mbps, 8 AP online dalam dataset,
dan estimasi 11 AP tambahan dengan asumsi 200 Mbps/AP. Angka tersebut bukan
telemetry live/jaminan keselamatan. Tampilkan alasan serta asumsi, bukan angka saja.

### Menjalankan dan memverifikasi demo

- Backend: root proyek, environment `.env` lokal, PostgreSQL tersedia,
  `alembic upgrade head`, lalu `uvicorn src.main:app --reload`.
- Frontend: `frontend/`, `.env.local` dengan URL backend dan key demo yang cocok,
  `npm ci`, lalu `npm run dev`. Key browser bukan key produksi/provider AI.
- Default `LLM_ENABLED=false`: demo di atas tanpa biaya LLM. Review AI opsional
  memakai OpenAI existing ketika enabled; jangan aktifkan saat test rutin.
  Batasi percobaan via `LLM_MAX_ATTEMPTS`; budget dolar bukan hard cap aplikasi.
- Jalur gagal: ubah **Venue capacity** menjadi 0 di Operations lalu submit;
  server menolak `422`, UI menampilkan error dan tombol dapat dicoba ulang.
  Provider/data failure membuat task `failed`, bukan completed palsu.
- Backend regression: `python -m pytest tests/test_event_planning.py`.
- Frontend: `npm run test -- --run`, `npx tsc --noEmit`, `npm run build`.
  Jangan build ke `.next` yang sama saat dev server aktif; hentikan dev server
  sendiri terlebih dahulu atau gunakan snapshot terisolasi. Lint masih meminta
  setup ESLint karena konfigurasi repo belum tersedia.
- Browser E2E: `frontend/e2e/event-demo.spec.ts`, `npx playwright test`.
  Config default Edge, frontend `http://127.0.0.1:3001`; siapkan frontend/backend
  **terisolasi** dengan database test, key demo, `LLM_ENABLED=false`, dan origin
  frontend di CORS. Override URL dengan `DEMO_FRONTEND_URL`, browser dengan
  `PLAYWRIGHT_CHANNEL`. Tests membuat task: jangan arahkan ke produksi.

Keterbatasan: event masih input pengguna, bukan kalender terhubung; belum ada
RBAC per-worker, queue, streaming UI progress event, sensor live, pemetaan venue
OSM → AP yang terverifikasi, atau eksekusi fasilitas/jaringan otomatis. Hasil
tersimpan dapat dibaca setelah refresh; kontrol input/preview tidak dipersistenkan.


## Vision Twin: uploaded frame analysis

Route `/workspace/vision-twin` runs an independent Computer Vision vertical slice:

1. Operator chooses a campus zone and uploads a JPEG/PNG/WebP frame (8 MiB max).
2. Frontend posts multipart form data to `POST /api/vision/pedestrians`.
3. The authenticated backend validates the upload and decodes it with OpenCV.
4. By default, OpenCV HOG detects visible pedestrians without external model weights. An operator can configure a compatible YOLO COCO ONNX export through `VISION_MODEL_PATH`.
5. The response returns per-frame bounding boxes, an annotated image, a count, detector name, timestamp, and a provenance label.

This version deliberately **does not** connect a live camera, write images or results to the database, calculate calibrated real occupancy, or automatically change the Campus Twin status/layers. The selected zone is context supplied by the operator, not a verified camera-to-building mapping. Before live integration, define permission, retention, access control, persisted observation schema, measurement calibration, and zone/camera mapping. Verify real device integration separately from this uploaded-image path.

## Operations: investigasi IT dari halaman workspace

Route `/workspace/operations` mempertahankan event planner. Tab **Investigasi IT**
(`/workspace/operations?view=incidents`) menggunakan jalur task persisten yang berbeda
dari chat conversation:

1. Petugas mengisi deskripsi, zona dari dataset, jenis perangkat, dan permintaan review opsional.
2. UI mengirim `POST /api/tasks` dengan worker `it_helpdesk`. Workflow berjalan sinkron;
   selama request UI hanya menampilkan status menunggu, bukan progress node buatan.
3. Riwayat dibaca dari `/api/history`, difilter ke IT Helpdesk; inspector membaca run
   ternormalisasi dari `/api/tasks/{id}/runs` dengan fallback berlabel ke steps task.
4. Fakta dan source ID terpisah dari interpretasi, rekomendasi, dan ketidakpastian.
   Label `SYNTHETIC` selalu terlihat. Mode deterministik ditampilkan bila langkah LLM skipped;
   mode LLM hanya ditampilkan ketika analisis berhasil dan hasil tersedia.
5. Review tindakan sensitif dapat disetujui/ditolak dengan catatan melalui endpoint approval.
   Keputusan tidak mengeksekusi aksi pada perangkat atau akun.
6. Kegagalan request memuat ulang riwayat agar task gagal yang sudah disimpan tetap terlihat.
   Filter pencarian/status tidak menampilkan detail task di luar hasil filter.

Setup mengikuti `.env.example` dan `frontend/.env.example`. Untuk analisis LLM,
aktifkan `LLM_ENABLED=true` dan konfigurasi OpenAI pada backend; key provider tidak
ditaruh di browser. Mode deterministik tetap tersedia tanpa panggilan AI berbayar.

Tes client: `npm run test -- --run src/lib/operationsApi.test.ts` di `frontend/`.
Tes browser dengan semua endpoint backend dimock:
`npx playwright test e2e/operations-incidents.spec.ts` (URL frontend dari `DEMO_FRONTEND_URL`).
Tes ini tidak memanggil provider AI dan tidak membuktikan kompatibilitas PostgreSQL atau LLM live.
UI mengikuti palet terang workspace yang ada; preferensi warna gelap tidak mengubah
tema global. Header global masih memiliki overflow kecil pada viewport 390px;
konten modul investigasi diuji terpisah tanpa mengganti layout tim.

Verifikasi 10 Oktober 2026: tes client Operations 11 lulus; browser Operations
5 lulus (API dimock, Edge, frontend lokal port 3000), termasuk reload, approval,
retry, evidence, keyboard, serta viewport mobile/reduced-motion. Regresi backend
IT Helpdesk terkait: 53 lulus, 1 live-LLM dilewati dengan database SQLite terisolasi
di direktori temporer. Type-check dan `git diff --check` lulus. Build tidak dijalankan
ke `.next` karena dev server tim aktif; lint belum tersedia tanpa setup ESLint.
Pemeriksaan browser ulang setelah perubahan paralel tim terblokir oleh server Next.js:
`Cannot find module './vendor-chunks/@opentelemetry.js'` pada cache `.next`.
Perlu restart dev server setelah aktivitas build selesai, lalu ulangi tes browser;
cache/proses bersama tidak dihapus atau dihentikan otomatis.

## Workflow dokumen (shared capability)

1. Validasi ekstensi, MIME/type, ukuran, dan batas upload.
2. Simpan file dengan nama/ID internal yang aman.
3. Ekstrak teks/struktur menggunakan parser yang sesuai.
4. Catat status parsing dan error.
5. Jalankan task terhadap isi yang relevan saja.
6. Simpan referensi ke halaman, sheet, baris, atau bagian bila parser mendukungnya.
7. Tampilkan hasil serta keterbatasan ekstraksi.

PDF scan/image mungkin memerlukan OCR; jika OCR tidak tersedia, nyatakan keterbatasan daripada berpura-pura file terbaca.

## Worker-specific workflow outlines

- **PMB:** pertanyaan → retrieval sumber PMB → jawaban dengan referensi; upload → pemeriksaan kelengkapan → daftar item tersedia/kosong.
- **Finance:** data pembayaran → validasi schema → rekonsiliasi deterministic → exceptions → review manusia. Jangan membuat pembayaran atau mengirim pengingat tanpa izin.
- **BAAK:** permintaan → pencarian data/jadwal → verifikasi sumber → jawaban/draf. Perubahan catatan perlu otorisasi.
- **PDDikti:** dataset → validasi field/format/konsistensi → exception report → petugas meninjau. Jangan mengklaim pengiriman ke PDDikti tanpa integrasi.
- **IT Helpdesk:** intake → data/network evidence → analisis → rekomendasi → ticket/history.
- **Quality Assurance:** kriteria → cari dokumen bukti → mapping dengan sumber → gaps untuk review ahli.
- **Career Center:** data survei → pemeriksaan schema/anonymization → perhitungan → ringkasan berbasis hasil.
- **Digital Archive:** query → pencarian/classification → hasil berperingkat dengan metadata/link.

Outline ini adalah target desain. Hanya workflow yang telah diimplementasikan dan diuji boleh ditandai “implemented”.
