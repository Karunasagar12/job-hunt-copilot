import { useState } from 'react';
import { disconnectGmail, saveIntegration, testIntegration, uploadGmailCredentials } from '../api.js';

const FIELDS = {
  agentmail: [{ key: 'api_key', label: 'API key', secret: true }, { key: 'inbox_id', label: 'Inbox ID' }],
  fullenrich: [{ key: 'api_key', label: 'API key', secret: true }],
  apify: [{ key: 'api_token', label: 'API token', secret: true }],
  firecrawl: [{ key: 'api_key', label: 'API key', secret: true }],
};
const fieldClass = 'mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500';
const statusStyle = {
  connected: 'bg-emerald-500/15 text-emerald-300',
  error: 'bg-red-500/15 text-red-300',
  not_connected: 'bg-slate-700 text-slate-300',
};
const statusLabel = { connected: 'Connected', error: 'Error', not_connected: 'Not connected' };

export default function IntegrationCard({ integration = {}, config = {}, onChange = () => {} }) {
  const [values, setValues] = useState({});
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState(null);
  const id = integration.id;
  const isGmail = id === 'gmail';
  const status = integration.state || 'not_connected';
  const helpUrl = `https://github.com/karunasagar12/job-hunt-copilot/blob/main/${integration.docs_url || `docs/integrations/${id}.md`}`;

  function change(key, value) { setValues(current => ({ ...current, [key]: value })); }
  async function save() {
    setBusy('save'); setNotice(null);
    const data = {};
    for (const { key } of FIELDS[id] || []) if (values[key]?.trim()) data[key] = values[key].trim();
    if (id === 'apify') data.max_charge_usd = Math.min(5, Math.max(0, Number(values.max_charge_usd ?? config.max_charge_usd ?? 5)));
    if (isGmail) data.enabled = true;
    try { await saveIntegration(id, data); setValues(current => ({ ...current, api_key: '', api_token: '' })); setNotice({ ok: true, text: 'Saved.' }); onChange(); }
    catch (err) { setNotice({ ok: false, text: err.message }); }
    finally { setBusy(''); }
  }
  async function test() {
    setBusy('test'); setNotice(null);
    try { const result = await testIntegration(id); setNotice({ ok: !!result.ok, text: result.message || (result.ok ? 'Connected' : 'Connection failed') }); onChange(); }
    catch (err) { setNotice({ ok: false, text: err.message }); }
    finally { setBusy(''); }
  }
  async function upload(file) {
    if (!file) return;
    setBusy('upload'); setNotice(null);
    try { await uploadGmailCredentials(file); setNotice({ ok: true, text: 'Credentials uploaded.' }); onChange(); }
    catch (err) { setNotice({ ok: false, text: err.message }); }
    finally { setBusy(''); }
  }
  async function disconnect() {
    setBusy('disconnect'); setNotice(null);
    try { await disconnectGmail(); setNotice({ ok: true, text: 'Gmail disconnected.' }); onChange(); }
    catch (err) { setNotice({ ok: false, text: err.message }); }
    finally { setBusy(''); }
  }

  return (
    <article className="rounded-xl border border-slate-700 bg-slate-900 p-5">
      <div className="flex items-start justify-between gap-3">
        <div><h3 className="font-semibold text-white">{integration.label || id}</h3>{id === 'agentmail' && <p className="mt-1 text-xs text-cyan-300">Recommended way to send email</p>}</div>
        <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${statusStyle[status] || statusStyle.not_connected}`}>{statusLabel[status] || 'Not connected'}</span>
      </div>
      {status === 'error' && <p className="mt-3 text-sm text-red-300">{integration.message}</p>}
      <div className="mt-4 space-y-3">
        {isGmail ? <>
          <label className="block text-sm text-slate-300">Upload credentials.json
            <input className={`${fieldClass} file:mr-3 file:rounded file:border-0 file:bg-slate-700 file:px-3 file:py-1 file:text-slate-200`} type="file" accept="application/json,.json" onChange={e => upload(e.target.files?.[0])} disabled={!!busy} />
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => { window.location = '/api/gmail/connect'; }} className="rounded-lg bg-cyan-500 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400">Connect Gmail</button>
            {status === 'connected' && <button type="button" onClick={disconnect} disabled={!!busy} className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">Disconnect</button>}
            <button type="button" onClick={test} disabled={!!busy} className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">Test</button>
          </div>
        </> : <>
          {(FIELDS[id] || []).map(({ key, label, secret }) => <label key={key} className="block text-sm text-slate-300">{label}
            <input className={fieldClass} type={secret ? 'password' : 'text'} autoComplete={secret ? 'new-password' : undefined} value={values[key] || ''} placeholder={config[key] || ''} onChange={e => change(key, e.target.value)} />
          </label>)}
          {id === 'apify' && <label className="block text-sm text-slate-300">Monthly budget (max $5)
            <input className={fieldClass} type="number" min="0" max="5" step="0.01" value={values.max_charge_usd ?? config.max_charge_usd ?? 5} onChange={e => change('max_charge_usd', e.target.value)} />
          </label>}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={save} disabled={!!busy} className="rounded-lg bg-cyan-500 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50">{busy === 'save' ? 'Saving…' : 'Save'}</button>
            <button type="button" onClick={test} disabled={!!busy} className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50">{busy === 'test' ? 'Testing…' : 'Test'}</button>
          </div>
        </>}
        {notice && <p role="status" className={`text-sm ${notice.ok ? 'text-emerald-300' : 'text-red-300'}`}>{notice.text}</p>}
      </div>
      <a className="mt-4 inline-block text-sm text-cyan-400 underline" href={helpUrl} target="_blank" rel="noreferrer">How to get this</a>
    </article>
  );
}
