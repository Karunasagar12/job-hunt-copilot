import { useEffect, useRef, useState } from 'react';
import { createJob, matchLinkedIn } from '../api.js';

const EMPTY_CONTACT = { linkedin_url: '', name: '', title: '', email: '', contact_type: 'hiring_manager' };

function initForm() {
  return {
    inputMode: 'url', jd_url: '', jd_text: '',
    source_type: 'company', geography: 'auto', company: '',
    contacts: [{ ...EMPTY_CONTACT }, { ...EMPTY_CONTACT }, { ...EMPTY_CONTACT }],
  };
}

export default function AddJobForm({ isOpen, onClose, onCreated }) {
  const [form, setForm] = useState(initForm);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [autofillingIdx, setAutofillingIdx] = useState(null);
  const [autofillError, setAutofillError] = useState('');
  const mountedRef = useRef(true);

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  useEffect(() => {
    if (!isOpen) { setForm(initForm()); setSubmitting(false); setError(''); setSuccess(''); }
  }, [isOpen]);

  function set(field, value) { setForm(f => ({ ...f, [field]: value })); }
  function setContact(i, field, value) {
    setForm(f => ({ ...f, contacts: f.contacts.map((c, idx) => idx === i ? { ...c, [field]: value } : c) }));
  }

  async function handleAutofill(i) {
    const url = form.contacts[i].linkedin_url.trim();
    if (!url) return;
    setAutofillingIdx(i); setAutofillError('');
    try {
      const person = await matchLinkedIn(url);
      setForm(f => ({
        ...f,
        contacts: f.contacts.map((c, idx) => idx === i ? {
          ...c,
          name: person.name || c.name,
          title: person.title || c.title,
          email: person.email || c.email,
        } : c),
      }));
    } catch (err) {
      setAutofillError(`Contact ${i + 1}: ${err.message || 'Apollo lookup failed'}`);
    } finally {
      setAutofillingIdx(null);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(''); setSuccess('');
    const usingUrl = form.inputMode === 'url';
    if (usingUrl && !form.jd_url.trim()) { setError('JD URL is required.'); return; }
    if (!usingUrl && !form.jd_text.trim()) { setError('JD text is required.'); return; }

    const contacts = form.contacts
      .map(c => ({
        name: c.name.trim(), title: c.title.trim(), contact_type: c.contact_type,
        linkedin_url: c.linkedin_url.trim() || undefined,
        email: c.email.trim() || undefined,
      }))
      .filter(c => c.name || c.title || c.linkedin_url);

    const payload = {
      source_type: form.source_type, geography: form.geography,
      contacts,
      ...(form.company.trim() ? { company: form.company.trim() } : {}),
      ...(usingUrl ? { jd_url: form.jd_url.trim() } : { jd_text: form.jd_text.trim() }),
    };

    setSubmitting(true);
    try {
      await createJob(payload);
      if (!mountedRef.current) return;
      onCreated?.();
      setSuccess('Job queued — generating in background');
      setTimeout(() => { if (mountedRef.current) { setSubmitting(false); onClose(); } }, 800);
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err.message || 'Failed to create job');
      setSubmitting(false);
    }
  }

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-gray-950/30">
      <div className="h-full w-full max-w-2xl overflow-y-auto bg-white shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-200 bg-white px-6 py-5">
          <h2 className="text-xl font-semibold text-gray-950">Add Job</h2>
          <button type="button" onClick={onClose} disabled={submitting}
            className="rounded-lg px-3 py-2 text-sm text-gray-500 hover:bg-gray-100 disabled:opacity-50">Close</button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6 p-6">
          {error && <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
          {success && <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-700">{success}</div>}

          <fieldset disabled={submitting} className="space-y-6 disabled:opacity-60">
            <div>
              <div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-1 mb-4">
                {['url', 'text'].map(mode => (
                  <button key={mode} type="button" onClick={() => set('inputMode', mode)}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium ${form.inputMode === mode ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600'}`}>
                    {mode === 'url' ? 'JD URL' : 'JD Text'}
                  </button>
                ))}
              </div>
              {form.inputMode === 'url'
                ? <input type="url" value={form.jd_url} onChange={e => set('jd_url', e.target.value)}
                    placeholder="https://linkedin.com/jobs/view/..."
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500" />
                : <textarea value={form.jd_text} onChange={e => set('jd_text', e.target.value)}
                    rows={8} placeholder="Paste the job description..."
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500" />
              }
            </div>

            <div className="flex gap-6">
              {[['company', 'Direct company'], ['recruiter', 'Recruiter/agency']].map(([val, lbl]) => (
                <label key={val} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input type="radio" name="source_type" value={val} checked={form.source_type === val}
                    onChange={e => set('source_type', e.target.value)} className="text-indigo-600" />
                  {lbl}
                </label>
              ))}
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Geography</label>
                <select value={form.geography} onChange={e => set('geography', e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500">
                  <option value="auto">Auto-detect</option>
                  <option value="gcc">GCC</option>
                  <option value="india">India</option>
                  <option value="eu">EU</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Company override</label>
                <input type="text" value={form.company} onChange={e => set('company', e.target.value)}
                  placeholder="Optional — for agency posts"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500" />
              </div>
            </div>

            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-3">Contacts <span className="font-normal text-gray-400">(optional)</span></h3>
              <div className="space-y-3">
                {form.contacts.map((c, i) => (
                  <div key={i} className="rounded-xl border border-gray-200 bg-gray-50 p-4 space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-400">Contact {i + 1}</div>
                    <div className="flex gap-2">
                      <input type="url" value={c.linkedin_url} onChange={e => setContact(i, 'linkedin_url', e.target.value)}
                        placeholder="LinkedIn profile URL (auto-fill)"
                        className="min-w-0 flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500" />
                      <button type="button" onClick={() => handleAutofill(i)}
                        disabled={!c.linkedin_url.trim() || autofillingIdx === i}
                        className="flex shrink-0 items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-40">
                        {autofillingIdx === i && (
                          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-indigo-700 border-t-transparent" />
                        )}
                        {autofillingIdx === i ? 'Enriching…' : 'Fill'}
                      </button>
                    </div>
                    <div className="grid gap-3 md:grid-cols-3">
                      <input type="text" value={c.name} onChange={e => setContact(i, 'name', e.target.value)}
                        placeholder="Name" className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500" />
                      <input type="text" value={c.title} onChange={e => setContact(i, 'title', e.target.value)}
                        placeholder="Title" className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500" />
                      <select value={c.contact_type} onChange={e => setContact(i, 'contact_type', e.target.value)}
                        className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500">
                        <option value="hiring_manager">Hiring manager</option>
                        <option value="recruiter">Recruiter</option>
                        <option value="agency">Agency</option>
                        <option value="executive">Executive</option>
                        <option value="peer">Peer</option>
                      </select>
                    </div>
                    <input type="email" value={c.email} onChange={e => setContact(i, 'email', e.target.value)}
                      placeholder="Email (auto-filled or enter manually)"
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500" />
                  </div>
                ))}
              </div>
              {autofillError && <p className="mt-2 text-sm text-red-600">{autofillError}</p>}
            </div>
          </fieldset>

          <div className="flex justify-end gap-3 border-t border-gray-100 pt-6">
            <button type="button" onClick={onClose} disabled={submitting}
              className="rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 disabled:opacity-50">Cancel</button>
            <button type="submit" disabled={submitting}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">Submit</button>
          </div>
        </form>
      </div>
    </div>
  );
}
