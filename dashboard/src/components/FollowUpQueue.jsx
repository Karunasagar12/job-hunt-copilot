import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { batchCreateDrafts, createGmailDraft, skipOutreach } from '../api.js';
import { copyToClipboard } from '../utils/clipboard.js';

function channelIcon(channel) {
  if (channel === 'email') return '✉';
  if (channel === 'linkedin_connect') return '🔗';
  if (channel === 'linkedin_dm') return '💬';
  return '•';
}

function preview(text) {
  const v = text || '';
  return v.length > 100 ? `${v.slice(0, 100)}…` : v;
}

function todayString() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function daysOverdue(scheduledDate, today) {
  const diffMs = new Date(today) - new Date(scheduledDate);
  return Math.max(1, Math.round(diffMs / 86400000));
}

function groupFollowups(followups) {
  const today = todayString();
  const overdue = [];
  const dueToday = [];
  for (const entry of followups) {
    if (entry.scheduled_date && entry.scheduled_date < today) overdue.push(entry);
    else dueToday.push(entry);
  }
  overdue.sort((a, b) => (a.scheduled_date < b.scheduled_date ? -1 : 1));
  return { overdue, dueToday };
}

function FollowUpEntry({ entry, isPending, overdueDays, onCreateDraft, onCopy, onSkip }) {
  const isEmail = entry.channel === 'email';
  const isLinkedIn = entry.channel === 'linkedin_connect' || entry.channel === 'linkedin_dm';

  return (
    <div className="py-4 first:pt-[0px] last:pb-0">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-white">{channelIcon(entry.channel)} {entry.contact_name || 'Contact'}</span>
            {overdueDays !== null && (
              <span className="rounded-full bg-red-900/40 px-2 py-0.5 font-mono text-xs text-red-300">{overdueDays}d overdue</span>
            )}
            {entry.job_id && (
              <Link to={`/job/${entry.job_id}`} className="text-xs font-medium text-cyan-400 hover:text-cyan-300">
                View Job →
              </Link>
            )}
          </div>
          <div className="mt-1 text-sm text-slate-400">
            {entry.company || '—'}{entry.role ? ` — ${entry.role}` : ''}
          </div>
        </div>
        {entry.geography && (
          <span className="rounded-full bg-slate-700 px-2 py-1 font-mono text-xs text-slate-300">{entry.geography}</span>
        )}
      </div>

      {entry.subject && <div className="mb-1 text-sm text-cyan-400">{entry.subject}</div>}
      {entry.scheduled_date && <div className="mb-2 font-mono text-xs text-slate-500">{entry.scheduled_date}</div>}
      <p className="mb-3 text-sm text-slate-400">{preview(entry.content)}</p>
      {isEmail && (
        <p className="mb-3 text-xs text-amber-400">Best sent Tue–Thu morning</p>
      )}

      <div className="flex flex-wrap gap-2">
        {isEmail && (
          <button type="button" disabled={isPending}
            onClick={onCreateDraft}
            className="rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-40">
            Create Gmail Draft
          </button>
        )}
        {(isLinkedIn || isEmail) && (
          <button type="button" onClick={onCopy}
            className="rounded-lg border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 transition hover:bg-slate-600">
            Copy
          </button>
        )}
        <button type="button" disabled={isPending}
          onClick={onSkip}
          className="rounded-lg border border-red-800 px-3 py-1.5 text-sm font-medium text-red-400 transition hover:bg-red-900/30 disabled:opacity-40">
          Skip
        </button>
      </div>
    </div>
  );
}

export default function FollowUpQueue({ followups = [], onAction }) {
  const [error, setError] = useState('');
  const [batchPending, setBatchPending] = useState(false);
  const [pendingId, setPendingId] = useState(null);

  const emailIds = useMemo(() => followups.filter(e => e.channel === 'email').map(e => e.id), [followups]);
  const { overdue, dueToday } = useMemo(() => groupFollowups(followups), [followups]);
  const today = useMemo(() => todayString(), []);

  async function copyText(text) {
    try { await copyToClipboard(text); }
    catch (e) { setError(e.message || 'Failed to copy.'); }
  }

  async function handleCreateAllDrafts() {
    setError(''); setBatchPending(true);
    try { await batchCreateDrafts(emailIds); await onAction?.(); }
    catch (e) { setError(e.message || 'Failed to create drafts.'); }
    finally { setBatchPending(false); }
  }

  async function handleAction(id, action, fallback) {
    setError(''); setPendingId(id);
    try { await action(); await onAction?.(); }
    catch (e) { setError(e.message || fallback); }
    finally { setPendingId(null); }
  }

  function renderEntry(entry, overdueDays) {
    return (
      <FollowUpEntry
        key={entry.id}
        entry={entry}
        isPending={pendingId === entry.id}
        overdueDays={overdueDays}
        onCreateDraft={() => handleAction(entry.id, () => createGmailDraft(entry.id), 'Failed to create Gmail draft.')}
        onCopy={() => copyText(entry.content)}
        onSkip={() => handleAction(entry.id, () => skipOutreach(entry.id), 'Failed to skip.')}
      />
    );
  }

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
      <div className="mb-5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-slate-300">Follow-ups</span>
          <span className="rounded-full bg-slate-700 px-2 py-0.5 font-mono text-xs text-slate-300">{followups.length}</span>
        </div>
        {emailIds.length > 0 && (
          <button type="button" onClick={handleCreateAllDrafts} disabled={batchPending}
            className="rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-40">
            {batchPending ? 'Creating…' : 'Create All Drafts'}
          </button>
        )}
      </div>

      {error && <div className="mb-4 rounded-lg border border-red-700 bg-red-900/30 p-3 text-sm text-red-400">{error}</div>}

      {followups.length === 0 ? (
        <div className="rounded-lg bg-slate-700/50 p-6 text-center text-sm text-slate-500">No follow-ups due.</div>
      ) : (
        <div className="space-y-5">
          {overdue.length > 0 && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-red-500" />
                <span className="text-xs font-semibold uppercase tracking-wide text-red-400">Overdue</span>
                <span className="rounded-full bg-red-900/40 px-2 py-0.5 font-mono text-xs text-red-300">{overdue.length}</span>
              </div>
              <div className="divide-y divide-slate-700 rounded-lg border border-red-900/40 px-4">
                {overdue.map(entry => renderEntry(entry, daysOverdue(entry.scheduled_date, today)))}
              </div>
            </section>
          )}

          {dueToday.length > 0 && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-cyan-500" />
                <span className="text-xs font-semibold uppercase tracking-wide text-cyan-400">Due Today</span>
                <span className="rounded-full bg-cyan-900/40 px-2 py-0.5 font-mono text-xs text-cyan-300">{dueToday.length}</span>
              </div>
              <div className="divide-y divide-slate-700 rounded-lg border border-slate-700 px-4">
                {dueToday.map(entry => renderEntry(entry, null))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
