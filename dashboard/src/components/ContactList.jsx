import { useState } from 'react';
import { Link } from 'react-router-dom';
import { addContact, matchLinkedIn } from '../api.js';
import ContactCard from './ContactCard.jsx';
import DedupWarning from './DedupWarning.jsx';
import useIntegrations from '../hooks/useIntegrations.js';
import { integrationErrorMessage } from '../utils/integrations.js';

const EMPTY_FORM = { name: '', title: '', email: '', linkedin_url: '', contact_type: 'hiring_manager' };

export default function ContactList({ jobId, contacts, onContactsChange }) {
  const { isConnected } = useIntegrations();
  const fullenrichOk = isConnected('fullenrich');
  const safe = Array.isArray(contacts) ? contacts : [];

  const [showAddForm, setShowAddForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [adding, setAdding] = useState(false);
  const [autofilling, setAutofilling] = useState(false);
  const [error, setError] = useState('');
  const [dedupWarning, setDedupWarning] = useState(null);

  function updateForm(key, value) { setForm(cur => ({ ...cur, [key]: value })); }

  function closeAddForm() { setShowAddForm(false); setForm(EMPTY_FORM); setError(''); setAutofilling(false); }

  async function handleAutofill() {
    const url = form.linkedin_url.trim();
    if (!url) { setError('Paste a LinkedIn URL first.'); return; }
    setAutofilling(true); setError('');
    try {
      const person = await matchLinkedIn(url);
      setForm(cur => ({
        ...cur,
        name: person.name || cur.name,
        title: person.title || cur.title,
        email: person.email || cur.email,
      }));
    } catch (err) {
      setError(integrationErrorMessage(err, 'FullEnrich lookup failed.'));
    } finally {
      setAutofilling(false);
    }
  }

  async function handleAdd(e) {
    e.preventDefault();
    setError(''); setDedupWarning(null);
    if (!form.name.trim()) { setError('Name is required.'); return; }
    setAdding(true);
    try {
      const res = await addContact(jobId, {
        name: form.name.trim(), title: form.title.trim(),
        email: form.email.trim(), linkedin_url: form.linkedin_url.trim(),
        contact_type: form.contact_type,
      });
      const newContact = res?.contact ?? res;
      if (!newContact?.id) throw new Error('API did not return the added contact.');
      onContactsChange([...safe, newContact]);
      if (res?.dedup_warning) setDedupWarning(res.dedup_warning);
      closeAddForm();
    } catch (err) {
      setError(err.message || 'Failed to add contact.');
    } finally {
      setAdding(false);
    }
  }

  function handleUpdate(updated) {
    onContactsChange(safe.map(c => c.id === updated.id ? updated : c));
  }

  function handleDelete(id) {
    onContactsChange(safe.filter(c => c.id !== id));
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="rounded-full bg-gray-100 px-3 py-1 text-sm font-semibold text-gray-700">
              {safe.length} contacts
            </span>
            {safe.length < 3 && (
              <span className="text-sm font-medium text-amber-700">Need at least 3 contacts for outreach</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button type="button"
              onClick={() => { if (showAddForm) setForm(EMPTY_FORM); setShowAddForm(cur => !cur); setError(''); }}
              className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800">
              Add Contact
            </button>
          </div>
        </div>

        {dedupWarning && (
          <div className="mt-4">
            <DedupWarning warning={dedupWarning}
              onAddAnyway={() => setDedupWarning(null)}
              onDismiss={() => setDedupWarning(null)} />
          </div>
        )}

        {showAddForm && (
          <form onSubmit={handleAdd} className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
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
                <div className="flex gap-2">
                  <input type="url" value={form.linkedin_url} onChange={e => updateForm('linkedin_url', e.target.value)}
                    placeholder="https://linkedin.com/in/..."
                    className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500" />
                  <button type="button" onClick={handleAutofill} disabled={!fullenrichOk || autofilling || !form.linkedin_url.trim()}
                    title={fullenrichOk ? '' : 'Connect FullEnrich in Settings'}
                    className="flex items-center gap-2 rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-40">
                    {autofilling && (
                      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-indigo-700 border-t-transparent" />
                    )}
                    {autofilling ? 'Enriching…' : 'Auto-fill'}
                  </button>
                </div>
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
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
            {!fullenrichOk && <Link to="/settings" className="mt-3 inline-block text-xs text-cyan-700 underline">Connect FullEnrich in Settings</Link>}
            <div className="mt-4 flex items-center gap-3">
              <button type="submit" disabled={adding}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
                {adding ? 'Adding…' : 'Add'}
              </button>
              <button type="button" onClick={closeAddForm} disabled={adding}
                className="text-sm font-medium text-gray-600 hover:text-gray-900 disabled:opacity-50">
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>

      <div className="space-y-3">
        {safe.map(contact => (
          <ContactCard key={contact.id} contact={contact} jobId={jobId}
            onUpdate={handleUpdate}
            onDelete={() => handleDelete(contact.id)} />
        ))}
      </div>
    </div>
  );
}
