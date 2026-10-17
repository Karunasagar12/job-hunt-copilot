import { useState } from 'react';
import { fetchSalaryEstimate } from '../api.js';

export default function SalaryEstimator({ jobId }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleEstimate(refresh = false) {
    setLoading(true); setError('');
    try {
      const data = await fetchSalaryEstimate(jobId, { refresh });
      setResult(data);
    } catch (e) { setError(e.message || 'Failed to estimate salary.'); }
    finally { setLoading(false); }
  }

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Salary Estimator</h3>
          <p className="mt-1 text-sm text-slate-400">
            AI-estimated range based on this role, company, geography, and your profile.
          </p>
        </div>
        {!result && (
          <button type="button" onClick={() => handleEstimate(false)} disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-40">
            {loading && <span className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-300 border-t-slate-950" />}
            {loading ? 'Estimating…' : 'Estimate Salary'}
          </button>
        )}
      </div>

      {error && <div className="rounded-lg border border-red-700 bg-red-900/30 p-4 text-sm text-red-400">{error}</div>}

      {result && (
        <div className="space-y-4">
          {result.cached && (
            <p className="text-xs text-slate-500">Cached result — click Refresh to regenerate.</p>
          )}
          <div className="whitespace-pre-wrap rounded-lg border border-slate-700 bg-slate-900 p-4 text-sm leading-6 text-slate-300">
            {result.estimate}
          </div>
          <button type="button" onClick={() => handleEstimate(true)} disabled={loading}
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm font-medium text-slate-400 hover:bg-slate-700 hover:text-white disabled:opacity-40">
            {loading ? 'Refreshing…' : 'Refresh Estimate'}
          </button>
        </div>
      )}
    </div>
  );
}
