export default function AtsGauge({ score }) {
  const circumference = 314;
  const numeric = typeof score === 'number' && Number.isFinite(score) ? Math.max(0, Math.min(50, score)) : null;
  const dashOffset = numeric == null ? circumference : circumference - (numeric / 50) * circumference;

  let label = 'Pending';
  let labelClass = 'text-slate-500';
  if (numeric != null) {
    if (numeric >= 40) { label = 'Excellent'; labelClass = 'text-cyan-400'; }
    else if (numeric >= 35) { label = 'Good'; labelClass = 'text-green-400'; }
    else { label = 'Needs Review'; labelClass = 'text-amber-400'; }
  }

  return (
    <div className="flex flex-col items-center">
      <div className="relative h-[120px] w-[120px]">
        <svg viewBox="0 0 120 120" width="120" height="120">
          <circle cx="60" cy="60" r="50" fill="none" stroke="currentColor" strokeWidth="10" className="text-slate-700" />
          <circle cx="60" cy="60" r="50" fill="none" stroke="currentColor" strokeWidth="10"
            strokeLinecap="round" strokeDasharray="314" strokeDashoffset={dashOffset}
            className="text-cyan-400"
            style={{ transform: 'rotate(-90deg)', transformOrigin: 'center', transition: 'stroke-dashoffset 0.6s ease' }} />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex items-baseline gap-0.5">
            <span className="font-mono text-2xl font-bold text-white">{numeric ?? '—'}</span>
            <span className="text-xs text-slate-400">/50</span>
          </div>
        </div>
      </div>
      <div className={`mt-3 text-sm font-medium ${labelClass}`}>{label}</div>
    </div>
  );
}
