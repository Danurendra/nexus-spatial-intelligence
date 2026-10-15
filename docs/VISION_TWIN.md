# Nexus Digital Twin — OpenCV 5 Video MVP

**Status dokumen:** implementation guide untuk branch feat/opencv-vision-twin.
**Target submission internal:** 26 Oktober 2026, sebelum 23.00 WIB.
**Status proyek harus dinyatakan jujur:** video pipeline, polygon mapping, SQLite twin state, evidence frames, deterministic agent trace, dan UI telah ditambahkan ke branch. Eksekusi tes/CI, kalibrasi data ground truth, AWS deployment publik, dan submission Devpost masih perlu diverifikasi secara nyata.

## 1. Tujuan MVP

Nexus Digital Twin mengubah satu video uji yang diizinkan menjadi pengamatan visual terstruktur per zona. OpenCV 5 membaca video, mengambil sampel frame, menjalankan detector, memetakan objek ke polygon zona, menghitung jumlah deteksi, dan memperbarui state digital twin. Policy agent memeriksa output tersebut untuk menentukan tindakan berikutnya.

MVP tidak dimaksudkan sebagai sistem keselamatan bangunan, pengenalan identitas, atau pengendali perangkat fisik. Video diproses secara batch setelah diunggah; aplikasi belum merupakan sistem CCTV live.

## 2. Alur yang sudah diimplementasikan

~~~text
Video unggahan
    |
    v
FastAPI: validasi tipe, ukuran, konfigurasi zona
    |
    v
OpenCV 5: decode video, sampling, resize frame
    |
    v
Detector: HOG bawaan atau YOLO COCO ONNX melalui OpenCV DNN
    |
    v
Anchor bounding box -> polygon zona -> occupancy per sampel
    |
    +----> frame bukti teranotasi
    |
    v
SQLite: job, observations, latest zone state, event
    |
    v
Policy agent:
  get_zone_state
  -> analyze_next_window
  -> compare_snapshots jika ambang tetap terlampaui
  -> draft_ticket atau request_human_review
    |
    v
Dashboard: state, frame bukti, histori, trace, human review
~~~

Policy loop bersifat deterministik. Ia tidak meminta LLM menyusun keputusan, dan tidak menjalankan aksi eksternal. Nilai evidence yang berbeda dapat menghasilkan keputusan yang berbeda: tidak ada ambang terlampaui menghasilkan no-action, sedangkan indikasi berulang dapat menghasilkan draf tiket yang menunggu persetujuan.

## 3. Runtime OpenCV 5

Dependency Python mem-pin paket OpenCV contrib headless ke versi 5.0.0.93. Konfigurasi runtime secara default menolak job video jika major version yang dilaporkan bukan 5. Keberadaan paket dalam requirements tidak membuktikan bahwa instalasi, build, atau pipeline telah berhasil diuji; verifikasi melalui endpoint dan output lokal harus tetap dilakukan.

~~~bash
python --version
python -c "import cv2; print('OpenCV:', cv2.__version__); print(bool(cv2.getBuildInformation()))"
~~~

Endpoint verifikasi terautentikasi:

~~~bash
curl http://127.0.0.1:8000/api/vision/opencv-version \
  -H "X-API-Key: $DINUSNEXUS_API_KEY"
~~~

Jika versi bukan 5.x, periksa interpreter dan virtual environment yang aktif, lalu instal ulang requirements. Jangan melaporkan OpenCV 4 sebagai OpenCV 5.

## 4. Detector dan konfigurasi model

### Baseline HOG

Bila VISION_MODEL_PATH kosong, detector menggunakan OpenCV HOG pedestrian detector. Tidak dibutuhkan file bobot eksternal. Ini baseline yang mudah direproduksi, tetapi dapat melewatkan objek atau menghasilkan false positives pada sudut pandang, ukuran orang, occlusion, pencahayaan, dan kualitas video tertentu.

### Model YOLO ONNX opsional

Pipeline juga mendukung model YOLOv5/YOLOv8 COCO ONNX yang output-nya sesuai parser saat ini. Letakkan model di filesystem runtime, periksa lisensi dan kompatibilitas, lalu atur variabel environment:

~~~dotenv
VISION_MODEL_PATH=/absolute/path/to/model.onnx
VISION_CONFIDENCE_THRESHOLD=0.25
~~~

Parser saat ini mengharapkan layout output umum dengan 84 atau 85 feature per prediksi. Tidak ada proses pengunduhan model otomatis. Simpan nama/versi model, lisensi, SHA-256 model, confidence threshold, input size, konfigurasi NMS, versi OpenCV, dan hasil smoke test sebelum menjadikan model tersebut model evaluasi.

Skor YOLO belum merupakan probabilitas occupancy terkalibrasi. Baseline HOG tidak mengembalikan confidence probabilistik. Jangan membuat confidence summary dari hitungan orang saja.

## 5. Video, polygon zona, dan state twin

### Batas input

- Format: MP4, MOV, AVI, WebM, MPEG.
- Batas upload: 50 MiB.
- Batas durasi: 300 detik.
- Maksimum 60 frame sampel per job.
- Interval sampling pilihan pengguna: 1–30 detik, dinaikkan otomatis bila perlu agar sesuai batas sampel.
- Sisi frame yang diproses: maksimum 1280 piksel.
- File video input ditulis ke file temporer selama pemrosesan dan dihapus pada akhir request.

Pipeline mencatat SHA-256 input, metadata video, versi OpenCV, detector, konfigurasi zona, frame yang diproses, dan waktu pemrosesan.

### Polygon zona

Endpoint GET /api/vision/zones menyediakan dua polygon DEMO yang membagi frame ke kiri dan kanan. Polygon dinyatakan dalam koordinat ternormalisasi 0–1; ini koordinat relatif terhadap gambar/video, bukan koordinat geografis atau geometri bangunan OSM.

Operator dapat mengubah JSON pada halaman /workspace/vision-twin. Setiap konfigurasi memiliki 1–4 zona dengan:
- zone_id unik berisi huruf, angka, underscore, atau hyphen;
- nama zona;
- polygon 3–20 titik;
- occupancy_threshold integer 1–1000.

Anchor deteksi adalah tengah-bawah bounding box. Objek dimasukkan ke zona pertama yang mengandung anchor. Kamera yang diarahkan pada perspektif berbeda perlu kalibrasi polygon baru. Polygon default hanya memudahkan demonstrasi end-to-end dan tidak boleh diklaim sebagai peta kampus yang terkalibrasi.

### State yang disimpan

Database SQLite yang dikendalikan VISION_TWIN_DB_PATH menyimpan jobs, observations per zona/frame, latest zone state, events, agent runs/steps, dan tickets. Frame JPEG bukti disimpan di VISION_ARTIFACT_DIR. Docker Compose memetakan direktori artifacts ke volume bernama agar state/frame tidak hilang saat container diganti.

Status zona yang dikembalikan dapat berupa normal, review, atau stale. Nilai stale diturunkan ketika observasi terlalu lama dibanding VISION_STATE_STALE_SECONDS; status ini menunjukkan data lama, bukan bahwa area fisik pasti kosong atau bermasalah.

## 6. Policy agent dan persetujuan manusia

Untuk setiap zona, agent membaca state terbaru dan mencari sampel pertama yang mencapai ambang.

- Bila tidak ada sampel yang mencapai ambang, trace mencatat policy_no_action.
- Bila ada trigger, agent memeriksa jendela sampel sesudahnya melalui analyze_next_window.
- Bila ambang tidak lagi terlampaui atau tidak ada sampel lanjutan, event menunggu human review. Agent tidak menganggap kondisi sementara sebagai fakta yang sudah dikonfirmasi.
- Bila sampel lanjutan masih melampaui ambang, agent mencatat compare_snapshots dan menyusun draf tiket berstatus pending_approval.
- Petugas dapat approve atau reject draf melalui UI. API hanya menyimpan keputusan demo dan tidak menghubungi ticketing eksternal atau mengubah fasilitas.

Trace menyimpan input, output, timestamp, tool yang dipilih, dan alasan operasional. Ini execution trace yang bisa diaudit; bukan chain-of-thought privat. Setiap run terhubung dengan job/event dan data sumbernya.

## 7. API utama

Semua endpoint Vision Twin dilindungi autentikasi workspace yang sama: bearer session atau X-API-Key demo.

| Method | Endpoint | Tujuan |
|---|---|---|
| GET | /api/vision/opencv-version | Memeriksa versi runtime |
| GET | /api/vision/zones | Mengambil konfigurasi polygon awal |
| POST | /api/vision/videos | Memproses video, menyimpan state, dan menjalankan policy |
| GET | /api/vision/jobs?limit=10 | Histori video jobs terbaru |
| GET | /api/vision/jobs/{job_id} | Summary job persisten |
| GET | /api/vision/jobs/{job_id}/frame | Mengambil frame bukti puncak |
| GET | /api/vision/jobs/{job_id}/agent-runs | Membaca trace agent |
| GET | /api/vision/twin/state | Membaca state zona terakhir |
| GET | /api/vision/events | Daftar event vision |
| GET | /api/vision/tickets | Daftar draf dan status review |
| POST | /api/vision/tickets/{ticket_id}/decision | Menyimpan approve/reject |

Contoh pemrosesan video:

~~~bash
curl -X POST http://127.0.0.1:8000/api/vision/videos \
  -H "X-API-Key: $DINUSNEXUS_API_KEY" \
  -F "file=@licensed-demo.avi" \
  -F "source_label=Hallway experiment" \
  -F "sample_interval_seconds=1"
~~~

Respons sukses berisi job_id, input hash, versi OpenCV, nama detector, metadata sumber, durasi dan FPS video, interval sampling, ringkasan occupancy per zona, event, trace agent, draf tiket, preview frame, serta daftar keterbatasan.

## 8. Menjalankan secara lokal

Dari root repository, buat environment lokal berdasarkan template lalu ubah nilai placeholder. Jangan commit .env.

~~~bash
python3 -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn src.main:app --reload
~~~

Frontend:

~~~bash
cd frontend
npm ci
npm run dev
~~~

Buka http://localhost:3000/workspace/vision-twin setelah backend dan frontend aktif. Pastikan metode autentikasi lokal dikonfigurasi. Docker Compose menggunakan POSTGRES_PASSWORD dan DINUSNEXUS_API_KEY dari file .env; ganti placeholder dengan nilai acak sebelum menjalankan, dan jangan masukkan provider keys ke frontend/browser bundle.

## 9. Pengujian dan Definition of Done lokal

Tes yang sudah ditambahkan ke repository:

~~~bash
python -m compileall -q src
python -m pytest tests/test_vision_api.py tests/test_twin_video.py
python -m pytest
cd frontend
npx tsc --noEmit
npm run test -- --run
npm run build
~~~

Test fixtures video membuat klip AVI kecil secara sintetik; detector dimock untuk membuktikan pipeline routing/state/trace, bukan untuk mengukur akurasi HOG/YOLO. Jalankan juga manual smoke test dengan video berizin yang menampilkan orang dan inspeksi output anotasi.

Sebelum merge, catat hasil aktual dari:
- versi Python dan OpenCV serta build information;
- CI workflow, pytest, TypeScript, unit tests, dan production build;
- format/durasi/resolusi/checksum input video;
- model/detector dan polygon yang digunakan;
- job ID, frame bukti, zone state, event, trace agent, ticket approval;
- kasus gagal: video rusak, versi OpenCV salah, polygon invalid, video terlalu besar, tidak ada deteksi, dan event yang tidak terulang.

Tidak ada hasil akurasi, latency, task success rate, biaya cloud, atau uptime yang boleh diisi sebelum benar-benar dihitung. Test berisi mock tidak menjadi bukti akurasi model.

## 10. Evaluasi yang harus dilakukan

Gunakan klip berizin dan ground truth anotasi manual. Mulai dari tiga kasus: zona normal, threshold terlampaui secara berulang, dan trigger yang tidak persisten. Tambahkan satu kasus video invalid atau evidence tidak cukup.

| Area | Metrik | Catatan |
|---|---|---|
| Detektor | precision/recall/F1 | Definisikan aturan matching box dan anotasi ground truth |
| Occupancy | MAE count per sampel/zona | Bandingkan count hasil dengan count manual di zona yang sama |
| Event | precision/recall dan false positive | Cocokkan event dengan label event per zona/time window |
| Runtime | latency tiap job, p50/p95 jika sampel memadai | Rekam hardware, input duration, FPS, sampling, warm-up |
| Agent | jumlah keputusan benar, task success, tool calls, error rate | Tetapkan expected decisions sebelum menguji |
| Robustness | video rusak, gelap, blur, occlusion, zone mismatch | Simpan kasus buruk dan keterbatasan |
| AWS | smoke-test berhasil, build/deployment identifier | Jangan mengklaim uptime dari satu sesi demo |

Simpan data mentah ke CSV/JSON, plus checksum input, SHA commit, konfigurasi, versi library/model, output anotasi, agent trace, perintah pengujian, dan error logs. Jangan hanya menyimpan screenshot grafik.

## 11. AWS deployment — belum diverifikasi

Komponen vision/API harus berjalan pada AWS saat submission; men-deploy frontend saja tidak memenuhi maksud ini. Prosedur deployment yang disarankan untuk MVP adalah satu EC2 dengan Docker Compose.

1. Pilih region dan instance hemat yang telah diuji; catat instance type dan commit SHA.
2. Batasi Security Group: SSH hanya untuk IP admin, HTTP/HTTPS sesuai kebutuhan demo, dan database tidak dibuka publik.
3. Install Docker dan Docker Compose sesuai panduan OS yang dipilih.
4. Clone branch/release yang ditetapkan. Buat .env di host dari secret lokal; jangan embed AWS credentials atau API key ke image.
5. Isi POSTGRES_PASSWORD dan DINUSNEXUS_API_KEY dengan nilai acak; set CORS_ORIGINS dan NEXT_PUBLIC_API_BASE_URL sesuai endpoint demo.
6. Jalankan docker compose config, kemudian docker compose up -d --build.
7. Verifikasi docker compose ps, logs, GET /health, GET /api/vision/opencv-version, state/tickets, dan video demo di endpoint publik. Gunakan HTTPS ketika menerima kredensial pada endpoint internet.
8. Jalankan skenario video yang sama pada AWS; simpan timestamp, region, instance type, container/image ID, commit, log smoke test, dan bukti dashboard.
9. Review biaya billing aktual dan stop resource yang tidak dibutuhkan. Pastikan disk/IP/storage yang tetap ditagih dipahami.

**Status:** kode konfigurasi Compose sudah menambahkan volume persistensi state/frame dan menghilangkan kredensial demo yang sebelumnya tertanam. Deployment AWS, konfigurasi endpoint publik, smoke test dari luar, serta biaya aktual belum diverifikasi melalui implementasi ini.

## 12. Timeline submission internal: 15–26 Oktober 2026

| Tanggal | Prioritas | Hasil yang harus diselesaikan |
|---|---|---|
| 15 Okt | Scope/environment | Repository, OpenCV 5 gate, data uji berizin |
| 16 Okt | Video baseline | Video reader, metadata, smoke test |
| 17 Okt | Detector | HOG/ONNX dan frame anotasi |
| 18 Okt | Spatial mapping | Polygon, occupancy per zona, event |
| 19 Okt | Persistent state/API | SQLite state, events/jobs, failure handling |
| 20 Okt | Dashboard | State, frame evidence, history |
| 21 Okt | Agent loop | Trace, different decisions, human approval |
| 22 Okt | AWS | API/vision pipeline berjalan di AWS |
| 23 Okt | Integrasi/failure | End-to-end dan path gagal |
| 24 Okt | Evaluasi | Ground truth, baseline, metrik dan raw data |
| 25 Okt | Report/video | Technical report, diagram, video demo maksimal 5 menit |
| 26 Okt | Freeze/submission | Freeze fitur, smoke test clean, audit secrets, submit sebelum 23.00 WIB |

Periksa ulang halaman resmi Devpost sebelum submission karena perubahan deadline/rubrik dapat terjadi: https://opencv26.devpost.com/ dan https://opencv26.devpost.com/rules. Target internal lebih awal daripada waktu resmi konservatif pada dokumen perencanaan.

## 13. Acceptance gate sebelum mengirim submission

- [x] Implementasi dasar video upload, OpenCV 5 version gate, zona polygon, state SQLite, event, agent trace, serta draft ticket review telah ditambahkan ke branch.
- [x] Repository menambahkan tes untuk alur state/decision dan endpoint.
- [ ] CI/test/type-check/build lulus dan hasil aktual tercatat.
- [ ] OpenCV 5 benar-benar terverifikasi pada environment bersih.
- [ ] Video dengan izin diproses dari upload hingga bukti zona; hasil diperiksa manual.
- [ ] Ground truth, baseline, metrik, dan kasus gagal dihitung serta disimpan.
- [ ] AWS menjalankan pipeline vision, bukan hanya frontend; endpoint eksternal dapat diverifikasi.
- [ ] Technical report, arsitektur, video maksimal 5 menit, reproduksi, lisensi, privasi, dan keamanan lengkap.
- [ ] Tidak ada secrets, data tanpa izin, atau klaim yang belum terbukti.
- [ ] Submission final tersimpan di Devpost dan statusnya diverifikasi.

Terakhir ditinjau: 15 Oktober 2026. Kotak checklist belum dicentang hanya berdasarkan rencana atau keberadaan source code; centang setelah ada bukti run yang nyata.
