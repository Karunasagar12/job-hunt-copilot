import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { deleteJob, downloadCoverLetter, downloadCV, fetchJob, updateJob } from '../api.js';
import AtsGauge from '../components/AtsGauge.jsx';
import CompanyProfile from '../components/CompanyProfile.jsx';
import ContactList from '../components/ContactList.jsx';
import CopyButton from '../components/CopyButton.jsx';
import OutreachTimeline from '../components/OutreachTimeline.jsx';
import SalaryEstimator from '../components/SalaryEstimator.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import StatusDropdown from '../components/StatusDropdown.jsx';

const TABS = ['Overview', 'Contacts', 'Outreach', 'Notes', 'Company', 'Salary'];

function PipelineStep({ label, state }) {
  const icon = state === 'done' ? '✓' : state === 'warn' ? '⚠' : '○';
  const color = state === 'done' ? 'text-green-400' : state === 'warn' ? 'text-amber-400' : 'text-slate-600';
  return (
    <div className="flex items-center gap-3">
      <span className={`w-5 text-center font-mono ${color}`}>{icon}</span>
      <span className="text-sm text-slate-300">{label}</span>
    </div>
  );
}

export default function JobDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [tab, setTab] = useState('Overview');
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [downloadingCL, setDownloadingCL] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteSaved, setNoteSaved] = useState(false);
  const mounted = useRef(true);
  const lastSavedNotes = useRef('');
  const notesLoaded = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const load = useCallback(async () => {
    let active = true;
    setLoading(true);
    try {
      const data = await fetchJob(id);
      if (!active) return;
      setJob(data); setNotes(data.notes || '');
      lastSavedNotes.current = data.notes || '';
      notesLoaded.current = true;
      setError('');
    } catch (e) { if (active) setError(e.message); }
    finally { if (active) setLoading(false); }
    return () => { active = false; };
  }, [id]);

  useEffect(() => { load(); }, [load]);
  const reload = useCallback(() => load(), [load]);

  useEffect(() => {
    if (!notesLoaded.current || tab !== 'Notes' || notes === lastSavedNotes.current) return;
    let active = true;
    setNoteSaving(true); setNoteSaved(false);
    const t = setTimeout(async () => {
      try {
        await updateJob(id, { notes });
        if (!active) return;
        lastSavedNotes.current = notes;
        setNoteSaved(true);
      } catch (e) { if (active) setError(e.message); }
      finally { if (active) setNoteSaving(false); }
    }, 500);
    return () => { active = false; clearTimeout(t); };
  }, [notes, id, tab]);

  async function handleDownload() {
    setDownloading(true); setError('');
    try { await downloadCV(id); }
    catch (e) { setError(e.message); }
    finally { setDownloading(false); }
  }

  async function handleDownloadCoverLetter() {
    setDownloadingCL(true); setError('');
    try { await downloadCoverLetter(id); }
    catch (e) { setError(e.message); }
    finally { setDownloadingCL(false); }
  }

  async function handleDelete() {
    if (!window.confirm('Delete this job and all its contacts and outreach? This cannot be undone.')) return;
    setDeleting(true);
    try { await deleteJob(job.id); navigate('/pipeline'); }
    catch (e) { setError(e.message); setDeleting(false); }
  }

  const steps = useMemo(() => {
    const score = job?.ats_score;
    return [
      { label: 'CV Generated',     state: job?.cv_path      ? 'done' : 'pending' },
      { label: 'ATS Scored',       state: score != null      ? 'done' : 'pending' },
      { label: 'ATS Passed',       state: score == null ? 'pending' : score >= 35 ? 'done' : 'warn' },
      { label: 'Cover Letter',     state: job?.cover_letter  ? 'done' : 'pending' },
      { label: 'Outreach Drafted', state: job?.outreach_raw  ? 'done' : 'pending' },
    ];
  }, [job]);

  if (loading) return (
    <div className="flex justify-center rounded-xl border border-slate-700 bg-slate-800 p-12">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400" />
    </div>
  );

  if (!job) return <div className="rounded-xl border border-red-700 bg-red-900/30 p-4 text-sm text-red-400">{error || 'Job not found'}</div>;

  return (
    <div className="space-y-6">
      {error && <div className="rounded-xl border border-red-700 bg-red-900/30 p-4 text-sm text-red-400">{error}</div>}

      {job.ats_parse_warning && (
        <div className="rounded-xl border border-amber-700 bg-amber-900/30 p-4 text-sm text-amber-400">
          <span className="font-semibold">ATS parseability warning:</span> {job.ats_parse_warning}
        </div>
      )}

      <section className="rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-2xl font-semibold tracking-tight text-white">{job.company || '—'}</h2>
              <span className="rounded-full bg-slate-700 px-2.5 py-1 font-mono text-xs uppercase text-slate-300">
                {job.geography || '—'}
              </span>
              <StatusBadge status={job.status} />
            </div>
            <p className="mt-1 text-lg text-slate-300">{job.role || '—'}</p>
            {job.applied_at && (
              <p className="mt-1 text-sm text-slate-500">
                Applied {new Date(job.applied_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </p>
            )}
          </div>
          <div className="flex items-center gap-3">
            <StatusDropdown id={job.id} status={job.status} onChange={s => setJob(j => ({ ...j, status: s }))} />
            <button type="button" onClick={handleDelete} disabled={deleting}
              className="rounded-lg border border-red-700 px-3 py-1.5 text-sm font-medium text-red-400 hover:bg-red-900/30 disabled:opacity-40">
              {deleting ? 'Deleting…' : 'Delete Job'}
            </button>
          </div>
        </div>
      </section>

      <div className="border-b border-slate-700">
        <nav className="-mb-px flex gap-6">
          {TABS.map(t => (
            <button key={t} type="button" onClick={() => setTab(t)}
              className={`border-b-2 px-1 pb-3 text-sm font-medium transition ${
                tab === t ? 'border-cyan-400 text-cyan-400' : 'border-transparent text-slate-500 hover:text-slate-300'
              }`}>
              {t}
            </button>
          ))}
        </nav>
      </div>

      {tab === 'Overview' && (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
            <section className="flex items-center justify-center rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
              <AtsGauge score={job.ats_score} />
            </section>
            <section className="rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
              <h3 className="mb-4 text-base font-semibold text-white">Pipeline Steps</h3>
              <div className="space-y-3">
                {steps.map(step => <PipelineStep key={step.label} label={step.label} state={step.state} />)}
              </div>
            </section>
          </div>

          <section className="rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-base font-semibold text-white">Cover Letter</h3>
              <div className="flex items-center gap-2">
                <CopyButton text={job.cover_letter || ''} />
                {job.cover_letter && (
                  <button type="button" onClick={handleDownloadCoverLetter} disabled={downloadingCL}
                    className="rounded-lg border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 transition hover:bg-slate-600 hover:text-white disabled:opacity-40">
                    {downloadingCL ? 'Downloading…' : 'Download PDF'}
                  </button>
                )}
              </div>
            </div>
            <div className="max-h-80 overflow-y-auto whitespace-pre-wrap rounded-lg border border-slate-700 bg-slate-900 p-4 text-sm leading-6 text-slate-300">
              {job.cover_letter || 'Not yet generated.'}
            </div>
          </section>

          <button type="button" onClick={handleDownload} disabled={downloading}
            className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 shadow-sm transition hover:bg-cyan-400 disabled:opacity-40">
            {downloading ? 'Downloading…' : 'Download CV'}
          </button>
        </div>
      )}

      {tab === 'Contacts' && (
        <ContactList jobId={job.id} contacts={job.contacts || []}
          onContactsChange={updated => setJob(j => ({ ...j, contacts: updated }))} />
      )}

      {tab === 'Outreach' && (
        <OutreachTimeline jobId={job.id} contacts={job.contacts || []}
          outreachEntries={(job.contacts || []).flatMap(c => c.outreach_entries || [])}
          onOutreachChange={reload}
          onOpenContacts={() => setTab('Contacts')} />
      )}

      {tab === 'Notes' && (
        <section className="rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-base font-semibold text-white">Notes</h3>
            <span className="text-sm text-slate-500">{noteSaving ? 'Saving…' : noteSaved ? 'Saved' : ''}</span>
          </div>
          <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={10}
            placeholder="Notes about this opportunity…"
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-4 py-3 text-sm leading-6 text-slate-300 outline-none placeholder:text-slate-600 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500" />
        </section>
      )}

      {tab === 'Company' && (
        <CompanyProfile jobId={job.id} />
      )}

      {tab === 'Salary' && (
        <SalaryEstimator jobId={job.id} />
      )}
    </div>
  );
}
