import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import AddJobForm from './AddJobForm.jsx';
import Sidebar from './Sidebar.jsx';

const TITLES = {
  '/pipeline': 'Pipeline',
  '/today': 'Mission Brief',
  '/shortlist': 'Shortlist',
  '/analytics': 'Analytics',
  '/profile': 'Profile',
  '/settings': 'Settings',
};

export default function Layout() {
  const [addOpen, setAddOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const title = TITLES[location.pathname] || (location.pathname.startsWith('/job/') ? 'Job Detail' : 'Dashboard');

  function handleCreated() {
    window.dispatchEvent(new CustomEvent('job-created'));
  }

  return (
    <div className="min-h-screen bg-slate-950">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <main
        className="ml-0 h-screen overflow-y-auto bg-slate-950 md:ml-[280px]"
        style={{
          backgroundImage: 'radial-gradient(circle, #334155 1px, transparent 1px)',
          backgroundSize: '24px 24px',
        }}
      >
        <div className="sticky top-0 z-20 border-b border-slate-700 bg-slate-900 px-4 py-4 backdrop-blur md:px-8 md:py-5">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <button
                type="button"
                aria-label="Open sidebar"
                onClick={() => setSidebarOpen(true)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 hover:text-white md:hidden"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
              <h1 className="text-2xl font-semibold tracking-tight text-white">{title}</h1>
            </div>
            <button type="button" onClick={() => setAddOpen(true)}
              className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 shadow-sm transition hover:bg-cyan-400">
              Add Job
            </button>
          </div>
        </div>
        <div className="p-4 md:p-8">
          <Outlet />
        </div>
      </main>
      <AddJobForm isOpen={addOpen} onClose={() => setAddOpen(false)} onCreated={handleCreated} />
    </div>
  );
}
