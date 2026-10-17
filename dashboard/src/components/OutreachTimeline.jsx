import { useEffect, useMemo, useState } from 'react';
import {
  bounceContact,
  createGmailDraft,
  editOutreach,
  markOutreachSent,
  markReplied,
  redraftOutreach,
  retryOutreach,
  skipContactOutreach,
  skipOutreach,
  startOutreach,
} from '../api.js';
import { copyToClipboard } from '../utils/clipboard.js';
import ReviewSendDrawer from './ReviewSendDrawer.jsx';
import LinkedInConnectPanel from './LinkedInConnectPanel.jsx';
import { noteText } from '../utils/linkedin.js';

function channelIcon(channel) {
  if (channel === 'email') return '✉';
  if (channel === 'linkedin_connect') return '🔗';
  if (channel === 'linkedin_dm') return '💬';
  return '•';
}

function formatContactType(value) {
  if (!value) return 'Contact';
  const lower = value.toLowerCase();
  if (lower === 'hr') return 'HR';
  if (lower === 'hiring_manager') return 'Hiring Manager';
  if (lower === 'agency') return 'Agency';
  return value.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function StatusBadge({ status }) {
  if (status === 'gmail_draft') return <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">In Gmail</span>;
  if (status === 'sent') return <span className="rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">Sent</span>;
  if (status === 'sending') return <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">Sending…</span>;
  if (status === 'uncertain') return <span className="rounded-full bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-700">Uncertain</span>;
  if (status === 'failed') return <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">Failed</span>;
  if (status === 'skipped') return <span className="text-xs font-medium text-gray-400 line-through">Skipped</span>;
  if (status === 'ready') return <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">Ready</span>;
  return <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">Draft</span>;
}

export default function OutreachTimeline({ jobId, contacts = [], outreachEntries = [], onOutreachChange, onOpenContacts }) {
  const [entries, setEntries] = useState(outreachEntries);
  const [starting, setStarting] = useState(false);
  const [pendingId, setPendingId] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editingId, setEditingId] = useState(null);
  const [editValues, setEditValues] = useState({ subject: '', content: '' });
  const [redraftingId, setRedraftingId] = useState(null);
  const [redraftFeedback, setRedraftFeedback] = useState('');
  const [redraftPending, setRedraftPending] = useState(false);
  const [reviewingEntry, setReviewingEntry] = useState(null);

  useEffect(() => { setEntries(outreachEntries || []); }, [outreachEntries]);

  const contactEntryIds = useMemo(() => {
    const map = new Map();
    contacts.forEach(c => {
      map.set(c.id, new Set((c.outreach_entries || []).map(e => e.id)));
    });
    return map;
  }, [contacts]);

  function entriesForContact(contact) {
    const ids = contactEntryIds.get(contact.id);
    return entries.filter(e => e.contact_id === contact.id || (ids && ids.has(e.id)));
  }

  async function copyText(text) {
    try { await copyToClipboard(text); }
    catch (e) { setError(e.message || 'Failed to copy.'); }
  }

  async function handleStartOutreach() {
    setError(''); setStarting(true);
    try { await startOutreach(jobId); await onOutreachChange?.(); }
    catch (e) { setError(e.message || 'Failed to start outreach.'); }
    finally { setStarting(false); }
  }

  async function updateEntryOptimistically(id, patch, request) {
    const prev = entries;
    setError(''); setPendingId(id);
    setEntries(cur => cur.map(e => e.id === id ? { ...e, ...patch } : e));
    try { await request(); await onOutreachChange?.(); return true; }
    catch (e) {
      // Roll back, then refetch: a 409 usually means the row changed
      // server-side (e.g. skipped by a reply/bounce), so prev is stale too.
      setEntries(prev); setError(e.message || 'Action failed.'); onOutreachChange?.(); return false;
    }
    finally { setPendingId(null); }
  }

  async function handleSaveEdit(entry) {
    const data = { subject: editValues.subject, content: editValues.content };
    const saved = await updateEntryOptimistically(entry.id, data, () => editOutreach(entry.id, data));
    if (saved) setEditingId(null);
  }

  async function handleRedraft(entry) {
    setError(''); setRedraftPending(true);
    try {
      const updated = await redraftOutreach(entry.id, redraftFeedback);
      // Reset status to 'draft' so "Create Gmail Draft" reappears with the new content
      setEntries(cur => cur.map(e =>
        e.id === entry.id ? { ...e, status: 'draft', subject: updated.subject, content: updated.content } : e
      ));
      setRedraftingId(null);
      setRedraftFeedback('');
      await onOutreachChange?.();
    } catch (e) { setError(e.message || 'Redraft failed.'); }
    finally { setRedraftPending(false); }
  }

  async function handleMarkReplied(contactId) {
    setError(''); setNotice(''); setPendingId(`replied-${contactId}`);
    try {
      const result = await markReplied(contactId);
      if (result.cascaded && result.cascaded.length > 0) {
        setNotice(`Also paused outreach to ${result.cascaded.length} other contact(s) on this job.`);
      }
      await onOutreachChange?.();
    }
    catch (e) { setError(e.message || 'Failed to mark replied.'); }
    finally { setPendingId(null); }
  }

  async function handleBounce(contactId) {
    setError(''); setNotice(''); setPendingId(`bounced-${contactId}`);
    try { await bounceContact(contactId); await onOutreachChange?.(); }
    catch (e) { setError(e.message || 'Failed to mark bounced.'); }
    finally { setPendingId(null); }
  }

  async function handleSkipContact(contactId) {
    setError(''); setNotice(''); setPendingId(`skip-${contactId}`);
    try { await skipContactOutreach(contactId); await onOutreachChange?.(); }
    catch (e) { setError(e.message || 'Failed to skip contact.'); }
    finally { setPendingId(null); }
  }

  async function handleRetry(entry) {
    setError(''); setPendingId(entry.id);
    try { await retryOutreach(entry.id); await onOutreachChange?.(); }
    catch (e) { setError(e.message || 'Retry failed.'); }
    finally { setPendingId(null); }
  }

  function openEdit(entry) {
    setRedraftingId(null);
    setRedraftFeedback('');
    setEditingId(entry.id);
    setEditValues({ subject: entry.subject || '', content: entry.content || '' });
  }

  function toggleRedraft(entry) {
    setEditingId(null);
    if (redraftingId === entry.id) {
      setRedraftingId(null);
      setRedraftFeedback('');
    } else {
      setRedraftingId(entry.id);
      setRedraftFeedback('');
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-lg font-semibold text-gray-950">Outreach</h3>
          {entries.length > 0 && (
            <p className="mt-1 text-sm text-gray-500">{entries.length} touchpoints across {contacts.length} contacts</p>
          )}
        </div>
        {entries.length === 0 && (
          <button type="button" onClick={handleStartOutreach} disabled={starting}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60">
            {starting && <span className="h-4 w-4 animate-spin rounded-full border-2 border-gray-200 border-t-indigo-600" />}
            Start Outreach
          </button>
        )}
      </div>

      {error && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
      {notice && <div className="mb-4 rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-700">{notice}</div>}

      {entries.length > 0 && (
        <div className="space-y-6">
          {contacts.map(contact => {
            const grouped = entriesForContact(contact).map(e => ({ ...e, contact_email: contact.email }));
            const email1Sent = grouped.some(e => e.channel === 'email' && e.sequence_num === 1 && e.status === 'sent');
            return (
              <div key={contact.id} className="rounded-lg border border-gray-200">
                <div className="flex flex-col gap-3 border-b border-gray-200 bg-gray-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="font-medium text-gray-950">{contact.name || 'Unnamed'}</h4>
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
                      {formatContactType(contact.contact_type)}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {contact.replied === 0 && (
                      <button type="button" onClick={() => handleMarkReplied(contact.id)}
                        disabled={pendingId === `replied-${contact.id}`}
                        className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60">
                        {pendingId === `replied-${contact.id}` && <span className="h-4 w-4 animate-spin rounded-full border-2 border-gray-200 border-t-indigo-600" />}
                        Mark Replied
                      </button>
                    )}
                    {contact.email_status !== 'bounced' && (
                      <button type="button" onClick={() => handleBounce(contact.id)}
                        disabled={pendingId === `bounced-${contact.id}`}
                        className="inline-flex items-center gap-2 rounded-lg border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60">
                        {pendingId === `bounced-${contact.id}` && <span className="h-4 w-4 animate-spin rounded-full border-2 border-red-200 border-t-red-700" />}
                        Bounced
                      </button>
                    )}
                    <button type="button" onClick={() => handleSkipContact(contact.id)}
                      disabled={pendingId === `skip-${contact.id}`}
                      className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60">
                      {pendingId === `skip-${contact.id}` && <span className="h-4 w-4 animate-spin rounded-full border-2 border-gray-200 border-t-indigo-600" />}
                      Skip
                    </button>
                  </div>
                </div>

                <div className="divide-y divide-gray-200">
                  {grouped.map(entry => {
                    const isEmail = entry.channel === 'email';
                    const isLinkedIn = entry.channel === 'linkedin_connect' || entry.channel === 'linkedin_dm';
                    const isConnect = entry.channel === 'linkedin_connect';
                    const isEditing = editingId === entry.id;
                    const isRedrafting = redraftingId === entry.id;
                    const isPending = pendingId === entry.id;

                    return (
                      <div key={entry.id} className={`p-4 ${entry.status === 'skipped' ? 'opacity-50' : ''}`}>
                        <div className="flex flex-wrap items-start gap-3">
                          <span className="text-lg">{channelIcon(entry.channel)}</span>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2 text-sm">
                              <span className="font-medium text-gray-900">
                                {entry.sequence_label || `Touchpoint ${entry.sequence_num || ''}`}
                              </span>
                              <span className="text-gray-400">{entry.scheduled_date || 'Unscheduled'}</span>
                              <StatusBadge status={entry.status} />
                            </div>
                            {entry.subject && <p className="mt-1 truncate text-sm font-medium text-gray-900">{entry.subject}</p>}
                            <p className={`mt-1 text-sm text-gray-600 ${isConnect ? 'whitespace-pre-wrap' : 'line-clamp-2'}`}>
                              {entry.content || 'No content'}
                            </p>
                            {isConnect && (
                              <LinkedInConnectPanel
                                entry={entry}
                                contact={contact}
                                email1Sent={email1Sent}
                                pending={isPending}
                                onMarkSent={() => updateEntryOptimistically(
                                  entry.id,
                                  { status: 'sent', sent_at: new Date().toISOString() },
                                  () => markOutreachSent(entry.id),
                                )}
                                onAddProfile={() => onOpenContacts?.()}
                              />
                            )}
                            {isEmail && entry.status !== 'sent' && entry.status !== 'skipped' && (
                              <p className="mt-1 text-xs text-amber-600">Best sent Tue–Thu morning</p>
                            )}
                          </div>
                          {/* Connect rows keep only Edit/Copy here -- narrow enough to sit beside
                              the note on phones and squeeze it, so force them onto their own line. */}
                          <div className={`flex flex-wrap gap-2 ${isConnect ? 'w-full sm:w-auto' : ''}`}>
                            {isEmail && entry.status === 'draft' && entry.provider === 'agentmail' && (
                              <button type="button" onClick={() => setReviewingEntry(entry)}
                                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">
                                Review and Send
                              </button>
                            )}
                            {isEmail && entry.status === 'draft' && entry.provider !== 'agentmail' && (
                              <button type="button" disabled={isPending}
                                onClick={() => updateEntryOptimistically(entry.id, { status: 'gmail_draft' }, () => createGmailDraft(entry.id))}
                                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60">
                                Create Gmail Draft
                              </button>
                            )}
                            {isEmail && entry.status === 'failed' && entry.provider === 'agentmail' && (
                              <button type="button" disabled={isPending}
                                onClick={() => handleRetry(entry)}
                                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60">
                                Retry
                              </button>
                            )}
                            {isEmail && (entry.status === 'draft' || entry.status === 'gmail_draft') && (
                              <button type="button" disabled={redraftPending}
                                onClick={() => toggleRedraft(entry)}
                                className="rounded-lg bg-amber-500 px-3 py-1.5 text-sm font-medium text-slate-950 hover:bg-amber-400 disabled:opacity-60">
                                Re-draft
                              </button>
                            )}
                            {isEmail && (entry.status === 'gmail_draft' || entry.status === 'draft') && entry.provider !== 'agentmail' && (
                              <button type="button" disabled={isPending}
                                onClick={() => updateEntryOptimistically(entry.id, { status: 'sent' }, () => markOutreachSent(entry.id))}
                                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60">
                                Mark Sent
                              </button>
                            )}
                            {isEmail && entry.status !== 'sent' && entry.status !== 'skipped' &&
                              (entry.provider !== 'agentmail' || entry.status === 'draft') && (
                              <button type="button" disabled={isPending}
                                onClick={() => updateEntryOptimistically(entry.id, { status: 'skipped' }, () => skipOutreach(entry.id))}
                                className="rounded-lg border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60">
                                Skip
                              </button>
                            )}
                            {((isEmail && (entry.provider !== 'agentmail' || entry.status === 'draft')) || (isConnect && entry.status === 'draft')) && (
                              <button type="button" onClick={() => isEditing ? setEditingId(null) : openEdit(entry)}
                                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
                                {isEditing ? 'Cancel' : 'Edit'}
                              </button>
                            )}
                            {(isLinkedIn || isEmail) && (
                              <button type="button" onClick={() => copyText(entry.content)}
                                disabled={isConnect && !noteText(entry.content)}
                                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60">
                                Copy
                              </button>
                            )}
                          </div>
                        </div>

                        {isRedrafting && isEmail && (
                          <div className="mt-4 space-y-3">
                            <label className="block text-sm font-medium text-gray-700">
                              Optional feedback for the LLM (leave blank to just regenerate):
                            </label>
                            <textarea value={redraftFeedback} rows={3}
                              placeholder="e.g. Make the opening line more specific to their background. Cut the last paragraph."
                              onChange={e => setRedraftFeedback(e.target.value)}
                              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500" />
                            <div className="flex gap-2">
                              <button type="button" disabled={redraftPending} onClick={() => handleRedraft(entry)}
                                className="inline-flex items-center gap-2 rounded-lg bg-amber-500 px-3 py-1.5 text-sm font-medium text-slate-950 hover:bg-amber-400 disabled:opacity-60">
                                {redraftPending && <span className="h-4 w-4 animate-spin rounded-full border-2 border-amber-200 border-t-slate-950" />}
                                Regenerate
                              </button>
                              <button type="button" onClick={() => { setRedraftingId(null); setRedraftFeedback(''); }}
                                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}

                        {isEditing && (
                          <div className="mt-4 space-y-3">
                            {isEmail && (
                              <input type="text" value={editValues.subject} placeholder="Subject"
                                onChange={e => setEditValues(v => ({ ...v, subject: e.target.value }))}
                                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500" />
                            )}
                            <textarea value={editValues.content} rows={5} placeholder="Content"
                              onChange={e => setEditValues(v => ({ ...v, content: e.target.value }))}
                              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500" />
                            <div className="flex gap-2">
                              <button type="button" disabled={isPending} onClick={() => handleSaveEdit(entry)}
                                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60">
                                {isPending && <span className="h-4 w-4 animate-spin rounded-full border-2 border-gray-200 border-t-indigo-600" />}
                                Save
                              </button>
                              <button type="button" onClick={() => setEditingId(null)}
                                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {reviewingEntry && (
        <ReviewSendDrawer
          entry={reviewingEntry}
          onClose={() => setReviewingEntry(null)}
          onSent={() => onOutreachChange?.()}
          onUncertain={() => {
            setNotice('Send status unknown — check the "Uncertain sends" section on Mission Brief to resolve it.');
            onOutreachChange?.();
          }}
          onRequestRedraft={() => toggleRedraft(reviewingEntry)}
        />
      )}
    </div>
  );
}
