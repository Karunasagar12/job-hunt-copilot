import { useEffect, useState } from 'react';
import { fetchGeoStats } from '../api.js';

const GEOS = [
  { key: 'gcc', label: 'GCC / UAE' },
  { key: 'india', label: 'India' },
  { key: 'eu', label: 'Europe' },
];

const STATUS_COLORS = {
  new: 'bg-gray-400',
  generating: 'bg-blue-500',
  cv_ready: 'bg-sky-500',
  applied: 'bg-indigo-500',
  sent: 'bg-amber-500',
  reply: 'bg-green-500',
  interview: 'bg-purple-500',
  offer: 'bg-emerald-500',
  rejected: 'bg-red-400',
};

const STATUS_LABELS = {
  new: 'New',
  generating: 'Generating',
  cv_ready: 'CV Ready',
  applied: 'Applied',
  sent: 'Sent',
  reply: 'Reply',
  interview: 'Interview',
  offer: 'Offer',
  rejected: 'Rejected',
};

function formatPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return `${Math.round(Number(value) * 100)}%`;
}

function formatAts(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return value;
}

function getTopStatus(byStatus) {
  if (!byStatus || typeof byStatus !== 'object') return null;
  const entries = Object.entries(byStatus).filter(([, count]) => Number(count || 0) > 0);
  if (entries.length === 0) return null;
  return entries.sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))[0][0];
}

export default function GeoBreakdown() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const results = await Promise.all([
          fetchGeoStats('gcc'),
          fetchGeoStats('india'),
          fetchGeoStats('eu'),
        ]);
        if (!cancelled) {
          setRows(GEOS.map((geo, index) => ({ ...geo, data: results[index] || null })));
        }
      } catch {
        if (!cancelled) setRows(GEOS.map((geo) => ({ ...geo, data: null })));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-gray-950">Geographic Breakdown</h2>
      </div>

      {loading ? (
        <div className="text-sm text-gray-500">Loading...</div>
      ) : rows.length === 0 ? (
        <div className="text-sm text-gray-500">No data yet.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100">
            <thead>
              <tr className="text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                <th className="py-2 pr-4">Geography</th>
                <th className="px-4 py-2 text-right">Total Jobs</th>
                <th className="px-4 py-2 text-right">Avg ATS</th>
                <th className="px-4 py-2 text-right">Response Rate</th>
                <th className="py-2 pl-4 text-right">Top Status</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-gray-100">
              {rows.map((row) => {
                const topStatus = getTopStatus(row.data?.by_status);
                return (
                  <tr key={row.key} className="text-sm">
                    <td className="py-3 pr-4 font-medium text-gray-800">{row.label}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{row.data?.total ?? '—'}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{formatAts(row.data?.avg_ats_score)}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{formatPercent(row.data?.response_rate)}</td>
                    <td className="py-3 pl-4 text-right">
                      {topStatus ? (
                        <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium text-white ${STATUS_COLORS[topStatus] || 'bg-gray-400'}`}>
                          {STATUS_LABELS[topStatus] || topStatus}
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
