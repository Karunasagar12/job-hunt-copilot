import { useNavigate } from 'react-router-dom';
import StatusDropdown from './StatusDropdown.jsx';

function fmtDate(v) {
  if (!v) return '—';
  const d = new Date(v);
  return isNaN(d) ? '—' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export default function JobRow({ job, onJobUpdated }) {
  const navigate = useNavigate();
  const id = job.id ?? job.job_id;
  const contactCount = job.contact_count ?? 0;

  function handleRowClick(e) {
    if (e.target.closest('select, button, a')) return;
    navigate(`/job/${id}`);
  }

  return (
    <tr onClick={handleRowClick} className="cursor-pointer text-slate-300 transition hover:bg-slate-700/40">
      <td className="px-5 py-4">
        <StatusDropdown id={id} status={job.status} onChange={s => onJobUpdated?.({ ...job, status: s })} />
      </td>
      <td className="px-5 py-4 font-medium text-white">{job.company || '—'}</td>
      <td className="px-5 py-4 text-sm text-slate-300">{job.role || '—'}</td>
      <td className="px-5 py-4 font-mono text-xs uppercase text-slate-400">{job.geography || '—'}</td>
      <td className="px-5 py-4 font-mono text-sm text-white">{job.ats_score ?? '—'}</td>
      <td className={`px-5 py-4 font-mono text-sm ${contactCount < 3 ? 'text-red-400' : 'text-slate-400'}`}>
        {contactCount} contact{contactCount !== 1 ? 's' : ''}
      </td>
      <td className="px-5 py-4 font-mono text-sm text-slate-500">
        {job.applied_at
          ? <span title={new Date(job.applied_at).toLocaleString()}>Applied {fmtDate(job.applied_at)}</span>
          : fmtDate(job.created_at)}
      </td>
    </tr>
  );
}
