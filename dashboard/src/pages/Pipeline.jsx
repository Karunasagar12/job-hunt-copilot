import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchJobs } from '../api.js';
import JobTable from '../components/JobTable.jsx';
import useRegions from '../hooks/useRegions.js';
import { regionLabel } from '../utils/regions.js';

const STATUSES = ['new','generating','cv_ready','applied','sent','reply','interview','offer','rejected'];
const STATUS_LABELS = { new:'New', generating:'Generating', cv_ready:'CV Ready', applied:'Applied', sent:'Sent', reply:'Reply', interview:'Interview', offer:'Offer', rejected:'Rejected' };
export default function Pipeline() {
  const { regions } = useRegions();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState([]);
  const [geoFilter, setGeoFilter] = useState([]);
  const [sort, setSort] = useState('date');
  const [search, setSearch] = useState('');
  const mounted = useRef(true);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  async function load() {
    try {
      const data = await fetchJobs();
      if (mounted.current) { setJobs(data); setError(''); }
    } catch (e) {
      if (mounted.current) setError(e.message);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }

  useEffect(() => { load(); const id = setInterval(load, 10000); return () => clearInterval(id); }, []);
  useEffect(() => {
    function onCreated() { load(); }
    window.addEventListener('job-created', onCreated);
    return () => window.removeEventListener('job-created', onCreated);
  }, []);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const knownRegions = new Set(regions.map(region => region.id));
    return jobs.filter(j => {
      const geo = (j.geography || '').toLowerCase();
      const matchesGeo = !geoFilter.length || geoFilter.includes(geo) ||
        (geoFilter.includes('other') && Boolean(geo) && geo !== 'auto' && !knownRegions.has(geo));
      return (!statusFilter.length || statusFilter.includes(j.status)) &&
        matchesGeo &&
        (!q || (j.company||'').toLowerCase().includes(q) || (j.role||'').toLowerCase().includes(q));
    }).sort((a, b) => {
      if (sort === 'score') return (b.ats_score ?? -1) - (a.ats_score ?? -1);
      if (sort === 'company') return (a.company||'').localeCompare(b.company||'');
      return new Date(b.created_at||0) - new Date(a.created_at||0);
    });
  }, [jobs, statusFilter, geoFilter, sort, search, regions]);

  const unknownGeographies = jobs.some(job => {
    const geography = (job.geography || '').toLowerCase();
    return geography && geography !== 'auto' && !regions.some(region => region.id === geography);
  });

  function toggle(list, set, val) { set(list.includes(val) ? list.filter(v => v !== val) : [...list, val]); }
  function openAdd() { window.dispatchEvent(new CustomEvent('open-add-job')); }

  return (
    <div className="space-y-6">
      <div className="space-y-5 rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
        <div>
          <div className="mb-2 text-sm font-medium text-slate-400">Status</div>
          <div className="flex flex-wrap gap-2">
            {STATUSES.map(s => (
              <button key={s} type="button" onClick={() => toggle(statusFilter, setStatusFilter, s)}
                className={`rounded-full border px-3 py-1.5 text-sm font-medium transition ${
                  statusFilter.includes(s)
                    ? 'border-cyan-500 bg-cyan-500/10 text-cyan-400'
                    : 'border-slate-600 text-slate-400 hover:border-slate-500 hover:bg-slate-700 hover:text-white'
                }`}>
                {STATUS_LABELS[s]}
              </button>
            ))}
          </div>
        </div>
        <div className="grid gap-4 lg:grid-cols-[1fr_200px_260px]">
          <div>
            <div className="mb-2 text-sm font-medium text-slate-400">Geography</div>
            <div className="flex gap-2">
              {[...regions.map(region => ({ id: region.id, label: region.label })), ...(unknownGeographies ? [{ id: 'other', label: 'Other' }] : [])].map(({ id, label }) => (
                <button key={id} type="button" onClick={() => toggle(geoFilter, setGeoFilter, id)}
                  className={`rounded-full border px-3 py-1.5 text-sm font-medium transition ${
                    geoFilter.includes(id)
                      ? 'border-cyan-500 bg-cyan-500/10 text-cyan-400'
                      : 'border-slate-600 text-slate-400 hover:border-slate-500 hover:bg-slate-700 hover:text-white'
                  }`}>
                  {id === 'other' ? label : regionLabel(regions, id)}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-400">Sort</label>
            <select value={sort} onChange={e => setSort(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500">
              <option value="date">Newest</option>
              <option value="score">ATS Score</option>
              <option value="company">Company A-Z</option>
            </select>
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-400">Search</label>
            <input type="search" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Company or role…"
              className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500" />
          </div>
        </div>
      </div>

      {error && <div className="rounded-xl border border-red-700 bg-red-900/30 p-4 text-sm text-red-400">{error}</div>}

      {loading ? (
        <div className="flex justify-center rounded-xl border border-slate-700 bg-slate-800 p-12">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400" />
        </div>
      ) : visible.length > 0 ? (
        <JobTable jobs={visible} onJobUpdated={updated => setJobs(js => js.map(j => j.id === updated.id ? { ...j, ...updated } : j))} />
      ) : jobs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-600 bg-slate-800 p-12 text-center">
          <h2 className="text-lg font-semibold text-white">No jobs yet</h2>
          <p className="mt-2 text-sm text-slate-400">Add your first job to start generating tailored CVs.</p>
          <button type="button" onClick={openAdd}
            className="mt-5 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400">
            Add your first job
          </button>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-600 bg-slate-800 p-12 text-center">
          <p className="text-sm text-slate-400">No jobs match your filters.</p>
        </div>
      )}
    </div>
  );
}
