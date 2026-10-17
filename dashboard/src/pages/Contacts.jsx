import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchAllContacts } from '../api.js';

function formatContactType(contactType) {
  if (!contactType) return 'Unknown';
  const normalized = String(contactType).trim().toLowerCase();
  if (normalized === 'hr') return 'HR';
  return normalized
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function toSearchable(value) {
  return value == null ? '' : String(value).toLowerCase();
}

export default function Contacts() {
  const navigate = useNavigate();
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        setLoading(true);
        setError('');
        const data = await fetchAllContacts();
        if (active) setContacts(Array.isArray(data) ? data : []);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load contacts.');
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => { active = false; };
  }, []);

  const term = search.trim().toLowerCase();
  const visible = contacts.filter(c =>
    !term || [c.name, c.email, c.job_company, c.job_role].some(v => toSearchable(v).includes(term))
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Contacts</h1>
        <p className="mt-1 text-sm text-slate-400">All contacts across active jobs</p>
      </div>

      <input
        type="search"
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Search contacts…"
        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-white placeholder:text-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
      />

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400" />
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-700 bg-red-900/30 px-4 py-3 text-sm text-red-400">{error}</div>
      ) : visible.length === 0 ? (
        <div className="rounded-xl border border-slate-700 bg-slate-800 px-4 py-10 text-center text-slate-500">
          No contacts yet.
        </div>
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden overflow-x-auto rounded-xl border border-slate-700 bg-slate-800 shadow-sm md:block">
            <table className="min-w-full divide-y divide-slate-700 text-left">
              <thead className="bg-slate-900">
                <tr>
                  {['Name', 'Title', 'Email', 'Job', 'Type', 'Outreach', 'Dup'].map(h => (
                    <th key={h} className="px-4 py-3 text-xs font-medium uppercase tracking-wide text-slate-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700">
                {visible.map(c => (
                  <tr key={c.id} className="text-slate-300 transition hover:bg-slate-700/40">
                    <td className="px-4 py-4 font-medium text-white">{c.name || 'Unnamed'}</td>
                    <td className="px-4 py-4 text-sm">{c.title || '—'}</td>
                    <td className="px-4 py-4 font-mono text-sm">{c.email || '—'}</td>
                    <td className="px-4 py-4 text-sm">
                      <button type="button" onClick={() => navigate(`/job/${c.job_id}`)}
                        className="text-left text-cyan-400 hover:text-cyan-300">
                        <span className="block font-medium">{c.job_company || '—'}</span>
                        <span className="block text-xs text-slate-400">{c.job_role || '—'}</span>
                      </button>
                    </td>
                    <td className="px-4 py-4 text-sm">{formatContactType(c.contact_type)}</td>
                    <td className="px-4 py-4 font-mono text-sm">
                      {(c.sent_count ?? 0)}/{(c.outreach_count ?? 0)}
                      {(c.linkedin_done_count ?? 0) > 0 && (
                        <span className="ml-2 inline-flex rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-xs font-medium text-cyan-300">
                          🔗 +{c.linkedin_done_count}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-4">
                      {(c.dedup_count ?? 0) > 0 && (
                        <span className="inline-flex rounded-full border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-300">Dup</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="space-y-3 md:hidden">
            {visible.map(c => (
              <div key={c.id} className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold text-white">{c.name || 'Unnamed'}</div>
                    <div className="mt-0.5 text-sm text-slate-400">{c.title || 'No title'}</div>
                    <button type="button" onClick={() => navigate(`/job/${c.job_id}`)}
                      className="mt-1 text-left text-sm text-cyan-400 hover:text-cyan-300">
                      {c.job_company || '—'} · <span className="text-xs text-slate-400">{c.job_role || '—'}</span>
                    </button>
                  </div>
                  {(c.dedup_count ?? 0) > 0 && (
                    <span className="shrink-0 rounded-full border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-300">Dup</span>
                  )}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300">{c.email || 'No email'}</span>
                  <span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300">{formatContactType(c.contact_type)}</span>
                  <span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300">Outreach {(c.sent_count ?? 0)}/{(c.outreach_count ?? 0)}</span>
                  {(c.linkedin_done_count ?? 0) > 0 && (
                    <span className="rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 text-xs font-medium text-cyan-300">🔗 +{c.linkedin_done_count}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
