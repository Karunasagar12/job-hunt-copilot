import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { downloadCV, fetchDueFollowups, fetchInboxDigest, fetchJobs, updateJob } from '../api.js';
import FollowUpQueue from '../components/FollowUpQueue.jsx';
import InboxDigest from '../components/InboxDigest.jsx';

export default function Today() {
  const [followups, setFollowups] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [digest, setDigest] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [pendingJobId, setPendingJobId] = useState(null);

  async function load() {
    setLoading(true); setError('');
    try {
      const [due, allJobs, digestResult] = await Promise.all([fetchDueFollowups(), fetchJobs(), fetchInboxDigest()]);
      setFollowups(Array.isArray(due) ? due : []);
      setJobs((Array.isArray(allJobs) ? allJobs : []).filter(j => j.status === 'cv_ready'));
      setDigest(digestResult);
    } catch (e) { setError(e.message || 'Failed to load.'); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  async function handleMarkApplied(jobId) {
    setPendingJobId(jobId); setError('');
    try { await updateJob(jobId, { status: 'applied' }); setJobs(cur => cur.filter(j => j.id !== jobId)); }
    catch (e) { setError(e.message || 'Failed to mark applied.'); }
    finally { setPendingJobId(null); }
  }

  async function handleDownloadCV(jobId) {
    setPendingJobId(jobId); setError('');
    try { await downloadCV(jobId); }
    catch (e) { setError(e.message || 'Failed to download CV.'); }
    finally { setPendingJobId(null); }
  }

  return (
    <div className="space-y-6">
      {error && <div className="rounded-xl border border-red-700 bg-red-900/30 p-4 text-sm text-red-400">{error}</div>}

      {loading ? (
        <div className="flex justify-center rounded-xl border border-slate-700 bg-slate-800 p-12">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400" />
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-slate-300">Follow-ups Due</h2>
              <button type="button" onClick={load}
                className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm font-medium text-slate-400 transition hover:bg-slate-700 hover:text-white">
                Refresh
              </button>
            </div>
            <FollowUpQueue followups={followups} onAction={load} />
          </section>

          <section className="space-y-4">
            <h2 className="font-semibold text-slate-300">Ready to Apply</h2>
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
              {jobs.length === 0 ? (
                <div className="rounded-lg bg-slate-700/50 p-6 text-center text-sm text-slate-500">No CVs ready.</div>
              ) : (
                <div className="divide-y divide-slate-700">
                  {jobs.map(job => (
                    <div key={job.id} className="py-4 first:pt-[0px] last:pb-0">
                      <div className="mb-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-white">{job.company || '—'}</span>
                          <span className="text-slate-400">— {job.role || '—'}</span>
                          <Link to={`/job/${job.id}`} className="text-xs font-medium text-cyan-400 hover:text-cyan-300">
                            View →
                          </Link>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {job.geography && (
                            <span className="rounded-full bg-slate-700 px-2 py-1 font-mono text-xs text-slate-300">
                              {job.geography.toUpperCase()}
                            </span>
                          )}
                          {job.ats_score != null && (
                            <span className="rounded-full bg-cyan-500/10 px-2 py-1 font-mono text-xs text-cyan-400">
                              ATS {job.ats_score}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button type="button" onClick={() => handleDownloadCV(job.id)} disabled={pendingJobId === job.id}
                          className="rounded-lg border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 transition hover:bg-slate-600 disabled:opacity-40">
                          Download CV
                        </button>
                        <button type="button" onClick={() => handleMarkApplied(job.id)} disabled={pendingJobId === job.id}
                          className="rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-40">
                          Mark Applied
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          <section className="space-y-4 lg:col-span-2">
            <h2 className="font-semibold text-slate-300">Recent Inbox Activity</h2>
            <InboxDigest digest={digest} onAction={load} />
          </section>
        </div>
      )}
    </div>
  );
}
