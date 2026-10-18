import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { fetchSetupStatus } from '../api.js';
import { setupGateMode } from '../utils/setup.js';

export default function SetupGate({ children }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setStatus(null);
    setError('');
    let active = true;
    fetchSetupStatus().then(value => { if (active) setStatus(value); })
      .catch(err => { if (active) setError(err.message || 'Could not check setup status.'); });
    return () => { active = false; };
  }, [attempt]);
  const mode = setupGateMode(window.location.pathname, status, error);
  if (mode === 'loading') return <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-300"><p role="status">Checking setup…</p></main>;
  if (mode === 'error') return <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-950 px-5 text-slate-200"><p role="alert" className="max-w-lg text-center">Could not check setup status: {error}</p><button type="button" onClick={() => setAttempt(value => value + 1)} className="rounded-lg bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950">Retry</button></main>;
  if (mode === 'redirect') return <Navigate to="/setup" replace />;
  return children;
}
