import { useCallback, useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { fetchIntegrations, fetchScheduler, fetchSettings, saveSettings } from '../api.js';
import IntegrationCard from '../components/IntegrationCard.jsx';
import LlmSettings from '../components/LlmSettings.jsx';

const fieldClass = 'mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500';
const ORDER = ['agentmail', 'gmail', 'fullenrich', 'apify', 'firecrawl'];

function formatTime(value) { return value ? new Date(value).toLocaleString() : '—'; }

export default function Settings() {
  const location = useLocation();
  const [settings, setSettings] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [integrations, setIntegrations] = useState([]);
  const [scheduler, setScheduler] = useState([]);
  const [schedule, setSchedule] = useState(null);
  const [toast, setToast] = useState('');
  const [scheduleNotice, setScheduleNotice] = useState(null);
  const [savingSchedule, setSavingSchedule] = useState(false);

  const reloadIntegrations = useCallback(() => fetchIntegrations().then(setIntegrations).catch(err => setToast(err.message)), []);
  const reloadScheduler = useCallback(() => fetchScheduler().then(setScheduler).catch(() => setScheduler([])), []);
  const reloadSettings = useCallback(() => fetchSettings().then(data => {
    setSettings(data.settings || {}); setSchedule(data.settings?.schedule || {}); setLoadError(data.load_error || '');
  }).catch(err => setToast(err.message)), []);

  useEffect(() => { reloadSettings(); reloadIntegrations(); reloadScheduler(); }, [reloadSettings, reloadIntegrations, reloadScheduler]);
  useEffect(() => {
    if (new URLSearchParams(location.search).get('gmail') === 'connected') {
      setToast('Gmail connected'); reloadIntegrations(); window.history.replaceState({}, '', location.pathname);
    }
  }, [location.pathname, location.search, reloadIntegrations]);
  useEffect(() => { if (!toast) return undefined; const timeout = setTimeout(() => setToast(''), 5000); return () => clearTimeout(timeout); }, [toast]);

  async function saveSchedule() {
    setSavingSchedule(true); setScheduleNotice(null);
    try {
      const data = await saveSettings({ schedule: {
        inbox_scan: schedule.inbox_scan,
        job_sourcing: schedule.job_sourcing,
        gmail_sent_poll_minutes: Math.min(120, Math.max(5, Number(schedule.gmail_sent_poll_minutes) || 5)),
      } });
      setSettings(data.settings || settings); setSchedule(data.settings?.schedule || schedule);
      setScheduleNotice({ ok: true, text: 'Schedule saved.' }); reloadScheduler();
    } catch (err) { setScheduleNotice({ ok: false, text: err.message }); }
    finally { setSavingSchedule(false); }
  }
  function changeSchedule(key, value) { setSchedule(current => ({ ...(current || {}), [key]: value })); }

  const orderedIntegrations = ORDER.map(id => integrations.find(item => item.id === id)).filter(Boolean);
  const config = settings?.integrations || {};
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      {toast && <div role="status" className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">{toast}</div>}
      <LlmSettings value={settings?.llm} loadError={loadError} onSaved={reloadSettings} />

      <section>
        <div className="mb-4"><h2 className="text-lg font-semibold text-white">Integrations</h2><p className="mt-1 text-sm text-slate-400">Connect optional services used for email, research, and job sourcing.</p></div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {orderedIntegrations.map(integration => <IntegrationCard key={integration.id} integration={integration} config={config[integration.id] || {}} onChange={() => { reloadIntegrations(); reloadSettings(); reloadScheduler(); }} />)}
        </div>
      </section>

      <section className="rounded-xl border border-slate-700 bg-slate-900 p-5 md:p-6">
        <h2 className="text-lg font-semibold text-white">Schedule</h2>
        <p className="mt-1 text-sm text-slate-400">Set local times for inbox scans and job sourcing.</p>
        <div className="mt-5 grid gap-4 md:grid-cols-3">
          <label className="text-sm text-slate-300">Inbox scan
            <input className={fieldClass} type="time" value={schedule?.inbox_scan || ''} onChange={e => changeSchedule('inbox_scan', e.target.value)} />
          </label>
          <label className="text-sm text-slate-300">Job sourcing
            <input className={fieldClass} type="time" value={schedule?.job_sourcing || ''} onChange={e => changeSchedule('job_sourcing', e.target.value)} />
          </label>
          <label className="text-sm text-slate-300">Gmail sent poll (minutes)
            <input className={fieldClass} type="number" min="5" max="120" value={schedule?.gmail_sent_poll_minutes ?? 15} onChange={e => changeSchedule('gmail_sent_poll_minutes', e.target.value)} />
          </label>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button type="button" onClick={saveSchedule} disabled={savingSchedule} className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50">{savingSchedule ? 'Saving…' : 'Save schedule'}</button>
          {scheduleNotice && <span role="status" className={`text-sm ${scheduleNotice.ok ? 'text-emerald-300' : 'text-red-300'}`}>{scheduleNotice.text}</span>}
        </div>
      </section>

      <section className="rounded-xl border border-slate-700 bg-slate-900 p-5 md:p-6">
        <div className="mb-4"><h2 className="text-lg font-semibold text-white">Background jobs</h2><p className="mt-1 text-sm text-slate-400">Recent and upcoming scheduled work.</p></div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-700 text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500"><tr>{['Job', 'Enabled', 'Last run', 'Next run', 'Result'].map(label => <th className="px-3 py-3 font-medium" key={label}>{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-800 text-slate-300">
              {scheduler.map(job => <tr key={job.id}>
                <td className="px-3 py-3 font-medium text-white">{job.id.replace(/_/g, ' ')}</td>
                <td className="px-3 py-3">{job.enabled ? 'Yes' : 'No'}</td>
                <td className="px-3 py-3">{formatTime(job.last_run)}</td>
                <td className="px-3 py-3">{formatTime(job.next_run)}</td>
                <td className="px-3 py-3">{job.last_result ? (job.last_result.ok ? 'Success' : `Failed${job.last_result.exit_code != null ? ` (${job.last_result.exit_code})` : ''}`) : '—'}</td>
              </tr>)}
              {!scheduler.length && <tr><td colSpan="5" className="px-3 py-5 text-center text-slate-500">No scheduler data available.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
