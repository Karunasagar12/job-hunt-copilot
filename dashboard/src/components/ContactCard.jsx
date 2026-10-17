import { useState } from 'react';
import { deleteContact, fetchContacts, getContactEmail, updateContact } from '../api.js';

// FullEnrich's enrichment is async (~30-90s) -- poll for the result rather than
// expecting it in getContactEmail's own response. Matches the backend's own
// poll_enrichment timeout (120s at ~10s intervals).
const EMAIL_POLL_INTERVAL_MS = 10000;
const EMAIL_POLL_MAX_ATTEMPTS = 12;

const TYPE_BADGES = {
  hiring_manager: { label: 'Hiring Manager', className: 'bg-blue-100 text-blue-700' },
  recruiter:      { label: 'Recruiter',       className: 'bg-purple-100 text-purple-700' },
  agency:         { label: 'Agency',           className: 'bg-orange-100 text-orange-700' },
  executive:      { label: 'Executive',       className: 'bg-rose-100 text-rose-700' },
  peer:           { label: 'Peer',            className: 'bg-teal-100 text-teal-700' },
};

const SOURCE_BADGES = {
  apollo: { label: 'Apollo', className: 'bg-indigo-100 text-indigo-700' },
  manual: { label: 'Manual', className: 'bg-gray-100 text-gray-700' },
  hermes_discovered: { label: 'Hermes', className: 'bg-cyan-100 text-cyan-700' },
};

export default function ContactCard({ contact, jobId, onUpdate, onDelete }) {
  const [isEditing, setIsEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [fetchingEmail, setFetchingEmail] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    name: contact.name || '',
    title: contact.title || '',
    email: contact.email || '',
    linkedin_url: contact.linkedin_url || '',
    contact_type: contact.contact_type || 'hiring_manager',
  });

  const typeBadge = TYPE_BADGES[contact.contact_type] || TYPE_BADGES.hiring_manager;
  const sourceBadge = SOURCE_BADGES[contact.source] || SOURCE_BADGES.manual;

  function updateForm(key, value) {
    setForm(cur => ({ ...cur, [key]: value }));
  }

  function cancelEdit() {
    setError('');
    setForm({
      name: contact.name || '',
      title: contact.title || '',
      email: contact.email || '',
      linkedin_url: contact.linkedin_url || '',
      contact_type: contact.contact_type || 'hiring_manager',
    });
    setIsEditing(false);
  }

  async function handleSave(e) {
    e.preventDefault();
    setError('');
    if (!form.name.trim()) { setError('Name is required.'); return; }
    setSaving(true);
    try {
      const data = await updateContact(contact.id, {
        name: form.name.trim(),
        title: form.title.trim(),
        email: form.email.trim(),
        linkedin_url: form.linkedin_url.trim(),
        contact_type: form.contact_type,
      });
      onUpdate(data?.contact ?? data);
      setIsEditing(false);
    } catch (err) {
      setError(err.message || 'Failed to update contact.');
    } finally {
      setSaving(false);
    }
  }

  async function handleGetEmail() {
    setError(''); setFetchingEmail(true);
    try {
      await getContactEmail(contact.id); // starts the async enrichment, returns immediately with no email yet
      for (let attempt = 0; attempt < EMAIL_POLL_MAX_ATTEMPTS; attempt++) {
        await new Promise(resolve => setTimeout(resolve, EMAIL_POLL_INTERVAL_MS));
        const contacts = await fetchContacts(jobId);
        const refreshed = (Array.isArray(contacts) ? contacts : []).find(c => c.id === contact.id);
        if (refreshed) {
          onUpdate(refreshed);
          if (refreshed.email) break;
        }
      }
    } catch (err) {
      setError(err.message || 'Failed to fetch email.');
    } finally {
      setFetchingEmail(false);
    }
  }

  async function handleDelete() {
    setError('');
    setDeleting(true);
    try {
      await deleteContact(contact.id);
      onDelete();
    } catch (err) {
      setError(err.message || 'Failed to delete contact.');
      setDeleting(false);
    }
  }

  if (isEditing) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <form onSubmit={handleSave} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-gray-700">Name *</span>
              <input required type="text" value={form.name} onChange={e => updateForm('name', e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500" />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-gray-700">Title</span>
              <input type="text" value={form.title} onChange={e => updateForm('title', e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500" />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-gray-700">Email</span>
              <input type="email" value={form.email} onChange={e => updateForm('email', e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500" />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-gray-700">LinkedIn URL</span>
              <input type="url" value={form.linkedin_url} onChange={e => updateForm('linkedin_url', e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500" />
            </label>
            <label className="block text-sm sm:col-span-2">
              <span className="mb-1 block font-medium text-gray-700">Contact type</span>
              <select value={form.contact_type} onChange={e => updateForm('contact_type', e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500">
                <option value="hiring_manager">Hiring Manager</option>
                <option value="recruiter">Recruiter</option>
                <option value="agency">Agency</option>
                <option value="executive">Executive</option>
                <option value="peer">Peer</option>
              </select>
            </label>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex items-center gap-3">
            <button type="submit" disabled={saving}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button type="button" onClick={cancelEdit} disabled={saving}
              className="text-sm font-medium text-gray-600 hover:text-gray-900 disabled:opacity-50">
              Cancel
            </button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h4 className="font-semibold text-gray-950">{contact.name}</h4>
          {contact.title && <p className="text-sm text-gray-500">{contact.title}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
            {contact.email ? (
              <a href={`mailto:${contact.email}`} className="text-sm text-indigo-600 hover:text-indigo-800">
                {contact.email}
              </a>
            ) : (contact.apollo_id || contact.linkedin_url) ? (
              <button type="button" onClick={handleGetEmail} disabled={fetchingEmail}
                className="flex items-center gap-2 text-sm font-medium text-amber-700 hover:text-amber-900 disabled:opacity-50">
                {fetchingEmail && (
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-amber-700 border-t-transparent" />
                )}
                {fetchingEmail ? 'Enriching…' : 'Get email'}
              </button>
            ) : null}
            {contact.linkedin_url && (
              <a href={contact.linkedin_url} target="_blank" rel="noreferrer"
                className="text-sm text-indigo-600 hover:text-indigo-800">
                LinkedIn →
              </a>
            )}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${typeBadge.className}`}>
              {typeBadge.label}
            </span>
            <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${sourceBadge.className}`}>
              {sourceBadge.label}
            </span>
            {contact.replied === 1 && (
              <span className="rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-700">
                Replied
              </span>
            )}
            {contact.email_status === 'bounced' && (
              <span className="rounded-full bg-red-100 px-2.5 py-1 text-xs font-semibold text-red-700">
                Bounced
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <button type="button" onClick={() => { setError(''); setIsEditing(true); }}
            className="text-sm font-medium text-gray-600 hover:text-gray-950">
            Edit
          </button>
          <button type="button" onClick={() => { setError(''); setConfirmingDelete(true); }}
            className="text-sm font-medium text-gray-600 hover:text-red-700">
            Delete
          </button>
        </div>
      </div>

      {confirmingDelete && (
        <div className="mt-4 rounded-lg bg-gray-50 p-3 text-sm text-gray-700">
          Are you sure?{' '}
          <button type="button" onClick={handleDelete} disabled={deleting}
            className="font-semibold text-red-700 hover:text-red-800 disabled:opacity-50">
            {deleting ? 'Deleting…' : 'Yes, Delete'}
          </button>{' '}
          <button type="button" onClick={() => setConfirmingDelete(false)} disabled={deleting}
            className="font-medium text-gray-600 hover:text-gray-900 disabled:opacity-50">
            Cancel
          </button>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
    </div>
  );
}
