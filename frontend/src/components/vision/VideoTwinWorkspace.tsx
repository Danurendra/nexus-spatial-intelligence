'use client';

import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Clock3, Film, RefreshCw, ScanLine, ShieldCheck, Users, Workflow, XCircle } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';

type ZoneSummary = { zone_id: string; name: string; occupancy_count: number; peak_count: number; occupancy_threshold: number; triggered: boolean; status: string };
type AgentStep = { step_id: string; order: number; tool: string; status: string; inputs: Record<string, unknown>; output: Record<string, unknown>; reason: string; timestamp: string };
type AgentRun = { run_id: string; job_id: string; event_id: string | null; status: string; decision: string; steps: AgentStep[] };
type VisionEvent = { event_id: string; job_id: string; zone_id: string; occupancy_peak: number; occupancy_threshold: number; status: string; details?: Record<string, unknown>; created_at: string };
type VisionTicket = { ticket_id: string; event_id: string; job_id: string; zone_id: string; summary: string; recommended_action: string; status: string; created_at: string; reviewed_at?: string | null; reviewer_label?: string | null; review_note?: string | null };
type VersionCheck = { opencv_version: string; required_major: number | null; compatible: boolean; message: string };
type JobListItem = { job_id: string; status: string; source_label: string; original_filename: string; opencv_version: string; detector: string | null; created_at: string; finished_at?: string | null; sampled_frames: number; error_code?: string | null; error_message?: string | null };
type VisionJobResult = { status: string; job_id: string; source_type: string; data_label: string; opencv_version: string; detector: string; source_label: string; original_filename: string; input_sha256: string; duration_seconds: number; source_fps: number; source_width: number; source_height: number; sample_interval_seconds: number; sampled_frames: number; zone_summary: ZoneSummary[]; events: VisionEvent[]; agent_runs: AgentRun[]; tickets: VisionTicket[]; preview_frame_url: string; duration_processing_seconds?: number; limitations: string[] };

const DEFAULT_ZONES = [
  { zone_id: 'corridor-a', name: 'Koridor A', polygon_normalized: [[0.03, 0.08], [0.49, 0.08], [0.49, 0.97], [0.03, 0.97]], occupancy_threshold: 3 },
  { zone_id: 'corridor-b', name: 'Koridor B', polygon_normalized: [[0.51, 0.08], [0.97, 0.08], [0.97, 0.97], [0.51, 0.97]], occupancy_threshold: 3 },
];

function responseError(body: any): string {
  if (typeof body?.detail === 'string') return body.detail;
  if (typeof body?.detail?.message === 'string') return body.detail.message;
  return 'Permintaan gagal diproses.';
}
function formatTime(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
function decisionLabel(value: string): string {
  const labels: Record<string, string> = { no_action: 'Tidak perlu tindakan', human_review_required: 'Perlu tinjauan manusia', draft_ticket_pending_approval: 'Draf tiket menunggu persetujuan' };
  return labels[value] ?? value.replace(/_/g, ' ');
}
function statusVariant(value: string): 'success' | 'warning' | 'error' | 'info' | 'secondary' {
  if (['normal', 'completed', 'approved'].includes(value)) return 'success';
  if (['review', 'pending_review', 'ticket_draft', 'pending_approval', 'processing'].includes(value)) return 'warning';
  if (['failed', 'rejected', 'stale'].includes(value)) return 'error';
  return 'info';
}

export function VideoTwinWorkspace() {
  const [file, setFile] = useState<File | null>(null);
  const [sourceLabel, setSourceLabel] = useState('Uploaded demo video');
  const [sampleInterval, setSampleInterval] = useState('1');
  const [zonesJson, setZonesJson] = useState(JSON.stringify(DEFAULT_ZONES, null, 2));
  const [job, setJob] = useState<VisionJobResult | null>(null);
  const [version, setVersion] = useState<VersionCheck | null>(null);
  const [zoneState, setZoneState] = useState<any[]>([]);
  const [events, setEvents] = useState<VisionEvent[]>([]);
  const [tickets, setTickets] = useState<VisionTicket[]>([]);
  const [recentJobs, setRecentJobs] = useState<JobListItem[]>([]);
  const [frameUrl, setFrameUrl] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [busyTicket, setBusyTicket] = useState('');
  const [loadingPage, setLoadingPage] = useState(true);
  const [configError, setConfigError] = useState('');

  const fetchJson = useCallback(async (path: string) => {
    const response = await apiFetch(path);
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new Error(responseError(body));
    return body;
  }, []);

  const refreshState = useCallback(async () => {
    const values = await Promise.all([
      fetchJson('/api/vision/twin/state'),
      fetchJson('/api/vision/events?limit=25'),
      fetchJson('/api/vision/tickets?limit=25'),
      fetchJson('/api/vision/jobs?limit=10'),
    ]);
    setZoneState(values[0].zones ?? []);
    setEvents(values[1].events ?? []);
    setTickets(values[2].tickets ?? []);
    setRecentJobs(values[3].jobs ?? []);
  }, [fetchJson]);

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoadingPage(true);
      try {
        const values = await Promise.all([fetchJson('/api/vision/opencv-version'), fetchJson('/api/vision/zones')]);
        if (!alive) return;
        setVersion(values[0]);
        if (Array.isArray(values[1].zones)) setZonesJson(JSON.stringify(values[1].zones, null, 2));
        await refreshState();
      } catch (cause) {
        if (alive) setError(cause instanceof Error ? cause.message : 'Tidak dapat memuat Vision Twin API.');
      } finally {
        if (alive) setLoadingPage(false);
      }
    }
    void load();
    return () => { alive = false; };
  }, [fetchJson, refreshState]);

  useEffect(() => () => { if (frameUrl) URL.revokeObjectURL(frameUrl); }, [frameUrl]);

  const pendingTickets = useMemo(() => tickets.filter((ticket) => ticket.status === 'pending_approval'), [tickets]);
  const activeEvents = useMemo(() => events.filter((event) => ['pending_review', 'ticket_draft', 'observed'].includes(event.status)), [events]);

  async function showJobFrame(jobId: string, fallbackPath?: string) {
    const response = await apiFetch(fallbackPath || ('/api/vision/jobs/' + jobId + '/frame'));
    if (!response.ok) return;
    const nextUrl = URL.createObjectURL(await response.blob());
    setFrameUrl((old) => { if (old) URL.revokeObjectURL(old); return nextUrl; });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setConfigError('');
    if (!file) { setError('Pilih video terlebih dahulu.'); return; }
    if (file.size > 50 * 1024 * 1024) { setError('Ukuran video maksimal 50 MiB.'); return; }
    let zones: unknown;
    try {
      zones = JSON.parse(zonesJson);
      if (!Array.isArray(zones) || zones.length < 1 || zones.length > 4) throw new Error('Konfigurasi harus berisi 1–4 zona.');
    } catch (cause) {
      setConfigError(cause instanceof Error ? cause.message : 'JSON zona tidak valid.');
      return;
    }
    setBusy(true);
    setJob(null);
    if (frameUrl) { URL.revokeObjectURL(frameUrl); setFrameUrl(''); }
    const form = new FormData();
    form.append('file', file);
    form.append('source_label', sourceLabel.trim() || 'Uploaded demo video');
    form.append('zones_json', JSON.stringify(zones));
    form.append('sample_interval_seconds', sampleInterval);
    try {
      const response = await apiFetch('/api/vision/videos', { method: 'POST', body: form });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(responseError(body));
      const result = body as VisionJobResult;
      setJob(result);
      await Promise.all([showJobFrame(result.job_id, result.preview_frame_url), refreshState()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Pemrosesan video gagal.');
    } finally { setBusy(false); }
  }

  async function loadExistingJob(jobId: string) {
    setError('');
    try {
      const saved = await fetchJson('/api/vision/jobs/' + jobId);
      if (!saved.result) throw new Error(saved.error_message || 'Job belum memiliki hasil tersimpan.');
      const merged = { ...saved.result, job_id: saved.job_id, status: saved.status, duration_processing_seconds: saved.duration_processing_seconds, preview_frame_url: saved.preview_frame_url } as VisionJobResult;
      setJob(merged);
      await Promise.all([showJobFrame(jobId, saved.preview_frame_url), refreshState()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Tidak dapat membuka job tersimpan.');
    }
  }

  async function reviewTicket(ticket: VisionTicket, decision: 'approve' | 'reject') {
    setBusyTicket(ticket.ticket_id);
    setError('');
    try {
      const response = await apiFetch('/api/vision/tickets/' + ticket.ticket_id + '/decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, reviewer_label: 'Campus operator', note: decision === 'approve' ? 'Disetujui untuk tindak lanjut manual.' : 'Ditolak setelah review manusia.' }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(responseError(body));
      await refreshState();
      if (job?.job_id === ticket.job_id) {
        setJob((current) => current ? { ...current, tickets: current.tickets.map((item) => item.ticket_id === ticket.ticket_id ? body.ticket : item) } : current);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Keputusan tiket gagal disimpan.');
    } finally { setBusyTicket(''); }
  }

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-6">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Badge variant="info">NEXUS DIGITAL TWIN</Badge>
            <Badge variant={version?.compatible ? 'success' : 'error'}>{version ? 'OpenCV ' + version.opencv_version : 'OpenCV checking…'}</Badge>
            <Badge variant="warning">UPLOADED VIDEO · NOT LIVE CCTV</Badge>
          </div>
          <h1 className="text-3xl font-semibold text-textPrimary">Vision Twin</h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-textSecondary">Proses video dengan OpenCV, petakan deteksi ke polygon zona, perbarui state twin persisten, lalu jalankan policy agent berdasarkan evidence. Semua nilai occupancy berasal dari sampel video unggahan.</p>
        </div>
        <Button variant="outline" disabled={loadingPage || busy} onClick={() => void refreshState()} icon={<RefreshCw className="h-4 w-4" />}>Refresh state</Button>
      </header>

      {version && !version.compatible && <div role="alert" className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" /><div><p className="font-semibold">OpenCV version gate belum terpenuhi</p><p className="mt-1">{version.message}. Pipeline kompetisi tidak akan melanjutkan pemrosesan dengan versi yang tidak sesuai.</p></div></div>}
      {error && <div role="alert" className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" /><span>{error}</span></div>}

      <div className="grid gap-5 xl:grid-cols-[minmax(320px,0.92fr)_minmax(0,1.45fr)]">
        <Card className="h-fit p-5">
          <div className="mb-5 flex items-center gap-3"><div className="rounded-lg bg-indigo-50 p-2 text-indigo-700"><Film className="h-5 w-5" /></div><div><h2 className="font-semibold text-textPrimary">Video input & spatial config</h2><p className="text-xs text-textSecondary">MP4, MOV, AVI, WebM, atau MPEG · maks. 50 MiB / 5 menit</p></div></div>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <label className="block"><span className="mb-1.5 block text-sm font-medium text-textPrimary">Label sumber video</span><input className="w-full rounded-md border border-border bg-white px-3 py-2.5 text-sm text-textPrimary outline-none focus:ring-2 focus:ring-primary" value={sourceLabel} onChange={(event) => setSourceLabel(event.target.value)} maxLength={100} /></label>
            <label className="block"><span className="mb-1.5 block text-sm font-medium text-textPrimary">Video demo</span><input className="w-full rounded-md border border-border bg-white px-3 py-2.5 text-sm text-textPrimary file:mr-3 file:rounded file:border-0 file:bg-indigo-50 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-indigo-700" type="file" accept="video/mp4,video/quicktime,video/x-msvideo,video/webm,video/mpeg,.mp4,.mov,.avi,.webm,.mpeg,.mpg,.m4v" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />{file && <span className="mt-1 block text-xs text-textSecondary">{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MiB</span>}</label>
            <label className="block"><span className="mb-1.5 block text-sm font-medium text-textPrimary">Interval sampling (detik)</span><select className="w-full rounded-md border border-border bg-white px-3 py-2.5 text-sm text-textPrimary" value={sampleInterval} onChange={(event) => setSampleInterval(event.target.value)}><option value="1">1 detik</option><option value="2">2 detik</option><option value="5">5 detik</option><option value="10">10 detik</option><option value="30">30 detik</option></select></label>
            <label className="block"><span className="mb-1.5 block text-sm font-medium text-textPrimary">Zona & polygon ternormalisasi (JSON)</span><textarea className="min-h-64 w-full rounded-md border border-border bg-slate-50 px-3 py-2.5 font-mono text-xs text-slate-800 outline-none focus:ring-2 focus:ring-primary" value={zonesJson} onChange={(event) => setZonesJson(event.target.value)} spellCheck={false} /><span className="mt-1 block text-xs leading-5 text-textSecondary">Tiap titik [x,y] menggunakan rentang 0–1 relatif terhadap frame. Polygon default membagi frame kiri/kanan dan hanya untuk demo; kalibrasikan sebelum evaluasi.</span></label>
            {configError && <p role="alert" className="text-sm text-red-700">{configError}</p>}
            <Button className="w-full" type="submit" disabled={busy || !file || !version?.compatible} icon={<ScanLine className="h-4 w-4" />}>{busy ? 'Memproses video & menjalankan agent…' : 'Jalankan video → digital twin'}</Button>
            <p className="text-xs leading-5 text-textSecondary">Video diproses sebagai batch. File input temporer dihapus sesudah job; frame bukti, state, event, dan trace disimpan sesuai konfigurasi lokal.</p>
          </form>
        </Card>

        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
            <Metric icon={<Users className="h-4 w-4" />} label="Zona" value={String(job?.zone_summary.length ?? zoneState.length)} detail="State terakhir tersimpan" />
            <Metric icon={<Film className="h-4 w-4" />} label="Frame sampel" value={job ? String(job.sampled_frames) : '—'} detail={job ? job.source_width + ' × ' + job.source_height + 'px' : 'Belum ada job aktif'} />
            <Metric icon={<AlertTriangle className="h-4 w-4" />} label="Event aktif" value={String(activeEvents.length)} detail="Review / tiket draft" />
            <Metric icon={<ShieldCheck className="h-4 w-4" />} label="Tiket menunggu" value={String(pendingTickets.length)} detail="Butuh keputusan manusia" />
          </div>

          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4"><div><h2 className="font-semibold text-textPrimary">Digital Twin state</h2><p className="mt-1 text-xs text-textSecondary">Status dihitung dari observasi tersimpan, bukan dekorasi.</p></div>{job && <Badge variant={statusVariant(job.status)}>{job.status.toUpperCase()}</Badge>}</div>
            <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
              {zoneState.length ? zoneState.map((zone) => <div key={zone.zone_id} className="rounded-lg border border-border p-4"><div className="flex items-start justify-between gap-2"><h3 className="text-sm font-semibold text-textPrimary">{zone.zone_name}</h3><Badge variant={statusVariant(zone.status)}>{zone.status}</Badge></div><p className="mt-3 text-3xl font-semibold tabular-nums text-textPrimary">{zone.occupancy_count}</p><p className="text-xs text-textSecondary">Orang terdeteksi pada sampel terakhir</p><div className="mt-3 flex items-center justify-between text-xs text-textSecondary"><span>Puncak: {zone.peak_count}</span><span>Ambang: {zone.occupancy_threshold}</span></div><p className="mt-2 truncate text-[11px] text-textSecondary">Teramati: {formatTime(zone.last_observed_at)}</p></div>) : <EmptyMessage text="Belum ada state zona. Jalankan video untuk membuat observasi pertama." />}
            </div>
          </Card>

          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4"><div><h2 className="font-semibold text-textPrimary">Frame evidence</h2><p className="mt-1 text-xs text-textSecondary">Frame dengan hitungan tertinggi pada video terpilih.</p></div>{job && <Badge variant="info">{job.data_label}</Badge>}</div>
            {frameUrl ? <div className="p-4"><img src={frameUrl} alt="Frame video teranotasi dengan polygon zona dan bounding box OpenCV" className="max-h-[560px] w-full rounded-lg bg-slate-950 object-contain" />{job && <div className="mt-3 grid gap-2 text-xs text-textSecondary sm:grid-cols-2"><span>Detector: {job.detector}</span><span>OpenCV: {job.opencv_version}</span><span>SHA-256: {job.input_sha256.slice(0, 20)}…</span><span>Sampling: {job.sample_interval_seconds}s · {job.sampled_frames} frame</span></div>}</div> : <div className="flex min-h-56 flex-col items-center justify-center px-6 py-8 text-center"><Film className="h-9 w-9 text-slate-400" /><p className="mt-3 font-medium text-textPrimary">Belum ada frame evidence</p><p className="mt-1 max-w-md text-sm leading-6 text-textSecondary">Setelah video diproses, panel menampilkan polygon zona, bounding box, dan hitungan frame puncak.</p></div>}
          </Card>
        </div>
      </div>

      {job && <Card className="overflow-hidden"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4"><div><h2 className="font-semibold text-textPrimary">Job result & reproducibility</h2><p className="mt-1 text-xs text-textSecondary">Sumber, versi, checksum, dan runtime.</p></div><Badge variant={statusVariant(job.status)}>{job.status}</Badge></div><div className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-4"><InfoItem label="Job ID" value={job.job_id} /><InfoItem label="Video" value={job.original_filename} /><InfoItem label="Durasi video" value={job.duration_seconds.toFixed(2) + 's · ' + job.source_fps.toFixed(2) + ' FPS'} /><InfoItem label="Waktu pemrosesan" value={job.duration_processing_seconds != null ? job.duration_processing_seconds.toFixed(2) + 's' : 'tersimpan'} /></div><div className="border-t border-border px-5 py-4"><h3 className="mb-2 text-sm font-semibold text-textPrimary">Batas interpretasi</h3><ul className="space-y-1.5 text-xs leading-5 text-textSecondary">{job.limitations.map((text) => <li key={text}>• {text}</li>)}</ul></div></Card>}

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="overflow-hidden"><div className="flex items-center gap-2 border-b border-border px-5 py-4"><Workflow className="h-4 w-4 text-indigo-600" /><div><h2 className="font-semibold text-textPrimary">Agent decision trace</h2><p className="mt-1 text-xs text-textSecondary">Input, tool, output dan alasan yang dapat diperiksa.</p></div></div><div className="space-y-4 p-5">
          {job?.agent_runs?.length ? job.agent_runs.map((run) => <div key={run.run_id} className="rounded-lg border border-border p-4"><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-semibold text-textSecondary">{run.event_id ? 'EVENT ' + run.event_id.slice(0, 8) : 'ZONE POLICY RUN'}</span><Badge variant={statusVariant(run.decision)}>{decisionLabel(run.decision)}</Badge></div><ol className="mt-3 space-y-3">{run.steps.map((step) => <li key={step.step_id} className="border-l-2 border-indigo-200 pl-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold text-textPrimary">{step.tool}</p><span className="text-[11px] text-textSecondary">{formatTime(step.timestamp)}</span></div><p className="mt-1 text-xs leading-5 text-textSecondary">{step.reason}</p><pre className="mt-2 max-h-28 overflow-auto rounded bg-slate-50 p-2 text-[10px] leading-4 text-slate-700">{JSON.stringify(step.output, null, 2)}</pre></li>)}</ol></div>) : <EmptyMessage text="Trace agent akan muncul setelah video menghasilkan state dan policy dievaluasi." />}
        </div></Card>

        <Card className="overflow-hidden"><div className="flex items-center gap-2 border-b border-border px-5 py-4"><ShieldCheck className="h-4 w-4 text-amber-600" /><div><h2 className="font-semibold text-textPrimary">Human review queue</h2><p className="mt-1 text-xs text-textSecondary">Agent hanya membuat draft; petugas menentukan tindak lanjut.</p></div></div><div className="space-y-3 p-5">
          {pendingTickets.length ? pendingTickets.map((ticket) => <div key={ticket.ticket_id} className="rounded-lg border border-amber-200 bg-amber-50/40 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><h3 className="text-sm font-semibold text-textPrimary">{ticket.zone_id}</h3><Badge variant="warning">Pending approval</Badge></div><p className="mt-2 text-sm text-textPrimary">{ticket.summary}</p><p className="mt-2 text-xs leading-5 text-textSecondary">{ticket.recommended_action}</p><p className="mt-2 text-[11px] text-textSecondary">Job {ticket.job_id.slice(0, 8)} · {formatTime(ticket.created_at)}</p><div className="mt-4 flex flex-wrap gap-2"><Button size="sm" disabled={busyTicket === ticket.ticket_id} onClick={() => void reviewTicket(ticket, 'approve')} icon={<CheckCircle2 className="h-4 w-4" />}>Approve draft</Button><Button size="sm" variant="outline" disabled={busyTicket === ticket.ticket_id} onClick={() => void reviewTicket(ticket, 'reject')} icon={<XCircle className="h-4 w-4" />}>Reject draft</Button></div><p className="mt-2 text-[11px] text-textSecondary">Keputusan dicatat di database demo; tidak ada tiket eksternal atau aksi fasilitas yang dieksekusi.</p></div>) : <EmptyMessage text="Tidak ada draft yang menunggu. Kasus yang tidak berulang diarahkan ke event review, bukan tiket otomatis." />}
        </div></Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="overflow-hidden"><div className="flex items-center gap-2 border-b border-border px-5 py-4"><TriangleAlert className="h-4 w-4 text-amber-600" /><div><h2 className="font-semibold text-textPrimary">Event history</h2><p className="mt-1 text-xs text-textSecondary">Evidence pemicu dan status approval.</p></div></div><div className="divide-y divide-border">
          {events.length ? events.map((event) => <div key={event.event_id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"><div><p className="text-sm font-medium text-textPrimary">{event.zone_id} · peak {event.occupancy_peak}/{event.occupancy_threshold}</p><p className="mt-1 text-xs text-textSecondary">{event.event_id.slice(0, 12)} · {formatTime(event.created_at)}</p></div><Badge variant={statusVariant(event.status)}>{event.status.replace(/_/g, ' ')}</Badge></div>) : <div className="p-5"><EmptyMessage text="Event muncul saat observasi video melewati ambang zona." /></div>}
        </div></Card>
        <Card className="overflow-hidden"><div className="flex items-center gap-2 border-b border-border px-5 py-4"><Clock3 className="h-4 w-4 text-indigo-600" /><div><h2 className="font-semibold text-textPrimary">Recent video jobs</h2><p className="mt-1 text-xs text-textSecondary">Job dan ringkasan tetap tersedia setelah reload.</p></div></div><div className="divide-y divide-border">
          {recentJobs.length ? recentJobs.map((item) => <div key={item.job_id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium text-textPrimary">{item.original_filename}</p><p className="mt-1 text-xs text-textSecondary">{item.job_id.slice(0, 12)} · {item.sampled_frames} frames · {formatTime(item.created_at)}</p></div><div className="flex items-center gap-2"><Badge variant={statusVariant(item.status)}>{item.status}</Badge>{item.status === 'completed' && <Button size="sm" variant="outline" onClick={() => void loadExistingJob(item.job_id)}>Load</Button>}</div></div>) : <div className="p-5"><EmptyMessage text="Belum ada job video tersimpan." /></div>}
        </div></Card>
      </div>
    </div>
  );
}

function Metric({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return <Card className="p-4"><div className="flex items-center justify-between text-textSecondary"><span className="text-xs font-medium">{label}</span>{icon}</div><p className="mt-3 text-2xl font-semibold tabular-nums text-textPrimary">{value}</p><p className="mt-1 text-xs text-textSecondary">{detail}</p></Card>;
}
function InfoItem({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 rounded-lg bg-surface p-3"><p className="text-xs text-textSecondary">{label}</p><p className="mt-1 break-all text-sm font-medium text-textPrimary">{value}</p></div>;
}
function EmptyMessage({ text }: { text: string }) {
  return <div className="rounded-lg bg-surface/70 px-4 py-5 text-center"><p className="text-sm text-textSecondary">{text}</p></div>;
}
