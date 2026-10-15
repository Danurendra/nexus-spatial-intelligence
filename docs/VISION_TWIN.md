# Vision Twin — OpenCV Frame Analysis

## Tujuan

Menambahkan jalur Computer Vision yang dapat diperlihatkan dan diuji dalam Nexus Digital Twin. MVP ini menerima satu gambar yang diunggah, mendeteksi pejalan kaki yang terlihat, lalu mengembalikan anotasi dan metadata untuk konteks zona kampus.

## Alur

1. Buka /workspace/vision-twin.
2. Pilih zona dari daftar yang ditampilkan dan isi label sumber gambar.
3. Unggah JPEG, PNG, atau WebP hingga 8 MiB.
4. Tekan **Jalankan deteksi OpenCV**.
5. UI memanggil POST /api/vision/pedestrians dengan multipart form data.
6. Backend memverifikasi autentikasi, membatasi ukuran/resolusi, mendekode gambar memakai OpenCV, menjalankan detector, dan menghasilkan JPEG beranotasi.
7. UI menampilkan jumlah deteksi, bounding boxes, ukuran frame, detector, timestamp, provenance, dan batas interpretasi.

## Detector

### Baseline default: OpenCV HOG

Jika VISION_MODEL_PATH kosong, backend memakai cv2.HOGDescriptor dengan default pedestrian SVM. Tidak ada bobot eksternal yang perlu diunduh. Ini baseline praktis agar pipeline dapat dijalankan lebih mudah, tetapi akurasinya terbatas pada sudut pandang, skala, occlusion, dan kondisi gambar.

### Model opsional: ONNX + OpenCV DNN

Untuk eksperimen dengan model lebih kuat, tempatkan ekspor COCO YOLOv8/YOLOv5 ONNX yang kompatibel di filesystem runtime, kemudian atur di file .env:

~~~dotenv
VISION_MODEL_PATH=/absolute/path/to/model.onnx
VISION_CONFIDENCE_THRESHOLD=0.25
~~~

Jangan commit model, gambar kamera, atau key ke Git. Konfigurasi ONNX yang digunakan harus dicatat dalam hasil eksperimen beserta versi OpenCV, checksum model, confidence threshold, perangkat komputasi, dan contoh uji. Perbedaan layout output ONNX dapat membuat suatu ekspor tidak kompatibel; endpoint gagal dengan pesan aman alih-alih menyatakan hasil berhasil.

## Cara menjalankan secara lokal

Backend, dari root repository:

~~~bash
python -m pip install -r requirements.txt
# Pastikan .env sudah diisi dan database backend disiapkan sesuai README.
uvicorn src.main:app --reload
~~~

Frontend, dari folder frontend/:

~~~bash
npm ci
# Set NEXT_PUBLIC_API_BASE_URL dan metode autentikasi lokal dalam .env.local.
npm run dev
~~~

Buka http://localhost:3000/workspace/vision-twin setelah masuk ke workspace. Endpoint membutuhkan sesi akun yang valid atau API key demo yang dikonfigurasi secara lokal.

## Validasi

~~~bash
python -m pytest tests/test_vision_api.py
python -m compileall -q src
cd frontend
npx tsc --noEmit
npm run test -- --run
~~~

Tes endpoint mencakup autentikasi, tipe konten, gambar invalid, payload sukses, dan batas unggahan. Jalankan juga UI manual dengan satu gambar kosong/indoor serta satu gambar outdoor yang punya izin digunakan. Review hasil deteksi secara visual; jangan menginterpretasikan test endpoint yang menggunakan detector mock sebagai bukti akurasi HOG/YOLO.

## Label data dan batas klaim

- source_type=uploaded_image dan data_label=OBSERVED_FROM_UPLOADED_IMAGE menyatakan bahwa output berasal dari satu gambar yang diunggah.
- Sistem belum tersambung ke RTSP/ONVIF, CCTV, atau feed kamera real-time.
- zone_id adalah konteks yang dipilih pengguna. Belum ada verified camera-to-building mapping pada backend.
- people_count adalah jumlah bounding box yang dikembalikan pada frame ini, bukan orang unik atau okupansi riil yang terkalibrasi.
- Gambar/output tidak dipersistenkan ke penyimpanan aplikasi, database, atau histori task pada implementasi sekarang. Parser multipart dapat memakai buffer upload temporer selama request, sehingga jangan mengirim gambar sensitif tanpa memahami kebijakan runtime.
- Modul ini belum mengubah status gedung, heatmap kepadatan, atau overlay occupancy Campus Twin.

## Backlog sebelum integrasi live

1. Tetapkan dasar legal, persetujuan, akses operator, retensi, dan penghapusan data gambar.
2. Tambahkan persisted observation records dengan provenance, timestamp, detector/model version, zone/camera mapping terverifikasi, dan audit.
3. Tambahkan jalur streaming dengan reconnect, rate-limit, health status, dan pemantauan lag.
4. Evaluasi detector pada dataset berizin dengan precision/recall, false positive, false negative, serta batas kondisi kerja.
5. Kalibrasi peta occupancy, zona pandang, ukuran frame, dan penghitungan lintas-frame; jangan menjumlahkan setiap frame menjadi orang unik.
6. Baru setelah validasi, hubungkan agregat occupancy dengan layer Campus Twin; tetap tampilkan stale-data dan source labels.

