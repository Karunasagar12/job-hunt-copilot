import { useEffect, useRef, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { fetchStats } from '../api.js';
import TodayCountCard from './TodayCountCard.jsx';

const STATUS_COLORS = {
  new: 'bg-slate-400', generating: 'bg-blue-500', cv_ready: 'bg-cyan-500',
  applied: 'bg-cyan-500', sent: 'bg-amber-500', reply: 'bg-green-500',
  interview: 'bg-purple-500', offer: 'bg-emerald-500', rejected: 'bg-red-400',
};

const STATUS_LABELS = {
  new: 'New', generating: 'Generating', cv_ready: 'CV Ready', applied: 'Applied',
  sent: 'Sent', reply: 'Reply', interview: 'Interview', offer: 'Offer', rejected: 'Rejected',
};

const NAV_LINKS = [
  { to: '/pipeline', label: 'Pipeline' },
  { to: '/today', label: 'Mission Brief' },
  { to: '/shortlist', label: 'Shortlist', badge: 'shortlist_new' },
  { to: '/analytics', label: 'Analytics' },
  { to: '/contacts', label: 'Contacts' },
];

export default function Sidebar({ isOpen = false, onClose = () => {} }) {
  const [stats, setStats] = useState(null);
  const [time, setTime] = useState(() => new Date());
  const location = useLocation();
  const lastPathRef = useRef(location.pathname);

  useEffect(() => {
    if (lastPathRef.current === location.pathname) return;
    lastPathRef.current = location.pathname;
    if (isOpen) onClose();
  }, [location.pathname, isOpen, onClose]);

  useEffect(() => {
    async function load() {
      try { setStats(await fetchStats()); } catch {}
    }
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const byStatus = stats?.by_status || {};
  const statusEntries = Object.entries(byStatus).filter(([, n]) => n > 0);
  const thisWeek = stats?.this_week || null;
  const showThisWeek = thisWeek && ['applied', 'interviews', 'replies'].some(k => Number(thisWeek[k] || 0) > 0);
  const responseRate = stats?.response_rate != null ? `${Math.round(stats.response_rate * 100)}%` : '—';
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone.split('/').pop().replace(/_/g, ' ');
  const hh = time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-950/70 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <aside className={`fixed inset-y-0 left-0 z-50 flex w-[280px] flex-col border-r border-slate-700 bg-slate-900 transition-transform duration-200 md:z-30 md:translate-x-0 ${isOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="border-b border-slate-700 px-6 py-6">
          <div className="flex items-center gap-3">
            <span className="font-mono text-xl font-bold uppercase tracking-[0.2em] text-white">Job Hunt Copilot</span>
          </div>
          <div className="mt-0.5 text-xs uppercase tracking-widest text-slate-500">Recruitment Intelligence</div>
        </div>

        <div className="border-b border-slate-700 px-6 py-4">
          <div className="font-mono text-2xl font-bold tracking-widest text-cyan-400">
            {hh}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-500" />
            {tz}
          </div>
        </div>

        <nav className="py-4">
          {NAV_LINKS.map(({ to, label, badge }) => (
            <NavLink key={to} to={to}
              className={({ isActive }) =>
                `flex items-center justify-between border-l-2 px-6 py-3 text-sm font-medium transition ${
                  isActive
                    ? 'border-cyan-400 bg-cyan-500/10 text-cyan-400'
                    : 'border-transparent text-slate-400 hover:bg-slate-800 hover:text-white'
                }`
              }>
              {label}
              {badge && Number(stats?.[badge] || 0) > 0 && (
                <span className="rounded-full bg-cyan-500/20 px-2 py-0.5 font-mono text-xs text-cyan-300">{stats[badge]}</span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 pb-6">
          {stats && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <TodayCountCard label="Applied Today" timestamps={stats.applied_at_recent || []} />
                <TodayCountCard label="Emails Sent Today" timestamps={stats.sent_at_recent || []} />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                  <div className="font-mono text-xl text-white">{stats.total_jobs ?? '—'}</div>
                  <div className="mt-1 text-xs text-slate-500">Total Jobs</div>
                </div>
                <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                  <div className="font-mono text-xl text-white">{stats.avg_ats_score ?? '—'}</div>
                  <div className="mt-1 text-xs text-slate-500">Avg ATS</div>
                </div>
              </div>

              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <div className="font-mono text-xl text-white">{responseRate}</div>
                <div className="mt-1 text-xs text-slate-500">Response Rate</div>
              </div>

              {showThisWeek && (
                <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                  <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">This Week</div>
                  <div className="space-y-2 text-sm">
                    {[['Applied', thisWeek.applied], ['Interviews', thisWeek.interviews], ['Replies', thisWeek.replies]].map(([label, val]) => (
                      <div key={label} className="flex justify-between">
                        <span className="text-slate-400">{label}</span>
                        <span className="font-mono text-white">{val ?? 0}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {statusEntries.length > 0 && (
                <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                  <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">By Status</div>
                  <div className="space-y-2">
                    {statusEntries.map(([status, count]) => (
                      <div key={status} className="flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className={`h-2 w-2 rounded-full ${STATUS_COLORS[status] || 'bg-slate-500'}`} />
                          <span className="truncate text-sm text-slate-400">{STATUS_LABELS[status] || status}</span>
                        </div>
                        <span className="font-mono text-sm text-white">{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </>
  );
}
