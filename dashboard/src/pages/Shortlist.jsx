import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  approveSourcedJob, fetchLatestSourcingRun, fetchSourcedJobs, passSourcedJob, pollJobStatus,
} from '../api.js';

const GEOS = [['', 'All'], ['gcc', 'GCC'], ['eu', 'EU']];
const PASS_REASONS = [
  ['wrong_seniority', 'Wrong seniority'], ['wrong_domain', 'Wrong domain'], ['wrong_location', 'Wrong location'],
  ['company', 'Company'], ['language', 'Language'], ['other', 'Other'],
];
const JOB_STATE = {
  new: ['Queued', 'text-slate-300'], generating: ['Generating…', 'text-blue-300'],
  cv_ready: ['Ready', 'text-cyan-300'], failed: ['Failed', 'text-red-400'],
};
const LANGUAGE_RE = /\b(language|fluent|german|arabic|french|spanish|dutch|italian)\b/i;

function postedAge(dateStr) {
  if (!dateStr) return '';
  const plain = /^\d{4}-\d{2}-\d{2}$/.test(dateStr);
  const t = new Date(plain ? `${dateStr}T00:00:00Z` : dateStr).getTime();
  if (Number.isNaN(t)) return '';
  const days = Math.floor((Date.now() - t) / 86400000);
  return days <= 0 ? 'today' : `${days}d ago`;
}

function RunHeader({ run }) {
  if (!run) return <p className="text-sm text-slate-500">No sourcing run yet.</p>;
  const locs = run.locations || [];
  const sum = k => locs.reduce((n, l) => n + (l[k] || 0), 0);
  const bad = locs.filter(l => l.status !== 'ok');
  const when = run.started_at ? new Date(`${run.started_at.replace(' ', 'T')}Z`).toLocaleString() : '—';
  const outcome = run.finished_at ? run.outcome : 'running / interrupted';
  const tone = outcome === 'success' ? 'text-slate-400' : 'text-amber-300';
  return (
    <div className={`text-sm ${tone}`}>
      Last run: {when} · {outcome} · {sum('scraped')} scraped · {sum('new')} new · ${Number(run.total_usd || 0).toFixed(3)}
      {bad.length > 0 && (
        <div className="mt-1 text-xs">{bad.map(l => `${l.location}: ${l.status}`).join(' · ')}</div>
      )}
    </div>
  );
}

function JobCard({ job, onApprove, onPass, busy }) {
  const [open, setOpen] = useState(false);
  const [passing, setPassing] = useState(false);
  const language = job.concerns.some(c => LANGUAGE_RE.test(c));
  const state = job.approved ? (JOB_STATE[job.job_status] || ['Approved', 'text-slate-300']) : null;
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-semibold text-white">{job.title}</div>
          <div className="mt-0.5 text-sm text-slate-400">
            {job.company || '—'} · {job.location || '—'} · {postedAge(job.posted_at)}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {job.is_agency === 1 && (
              <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-300">Agency</span>
            )}
            {language && (
              <span className="rounded-full border border-purple-500/40 bg-purple-500/10 px-2 py-0.5 text-xs text-purple-300">Language</span>
            )}
            <span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 font-mono text-xs uppercase text-slate-400">{job.geo}</span>
          </div>
        </div>
        <div className="shrink-0 text-right font-mono text-2xl font-bold text-cyan-400">
          {job.fit_score ?? '—'}
        </div>
      </div>

      <p className="mt-3 text-sm text-slate-300">{job.reasons[0] || job.concerns[0] || ''}</p>
      {job.concerns.length > 0 && job.reasons.length > 0 && (
        <p className="mt-1 text-xs text-slate-500">Concerns: {job.concerns.join('; ')}</p>
      )}

      {open && (
        <div className="mt-3 space-y-2 border-t border-slate-700 pt-3 text-sm text-slate-300">
          {job.reasons.length > 1 && <ul className="list-disc pl-5">{job.reasons.map(r => <li key={r}>{r}</li>)}</ul>}
          <a href={job.url} target="_blank" rel="noreferrer" className="text-cyan-400 hover:text-cyan-300">View on LinkedIn ↗</a>
          <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap font-sans text-xs text-slate-400">{job.jd_text}</pre>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => setOpen(o => !o)} className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700">
          {open ? 'Hide' : 'Details'}
        </button>
        {job.dispatch_failed ? (
          <>
            <span className="text-sm text-amber-300">Generation didn't start</span>
            <button type="button" disabled={busy} onClick={() => onApprove(job.id)}
              className="rounded-lg border border-amber-500/40 px-3 py-1.5 text-sm text-amber-300 hover:bg-amber-500/10 disabled:opacity-50">
              Retry
            </button>
          </>
        ) : state ? (
          <span className={`text-sm ${state[1]}`}>
            {state[0]}{job.job_id && <> · <Link to={`/job/${job.job_id}`} className="text-cyan-400 hover:text-cyan-300">open job</Link></>}
          </span>
        ) : passing ? (
          <>
            {PASS_REASONS.map(([value, label]) => (
              <button key={value} type="button" disabled={busy} onClick={() => onPass(job.id, value)}
                className="rounded-full border border-slate-600 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-700 disabled:opacity-50">
                {label}
              </button>
            ))}
            <button type="button" disabled={busy} onClick={() => onPass(job.id, null)}
              className="rounded-full px-2.5 py-1 text-xs text-slate-400 hover:text-white disabled:opacity-50">Skip reason</button>
          </>
        ) : (
          <>
            <button type="button" disabled={busy} onClick={() => onApprove(job.id)}
              className="rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-50">
              Approve
            </button>
            <button type="button" disabled={busy} onClick={() => setPassing(true)}
              className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700 disabled:opacity-50">
              Pass
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function Shortlist() {
  const [geo, setGeo] = useState('');
  const [jobs, setJobs] = useState([]);
  const [run, setRun] = useState(null);
  const [other, setOther] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError('');
      const [list, latest] = await Promise.all([fetchSourcedJobs({ status: 'new', geo }), fetchLatestSourcingRun()]);
      setJobs(list);
      setRun(latest);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load shortlist.');
    } finally {
      setLoading(false);
    }
  }, [geo]);

  useEffect(() => { load(); setOther(null); }, [load]);

  // Poll approved cards' job status until generation settles.
  useEffect(() => {
    const pending = jobs.filter(j => j.approved && j.job_id && !['cv_ready', 'failed'].includes(j.job_status));
    if (pending.length === 0) return undefined;
    const id = setInterval(async () => {
      const updates = await Promise.all(pending.map(j => pollJobStatus(j.job_id).then(s => [j.id, s.status]).catch(() => null)));
      setJobs(prev => prev.map(j => {
        const hit = updates.find(u => u && u[0] === j.id);
        return hit ? { ...j, job_status: hit[1] } : j;
      }));
    }, 5000);
    return () => clearInterval(id);
  }, [jobs]);

  async function handleApprove(id) {
    setBusyId(id);
    setError('');
    try {
      const { job_id: jobId, created, dispatch_failed: dispatchFailed } = await approveSourcedJob(id);
      setJobs(prev => prev.map(j => (j.id === id ? {
        ...j, approved: true, job_id: jobId, dispatch_failed: dispatchFailed,
        job_status: created || j.dispatch_failed ? 'new' : null,
      } : j)));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Approve failed.');
      load();
    } finally {
      setBusyId(null);
    }
  }

  async function handlePass(id, reason) {
    setBusyId(id);
    setError('');
    try {
      await passSourcedJob(id, reason);
      setJobs(prev => prev.filter(j => j.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Pass failed.');
      load();
    } finally {
      setBusyId(null);
    }
  }

  async function toggleOther() {
    if (other) { setOther(null); return; }
    try { setOther(await fetchSourcedJobs({ status: 'filtered,passed', geo })); } catch { setOther([]); }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Shortlist</h1>
        <div className="mt-1"><RunHeader run={run} /></div>
      </div>

      <div className="flex gap-2">
        {GEOS.map(([value, label]) => (
          <button key={label} type="button" onClick={() => setGeo(value)}
            className={`rounded-lg px-3 py-1.5 text-sm ${geo === value ? 'bg-cyan-500/20 text-cyan-300' : 'text-slate-400 hover:bg-slate-800'}`}>
            {label}
          </button>
        ))}
      </div>

      {error && <div className="rounded-lg border border-red-700 bg-red-900/30 px-4 py-3 text-sm text-red-400">{error}</div>}

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="rounded-xl border border-slate-700 bg-slate-800 px-4 py-10 text-center text-slate-500">
          Nothing waiting for review.
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map(job => (
            <JobCard key={job.id} job={job} busy={busyId === job.id} onApprove={handleApprove} onPass={handlePass} />
          ))}
        </div>
      )}

      <div>
        <button type="button" onClick={toggleOther} className="text-sm text-slate-400 hover:text-white">
          {other ? 'Hide filtered & passed' : 'Show filtered & passed'}
          {other && ` (${other.length})`}
        </button>
        {other && (
          <ul className="mt-3 divide-y divide-slate-800 rounded-xl border border-slate-700 bg-slate-900 text-sm">
            {other.map(j => (
              <li key={j.id} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2">
                <a href={j.url} target="_blank" rel="noreferrer" className="text-slate-300 hover:text-cyan-300">
                  {j.title} · <span className="text-slate-500">{j.company}</span>
                </a>
                <span className="font-mono text-xs text-slate-500">{j.status === 'passed' ? `passed: ${j.pass_reason || '—'}` : j.filter_reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
