import { useEffect, useRef, useState } from 'react';

function isToday(isoTimestamp) {
  const d = new Date(isoTimestamp);
  const now = new Date();
  return d.toDateString() === now.toDateString();
}

export default function TodayCountCard({ label, timestamps = [] }) {
  const count = timestamps.filter(isToday).length;
  const prevCountRef = useRef(count);
  const [displayCount, setDisplayCount] = useState(count);
  const [transition, setTransition] = useState(null);

  useEffect(() => {
    if (count > prevCountRef.current) {
      setTransition({ exitingValue: prevCountRef.current });
      prevCountRef.current = count;
      setDisplayCount(count);
      const timer = setTimeout(() => setTransition(null), 350);
      return () => clearTimeout(timer);
    }
    if (count !== prevCountRef.current) {
      prevCountRef.current = count;
      setDisplayCount(count);
    }
  }, [count]);

  return (
    <div className="rounded-xl border border-cyan-700/50 bg-slate-800 p-5">
      <div className="relative h-10 overflow-hidden">
        {transition && (
          <div key={`exit-${transition.exitingValue}`} className="absolute inset-0 flex items-center font-mono text-4xl font-bold text-cyan-400 animate-roll-out">
            {transition.exitingValue}
          </div>
        )}
        <div
          key={transition ? `enter-${displayCount}` : 'static'}
          className={`absolute inset-0 flex items-center font-mono text-4xl font-bold text-cyan-400 ${transition ? 'animate-roll-in' : ''}`}
        >
          {displayCount}
        </div>
      </div>
      <div className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}
