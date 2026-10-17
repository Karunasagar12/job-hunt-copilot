import { useEffect, useState } from 'react';
import { fetchCompanyProfile } from '../api.js';

const FIELD_LABELS = {
  sector: 'Sector',
  company_size: 'Company Size',
  funding_stage: 'Funding Stage',
  tech_stack: 'Tech Stack',
  geography: 'Geography',
  recent_news: 'Recent News',
  competitors: 'Competitors',
  hiring_for: 'Hiring For',
};

export default function CompanyProfile({ jobId }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetchCompanyProfile(jobId)
      .then(data => { if (active) setProfile(data); })
      .catch(e => { if (active) setError(e.message || 'Failed to load company profile.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [jobId]);

  if (loading) {
    return (
      <div className="flex justify-center rounded-xl border border-slate-700 bg-slate-800 p-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400" />
      </div>
    );
  }

  if (error) {
    return <div className="rounded-xl border border-red-700 bg-red-900/30 p-4 text-sm text-red-400">{error}</div>;
  }

  const isPending = !profile || profile.profile_status === 'pending' || profile.profile_status === 'not_found';

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
      <h3 className="mb-4 text-base font-semibold text-white">Company Profile</h3>
      {isPending ? (
        <div className="rounded-lg bg-slate-700/50 p-6 text-center text-sm text-slate-500">
          Not yet profiled — research runs automatically in the background.
        </div>
      ) : (
        <dl className="grid gap-4 sm:grid-cols-2">
          {Object.entries(FIELD_LABELS).map(([key, label]) => (
            <div key={key}>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
              <dd className="mt-1 text-sm text-slate-300">{profile[key] || '—'}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
