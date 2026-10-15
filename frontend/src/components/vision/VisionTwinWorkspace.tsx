'use client';

import { useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { AlertTriangle, ArrowRight, Camera, CheckCircle2, ImagePlus, ScanLine, ShieldCheck, Users } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';

type Detection = { x: number; y: number; width: number; height: number; label: string };
type VisionResult = {
  status: string; source_type: string; data_label: string; zone_id: string; camera_label: string;
  detector: string; processed_at: string; frame_width: number; frame_height: number;
  people_count: number; detections: Detection[]; annotated_image: string; limitations: string[];
};

const zones = [
  { id: 'zone-A1', label: 'Laboratorium Komputer 1 · Gedung Akademik' },
  { id: 'zone-A2', label: 'Laboratorium Komputer 2 · Gedung Akademik' },
  { id: 'zone-A3', label: 'Ruang Kelas 1 · Gedung Akademik' },
  { id: 'zone-A4', label: 'Ruang Kelas 2 · Gedung Akademik' },
  { id: 'zone-B1', label: 'Ruang Kelas Ekonomi 1 · Gedung Admissions' },
  { id: 'zone-C1', label: 'Laboratorium Jaringan · Gedung Finance' },
  { id: 'zone-C6', label: 'Ruang Server · Gedung Finance' },
  { id: 'zone-D1', label: 'Ruang Kelas Hukum 1' },
];

export function VisionTwinWorkspace() {
  const [file, setFile] = useState<File | null>(null);
  const [zoneId, setZoneId] = useState('zone-A1');
  const [cameraLabel, setCameraLabel] = useState('Uploaded frame');
  const [result, setResult] = useState<VisionResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [previewUrl, setPreviewUrl] = useState('');

  const formattedTime = useMemo(
    () => result?.processed_at ? new Date(result.processed_at).toLocaleString() : '',
    [result?.processed_at],
  );

  function handleFile(nextFile?: File) {
    setResult(null);
    setError('');
    setFile(nextFile ?? null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(nextFile ? URL.createObjectURL(nextFile) : '');
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError('Pilih gambar terlebih dahulu.');
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setError('Ukuran gambar maksimal 8 MiB.');
      return;
    }
    setBusy(true);
    setError('');
    setResult(null);
    const form = new FormData();
    form.append('file', file);
    form.append('zone_id', zoneId);
    form.append('camera_label', cameraLabel.trim() || 'Uploaded frame');
    try {
      const response = await apiFetch('/api/vision/pedestrians', { method: 'POST', body: form });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const detail = typeof body?.detail === 'string' ? body.detail : 'Analisis gambar gagal.';
        throw new Error(detail);
      }
      setResult((await response.json()) as VisionResult);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Tidak dapat menghubungi backend Vision Twin.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Badge variant="success">OPENCV PIPELINE</Badge>
            <Badge variant="warning">UPLOADED IMAGE · NOT LIVE CCTV</Badge>
          </div>
          <h1 className="text-3xl font-semibold text-textPrimary">Vision Twin</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-textSecondary">
            Analisis satu frame kamera untuk mendeteksi pejalan kaki dan memberi konteks zona pada Campus Twin.
            Hasil diproses backend dengan OpenCV; bukan estimasi simulasi atau feed CCTV live.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-border bg-white px-3 py-2 text-xs text-textSecondary">
          <ShieldCheck className="h-4 w-4 text-green-600" />
          <span>Unggahan diproses sementara; gambar tidak disimpan oleh endpoint ini.</span>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(320px,0.85fr)_minmax(0,1.5fr)]">
        <Card className="h-fit p-5">
          <div className="mb-5 flex items-center gap-3">
            <div className="rounded-lg bg-indigo-50 p-2 text-indigo-700"><Camera className="h-5 w-5" /></div>
            <div>
              <h2 className="font-semibold text-textPrimary">Frame input</h2>
              <p className="text-xs text-textSecondary">JPEG, PNG, atau WebP · maksimum 8 MiB</p>
            </div>
          </div>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-textPrimary">Zona kampus</span>
              <select className="w-full rounded-md border border-border bg-white px-3 py-2.5 text-sm text-textPrimary outline-none focus:ring-2 focus:ring-primary"
                value={zoneId} onChange={(event) => setZoneId(event.target.value)}>
                {zones.map((zone) => <option key={zone.id} value={zone.id}>{zone.label}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-textPrimary">Label sumber gambar</span>
              <input className="w-full rounded-md border border-border bg-white px-3 py-2.5 text-sm text-textPrimary outline-none focus:ring-2 focus:ring-primary"
                value={cameraLabel} onChange={(event) => setCameraLabel(event.target.value)} maxLength={80}
                placeholder="Contoh: Kamera koridor utara" />
            </label>
            <label className="flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-border bg-surface/60 px-4 py-6 text-center transition hover:border-primary hover:bg-primary/5">
              <ImagePlus className="mb-3 h-8 w-8 text-indigo-600" />
              <span className="text-sm font-semibold text-textPrimary">{file?.name ?? 'Pilih gambar dari perangkat'}</span>
              <span className="mt-1 text-xs text-textSecondary">
                {file ? (file.size / 1024 / 1024).toFixed(2) + ' MiB' : 'Gunakan gambar uji yang Anda punya izin untuk proses'}
              </span>
              <input className="sr-only" type="file" accept="image/jpeg,image/png,image/webp"
                onChange={(event) => handleFile(event.target.files?.[0])} />
            </label>
            {previewUrl && (
              <div className="overflow-hidden rounded-lg border border-border bg-slate-950">
                {/* Local preview only; the file is sent after the user starts analysis. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={previewUrl} alt="Pratinjau frame sebelum analisis" className="max-h-64 w-full object-contain" />
              </div>
            )}
            {error && (
              <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><span>{error}</span>
              </div>
            )}
            <Button className="w-full" type="submit" disabled={busy || !file} icon={<ScanLine className="h-4 w-4" />}>
              {busy ? 'Menganalisis frame…' : 'Jalankan deteksi OpenCV'}
            </Button>
            <p className="text-xs leading-5 text-textSecondary">
              Privasi: file hanya dikirim saat tombol dijalankan. Gunakan gambar yang tidak berisi data sensitif dan punya izin pemrosesan.
            </p>
          </form>
        </Card>

        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric title="Pejalan kaki terdeteksi" value={result ? String(result.people_count) : '—'} detail="Satu frame unggahan" icon={<Users className="h-4 w-4" />} />
            <Metric title="Zona terkait" value={result?.zone_id ?? zoneId} detail="Konteks yang dipilih user" icon={<Camera className="h-4 w-4" />} />
            <Metric title="Status analisis" value={result ? 'Selesai' : busy ? 'Berjalan' : 'Menunggu'} detail={result ? result.detector : 'Belum ada hasil'} icon={<ScanLine className="h-4 w-4" />} />
          </div>
          <Card className="min-h-[360px] overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
              <div>
                <h2 className="font-semibold text-textPrimary">Hasil visual</h2>
                <p className="mt-1 text-xs text-textSecondary">Bounding box berasal dari output detector OpenCV.</p>
              </div>
              {result && <Badge variant="success"><CheckCircle2 className="mr-1 inline h-3 w-3" /> ANALYZED</Badge>}
            </div>
            {result ? (
              <div className="space-y-4 p-4 sm:p-5">
                <div className="overflow-hidden rounded-lg bg-slate-950">
                  {/* The backend returns a JPEG data URL produced by OpenCV. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={result.annotated_image} alt="Gambar hasil deteksi dengan bounding box" className="max-h-[580px] w-full object-contain" />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-lg bg-surface p-3">
                    <p className="text-xs font-medium uppercase tracking-wide text-textSecondary">Sumber & waktu</p>
                    <p className="mt-1 font-medium text-textPrimary">{result.camera_label}</p>
                    <p className="mt-1 text-xs text-textSecondary">{formattedTime}</p>
                    <p className="mt-1 text-xs text-textSecondary">{result.frame_width} × {result.frame_height} px</p>
                  </div>
                  <div className="rounded-lg bg-surface p-3">
                    <p className="text-xs font-medium uppercase tracking-wide text-textSecondary">Provenance</p>
                    <p className="mt-1 font-medium text-textPrimary">{result.data_label}</p>
                    <p className="mt-1 text-xs text-textSecondary">Zona: {result.zone_id} · Detector: {result.detector}</p>
                  </div>
                </div>
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-textPrimary">Batas interpretasi</h3>
                  <ul className="space-y-1.5 text-xs leading-5 text-textSecondary">
                    {result.limitations.map((item) => <li key={item} className="flex gap-2"><span>•</span><span>{item}</span></li>)}
                  </ul>
                </div>
              </div>
            ) : (
              <div className="flex min-h-[300px] flex-col items-center justify-center px-6 py-10 text-center">
                <div className="rounded-full bg-slate-100 p-4"><ScanLine className="h-8 w-8 text-slate-500" /></div>
                <h3 className="mt-4 font-semibold text-textPrimary">Belum ada hasil frame</h3>
                <p className="mt-2 max-w-md text-sm leading-6 text-textSecondary">
                  Pilih gambar dan zona, lalu jalankan deteksi. Output akan menampilkan jumlah orang yang terdeteksi,
                  bounding box, nama detector, dan waktu pemrosesan.
                </p>
              </div>
            )}
          </Card>
          <div className="flex flex-col gap-3 rounded-lg border border-indigo-100 bg-indigo-50/70 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-indigo-700" />
              <div>
                <p className="text-sm font-semibold text-indigo-950">Langkah integrasi berikutnya</p>
                <p className="mt-1 text-xs leading-5 text-indigo-900/80">
                  Simpan setiap frame sebagai observation bertimestamp, lalu hubungkan agregat terkalibrasi ke layer occupancy
                  Campus Twin setelah skema persistence dan kebijakan retensi ditentukan.
                </p>
              </div>
            </div>
            <Badge variant="secondary">NOT YET PERSISTED</Badge>
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({ title, value, detail, icon }: { title: string; value: string; detail: string; icon: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2 text-textSecondary">
        <span className="text-xs font-medium">{title}</span>{icon}
      </div>
      <p className="mt-3 break-words text-2xl font-semibold text-textPrimary">{value}</p>
      <p className="mt-1 text-xs text-textSecondary">{detail}</p>
    </Card>
  );
}
