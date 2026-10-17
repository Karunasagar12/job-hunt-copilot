import { useNavigate } from 'react-router-dom';
import JobRow from './JobRow.jsx';
import StatusDropdown from './StatusDropdown.jsx';

function fmtDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export default function JobTable({ jobs, onJobUpdated }) {
  const navigate = useNavigate();
  const visibleJobs = Array.isArray(jobs) ? jobs : [];

  function handleCardClick(e, id) {
    if (e.target.closest('select, button, a')) return;
    if (id == null || id === '') return;
    navigate(`/job/${id}`);
  }

  return (
    <>
      {/* Mobile: stacked cards */}
      <div className="space-y-3 md:hidden">
        {visibleJobs.map(job => {
          const id = job.id ?? job.job_id;
          const contactCount = job.contact_count ?? 0;
          return (
            <div
              key={id}
              role="button"
              tabIndex={0}
              onClick={e => handleCardClick(e, id)}
              onKeyDown={e => {
                if (e.key !== 'Enter' && e.key !== ' ') return;
                e.preventDefault();
                handleCardClick(e, id);
              }}
              className="cursor-pointer rounded-xl border border-slate-700 bg-slate-800 p-4 shadow-sm"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate font-bold text-white">{job.company || '—'}</div>
                  <div className="mt-1 text-sm text-slate-300">{job.role || '—'}</div>
                </div>
                <div onClick={e => e.stopPropagation()} className="shrink-0">
                  <StatusDropdown
                    id={id}
                    status={job.status}
                    onChange={status => onJobUpdated?.({ ...job, status })}
                  />
                </div>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-xs uppercase tracking-wide text-slate-500">ATS</div>
                  <div className="mt-1 font-mono text-white">{job.ats_score ?? '—'}</div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-slate-500">Geo</div>
                  <div className="mt-1 inline-flex rounded-full border border-slate-700 px-2 py-0.5 font-mono text-xs uppercase text-slate-300">
                    {job.geography || '—'}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-slate-500">Date</div>
                  <div className="mt-1 font-mono text-slate-400">
                    {job.applied_at ? `Applied ${fmtDate(job.applied_at)}` : fmtDate(job.created_at)}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-slate-500">Contacts</div>
                  <div className={`mt-1 font-mono ${contactCount < 3 ? 'text-red-400' : 'text-slate-400'}`}>
                    {contactCount} contact{contactCount !== 1 ? 's' : ''}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop: table */}
      <div className="hidden overflow-hidden rounded-xl border border-slate-700 bg-slate-800 shadow-sm md:block">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-700 text-left">
            <thead className="bg-slate-900">
              <tr>
                {['Status', 'Company', 'Role', 'Geo', 'ATS', 'Contacts', 'Date'].map(h => (
                  <th key={h} className="px-5 py-3 text-xs font-medium uppercase tracking-wide text-slate-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700 bg-slate-800">
              {visibleJobs.map(job => (
                <JobRow key={job.id ?? job.job_id} job={job} onJobUpdated={onJobUpdated} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
