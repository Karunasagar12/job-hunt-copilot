import { useState } from 'react';
import { Link } from 'react-router-dom';
import { confirmCascade, dismissDigestContact, dismissDigestMessages, fetchDigestThread, updateJob } from '../api.js';
import { checkOutreachStatus, dismissUncertainOutreach, retryOutreach } from '../api.js'; // Task 11 `uncertain` bucket actions

function CollapsedSection({ label, colorClass, count, items, renderItem }) {
  const [open, setOpen] = useState(false);
  if (count === 0) return null;
  return (
    <section>
      <button type="button" onClick={() => setOpen(o => !o)} className="flex w-full items-center gap-2 text-left">
        <span className="text-xs text-slate-500">{open ? '▾' : '▸'}</span>
        <span className={`text-xs font-semibold uppercase tracking-wide ${colorClass}`}>{label}</span>
        <span className="rounded-full bg-slate-700 px-2 py-0.5 font-mono text-xs text-slate-300">{count}</span>
      </button>
      {open && (
        <div className="mt-2 divide-y divide-slate-700 rounded-lg border border-slate-700 px-4">
          {items.map(renderItem)}
        </div>
      )}
    </section>
  );
}

function ThreadView({ messages }) {
  if (!messages.length) return <div className="mt-2 text-xs text-slate-500">No messages found.</div>;
  return (
    <div className="mt-3 space-y-2 rounded-lg bg-slate-900/50 p-3">
      {messages.map(m => (
        <div key={m.message_id} className="text-xs">
          <div className="text-slate-400">{m.from || m.classification}{m.date ? ` — ${m.date}` : ''}</div>
          {m.body && <div className="mt-1 whitespace-pre-wrap text-slate-300">{m.body}</div>}
        </div>
      ))}
    </div>
  );
}

function ReplyCard({ entry, onAction }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [thread, setThread] = useState(null);
  const [threadLoading, setThreadLoading] = useState(false);

  async function handleViewThread() {
    if (thread) { setThread(null); return; }
    setThreadLoading(true); setError('');
    try {
      const result = await fetchDigestThread(entry.contact_id);
      setThread(result.messages || []);
    } catch (e) { setError(e.message || 'Failed to load thread.'); }
    finally { setThreadLoading(false); }
  }

  async function handleConfirmCascade() {
    setPending(true); setError('');
    try { await confirmCascade(entry.contact_id); await onAction?.(); }
    catch (e) { setError(e.message || 'Failed to confirm cascade.'); }
    finally { setPending(false); }
  }

  async function handleDismiss() {
    setPending(true); setError('');
    try { await dismissDigestContact(entry.contact_id); await onAction?.(); }
    catch (e) { setError(e.message || 'Failed to dismiss.'); }
    finally { setPending(false); }
  }

  return (
    <div className="py-4 first:pt-[0px] last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-white">{entry.contact_name}</span>
        <span className="rounded-full bg-slate-700 px-2 py-0.5 font-mono text-xs text-slate-300">
          {entry.message_count} msg{entry.message_count === 1 ? '' : 's'}
        </span>
        <Link to={`/job/${entry.job_id}`} className="text-xs font-medium text-cyan-400 hover:text-cyan-300">
          {entry.company} — {entry.role} →
        </Link>
        <button type="button" onClick={handleViewThread} disabled={threadLoading}
          className="ml-auto rounded-lg border border-slate-600 px-3 py-1.5 text-sm font-medium text-slate-300 transition hover:bg-slate-700 disabled:opacity-40">
          {threadLoading ? 'Loading…' : thread ? 'Hide thread' : 'View thread'}
        </button>
        <button type="button" onClick={handleDismiss} disabled={pending}
          className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm font-medium text-slate-400 transition hover:bg-slate-700 disabled:opacity-40">
          Dismiss
        </button>
      </div>
      {entry.cascade_pending && (
        <button type="button" disabled={pending} onClick={handleConfirmCascade}
          className="mt-2 rounded-lg border border-amber-700 px-3 py-1.5 text-sm font-medium text-amber-400 transition hover:bg-amber-900/30 disabled:opacity-40">
          Also pause outreach to other contacts on this job?
        </button>
      )}
      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}
      {thread && <ThreadView messages={thread} />}
    </div>
  );
}

function BucketRow({ m, onDismiss, right, pendingId }) {
  return (
    <div className="flex flex-wrap items-center gap-2 py-3 first:pt-[0px] last:pb-0">
      <span className="font-medium text-white">{m.contact_name}</span>
      <Link to={`/job/${m.job_id}`} className="text-xs font-medium text-cyan-400 hover:text-cyan-300">
        {m.company} — {m.role} →
      </Link>
      {right}
      <button type="button" disabled={pendingId === m.message_id} onClick={() => onDismiss(m.message_id)}
        className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm font-medium text-slate-400 transition hover:bg-slate-700 disabled:opacity-40">
        Dismiss
      </button>
    </div>
  );
}

function UncertainRow({ item, onAction, pendingId, setPendingId, setError }) {
  const isPending = pendingId === item.id;
  const sequencePosition = { 1: 1, 4: 2, 5: 3 }[item.sequence_num] || item.sequence_num;

  async function handleCheck() {
    setPendingId(item.id);
    setError('');
    try { await checkOutreachStatus(item.id); await onAction?.(); }
    catch (e) { setError(e.message || 'Check failed.'); }
    finally { setPendingId(null); }
  }

  async function handleDismiss() {
    setPendingId(item.id);
    setError('');
    try { await dismissUncertainOutreach(item.id); await onAction?.(); }
    catch (e) { setError(e.message || 'Dismiss failed.'); }
    finally { setPendingId(null); }
  }

  async function handleRetry() {
    setPendingId(item.id);
    setError('');
    try { await retryOutreach(item.id); await onAction?.(); }
    catch (e) { setError(e.message || 'Retry failed.'); }
    finally { setPendingId(null); }
  }

  return (
    <div className="flex items-center justify-between gap-2 py-2 text-sm">
      <span>{item.contact_name} ({item.company}) — Email {sequencePosition} — {item.status}</span>
      <div className="flex gap-2">
        {item.status === 'uncertain' && (
          <button type="button" disabled={isPending} onClick={handleCheck}
            className="rounded-lg border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60">
            Check status
          </button>
        )}
        {item.status === 'failed' && (
          <button type="button" disabled={isPending} onClick={handleRetry}
            className="rounded-lg border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60">
            Retry
          </button>
        )}
        <button type="button" disabled={isPending} onClick={handleDismiss}
          className="rounded-lg border border-gray-300 px-2 py-1 text-xs font-medium text-gray-500 hover:bg-gray-50 disabled:opacity-60">
          Dismiss
        </button>
      </div>
    </div>
  );
}

export default function InboxDigest({ digest, onAction }) {
  const [pendingId, setPendingId] = useState(null);
  const [error, setError] = useState('');
  const replies = digest?.replies || [];
  const bounced = digest?.bounced || { count: 0, items: [] };
  const rejected = digest?.rejected || { count: 0, items: [] };
  const ooo = digest?.ooo || { count: 0, items: [] };
  const uncertain = digest?.uncertain || { count: 0, items: [] };
  const totalCount = replies.length + bounced.count + rejected.count + ooo.count + uncertain.count;

  async function handleMarkRejected(jobId) {
    setError(''); setPendingId(`job-${jobId}`);
    try { await updateJob(jobId, { status: 'rejected' }); await onAction?.(); }
    catch (e) { setError(e.message || 'Failed to mark job rejected.'); }
    finally { setPendingId(null); }
  }

  async function handleDismissOne(messageId) {
    setError(''); setPendingId(messageId);
    try { await dismissDigestMessages([messageId]); await onAction?.(); }
    catch (e) { setError(e.message || 'Failed to dismiss.'); }
    finally { setPendingId(null); }
  }

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
      <div className="mb-5 flex items-center gap-2">
        <span className="font-semibold text-slate-300">Recent Inbox Activity</span>
        <span className="rounded-full bg-slate-700 px-2 py-0.5 font-mono text-xs text-slate-300">{totalCount}</span>
      </div>

      {error && <div className="mb-4 rounded-lg border border-red-700 bg-red-900/30 p-3 text-sm text-red-400">{error}</div>}

      {totalCount === 0 ? (
        <div className="rounded-lg bg-slate-700/50 p-6 text-center text-sm text-slate-500">Nothing new.</div>
      ) : (
        <div className="space-y-5">
          {replies.length > 0 && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-cyan-500" />
                <span className="text-xs font-semibold uppercase tracking-wide text-cyan-400">Replies</span>
                <span className="rounded-full bg-cyan-900/40 px-2 py-0.5 font-mono text-xs text-cyan-300">{replies.length}</span>
              </div>
              <div className="divide-y divide-slate-700 rounded-lg border border-slate-700 px-4">
                {replies.map(entry => <ReplyCard key={entry.contact_id} entry={entry} onAction={onAction} />)}
              </div>
            </section>
          )}

          <CollapsedSection label="Rejected" colorClass="text-red-400" count={rejected.count} items={rejected.items}
            renderItem={m => (
              <BucketRow key={m.message_id} m={m} onDismiss={handleDismissOne} pendingId={pendingId} right={
                <button type="button" disabled={pendingId === `job-${m.job_id}`} onClick={() => handleMarkRejected(m.job_id)}
                  className="ml-auto rounded-lg border border-red-700 px-3 py-1.5 text-sm font-medium text-red-400 transition hover:bg-red-900/30 disabled:opacity-40">
                  Mark job rejected
                </button>
              } />
            )} />

          <CollapsedSection label="Out-of-office" colorClass="text-amber-400" count={ooo.count} items={ooo.items}
            renderItem={m => (
              <BucketRow key={m.message_id} m={m} onDismiss={handleDismissOne} pendingId={pendingId} right={
                <span className="ml-auto text-sm text-slate-400">
                  {m.extracted_date ? `Back ${m.extracted_date} — next touchpoint rescheduled.` : 'No return date found — check manually.'}
                </span>
              } />
            )} />

          <CollapsedSection label="Bounced" colorClass="text-slate-400" count={bounced.count} items={bounced.items}
            renderItem={m => (
              <BucketRow key={m.message_id} m={m} onDismiss={handleDismissOne} pendingId={pendingId} right={
                <span className="ml-auto text-sm text-slate-400">Email bounced — outreach cancelled.</span>
              } />
            )} />

          <div>
            <CollapsedSection label="Uncertain sends" colorClass="text-orange-500" count={uncertain.count} items={uncertain.items}
              renderItem={item => (
                <UncertainRow key={item.id} item={item} onAction={onAction} pendingId={pendingId} setPendingId={setPendingId} setError={setError} />
              )} />
            {uncertain.count > 0 && (
              <p className="mt-1 text-xs text-gray-400">
                "Check status" re-sends the original request under its original idempotency key — safe if AgentMail already has a record of it, but if the original request never reached AgentMail at all, checking can itself send the email for the first time.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
