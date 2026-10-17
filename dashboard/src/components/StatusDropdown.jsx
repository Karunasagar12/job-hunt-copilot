import { useEffect, useState } from 'react';
import { updateJob } from '../api.js';

const LABELS = {
  new: 'New', generating: 'Generating', cv_ready: 'CV Ready', applied: 'Applied',
  sent: 'Sent', reply: 'Reply', interview: 'Interview', offer: 'Offer',
  rejected: 'Rejected', withdrawn: 'Withdrawn', failed: 'Failed',
};

const ACTIVE = new Set(['new', 'generating', 'cv_ready', 'applied', 'sent', 'reply', 'interview', 'offer']);

const NEXT = {
  new:        ['generating'],
  generating: ['cv_ready', 'failed'],
  cv_ready:   ['applied'],
  applied:    ['sent'],
  sent:       ['reply'],
  reply:      ['interview'],
  interview:  ['offer'],
  offer:      [],
  rejected:   [],
  withdrawn:  [],
  failed:     [],
};

export default function StatusDropdown({ id, status = 'new', onChange }) {
  const [local, setLocal] = useState(status);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { setLocal(status || 'new'); }, [status]);

  const nexts = [...(NEXT[local] || []), ...(ACTIVE.has(local) ? ['withdrawn', 'rejected'] : [])];
  const options = [local, ...nexts.filter(s => s !== local)];
  const terminal = options.length <= 1;

  async function handleChange(e) {
    const next = e.target.value;
    const prev = local;
    setLocal(next); setSaving(true); setError('');
    onChange?.(next);
    try { await updateJob(id, { status: next }); }
    catch (err) { setLocal(prev); onChange?.(prev); setError(err.message); }
    finally { setSaving(false); }
  }

  return (
    <select value={local} onChange={handleChange} disabled={saving || terminal} title={error || undefined}
      className="rounded-lg border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm text-white outline-none transition focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 disabled:cursor-not-allowed disabled:opacity-40">
      {options.map(s => <option key={s} value={s}>{LABELS[s] || s}</option>)}
    </select>
  );
}
