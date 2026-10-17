import { useEffect, useState } from 'react';
import { fetchFunnel } from '../api.js';

const STAGE_LABELS = {
  cv_ready: 'CV Ready',
  applied: 'Applied',
  sent: 'Sent',
  reply: 'Reply',
  interview: 'Interview',
  offer: 'Offer',
};

const STAGE_COLORS = [
  'bg-indigo-600',
  'bg-indigo-500',
  'bg-blue-500',
  'bg-cyan-500',
  'bg-teal-500',
  'bg-emerald-500',
];

const WIDTH_CLASSES = {
  0: 'w-0',
  5: 'w-[5%]',
  10: 'w-[10%]',
  15: 'w-[15%]',
  20: 'w-[20%]',
  25: 'w-[25%]',
  30: 'w-[30%]',
  35: 'w-[35%]',
  40: 'w-[40%]',
  45: 'w-[45%]',
  50: 'w-[50%]',
  55: 'w-[55%]',
  60: 'w-[60%]',
  65: 'w-[65%]',
  70: 'w-[70%]',
  75: 'w-[75%]',
  80: 'w-[80%]',
  85: 'w-[85%]',
  90: 'w-[90%]',
  95: 'w-[95%]',
  100: 'w-full',
};

function formatConversion(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return `↓ ${Math.round(Number(value) * 100)}%`;
}

function getWidthClass(count, maxCount) {
  const numericCount = Number(count || 0);
  if (numericCount <= 0 || maxCount <= 0) return WIDTH_CLASSES[0];
  const step = Math.max(5, Math.round((numericCount / maxCount) * 20) * 5);
  return WIDTH_CLASSES[Math.min(100, step)] || WIDTH_CLASSES[100];
}

function getStageColor(index, total) {
  if (total <= 1) return STAGE_COLORS[0];
  const colorIndex = Math.round((index * (STAGE_COLORS.length - 1)) / (total - 1));
  return STAGE_COLORS[colorIndex] || STAGE_COLORS[STAGE_COLORS.length - 1];
}

export default function PipelineFunnel() {
  const [stages, setStages] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const data = await fetchFunnel();
        if (!cancelled) setStages(Array.isArray(data?.stages) ? data.stages : []);
      } catch {
        if (!cancelled) setStages([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const maxCount = stages.reduce((max, stage) => Math.max(max, Number(stage?.count || 0)), 0);

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-gray-950">Pipeline Funnel</h2>
      </div>

      {loading ? (
        <div className="text-sm text-gray-500">Loading...</div>
      ) : stages.length === 0 ? (
        <div className="text-sm text-gray-500">No pipeline data yet.</div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-[minmax(0,1fr)_80px_120px] gap-3 border-b border-gray-100 pb-2 text-xs font-medium uppercase tracking-wide text-gray-400">
            <div>Stage name</div>
            <div className="text-right">Count</div>
            <div className="text-right">Conversion</div>
          </div>

          {stages.map((stage, index) => {
            const name = stage?.name || '';
            const count = Number(stage?.count || 0);
            const conversion = stage?.conversion_from_previous;
            const conversionIsMissing = conversion == null || Number.isNaN(Number(conversion));

            return (
              <div key={`${name}-${index}`} className="grid grid-cols-[minmax(0,1fr)_80px_120px] items-center gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-gray-800">
                    {STAGE_LABELS[name] || name || '—'}
                  </div>
                  <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-gray-100">
                    <div className={`h-2.5 rounded-full ${getStageColor(index, stages.length)} ${getWidthClass(count, maxCount)}`} />
                  </div>
                </div>

                <div className="text-right text-sm font-semibold text-gray-950">{count}</div>

                <div className={`text-right text-sm font-medium ${conversionIsMissing ? 'text-gray-400' : 'text-gray-700'}`}>
                  {formatConversion(conversion)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
