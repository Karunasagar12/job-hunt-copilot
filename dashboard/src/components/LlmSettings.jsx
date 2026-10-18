import { useEffect, useState } from 'react';
import { fetchSettings, saveSettings, testLlm } from '../api.js';
import { initialLlmSetupState, llmSetupReducer } from '../utils/llmSetup.js';

const MODELS = {
  anthropic: ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5'],
  openrouter: ['anthropic/claude-sonnet-5.5', 'anthropic/claude-opus-4.6', 'openai/gpt-5'],
  bedrock: ['us.anthropic.claude-opus-4-6-v1'],
};
const PROVIDERS = [
  ['anthropic', 'Anthropic (recommended)'],
  ['openrouter', 'OpenRouter (any model)'],
  ['openai_compatible', 'Custom OpenAI-compatible (OpenAI, Ollama, …)'],
  ['bedrock', 'AWS Bedrock (advanced)'],
];
const fieldClass = 'mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500';

export default function LlmSettings({ onSaved = () => {}, onTested = () => {}, compact = false, requireSaveBeforeTest = false, value: suppliedValue, loadError: suppliedLoadError }) {
  const [llm, setLlm] = useState(suppliedValue || null);
  const [loadError, setLoadError] = useState(suppliedLoadError || '');
  const [apiKey, setApiKey] = useState('');
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState('');
  const [wizardTest, setWizardTest] = useState(initialLlmSetupState);

  useEffect(() => {
    if (suppliedValue) setLlm(suppliedValue);
  }, [suppliedValue]);
  useEffect(() => {
    if (suppliedLoadError !== undefined) setLoadError(suppliedLoadError || '');
  }, [suppliedLoadError]);
  useEffect(() => {
    if (suppliedValue) return;
    let active = true;
    fetchSettings().then(data => {
      if (active) { setLlm(data.settings?.llm || {}); setLoadError(data.load_error || ''); }
    }).catch(err => { if (active) setNotice({ ok: false, text: err.message }); });
    return () => { active = false; };
  }, [suppliedValue]);

  function change(field, next) {
    setLlm(current => ({ ...(current || {}), [field]: next }));
    setWizardTest(current => llmSetupReducer(current, { type: 'edit' }));
    onTested(false);
  }
  function changeApiKey(next) {
    setApiKey(next);
    setWizardTest(current => llmSetupReducer(current, { type: 'edit' }));
    onTested(false);
  }
  async function save() {
    setBusy('save'); setNotice(null);
    const config = { ...llm };
    if (apiKey.trim()) config.api_key = apiKey.trim();
    else delete config.api_key;
    try {
      const data = await saveSettings({ llm: config });
      setLlm(data.settings?.llm || { ...llm, api_key: '' }); setApiKey('');
      setWizardTest(current => llmSetupReducer(current, { type: 'saved' }));
      if (requireSaveBeforeTest) onTested(false);
      setNotice({ ok: true, text: 'AI settings saved.' }); onSaved();
    } catch (err) { setNotice({ ok: false, text: err.message }); }
    finally { setBusy(''); }
  }
  async function test() {
    setBusy('test'); setNotice(null);
    try {
      const result = await testLlm();
      setNotice({ ok: !!result.ok, text: result.ok ? 'Connected' : (result.message || 'Connection failed') });
      setWizardTest(current => llmSetupReducer(current, { type: 'tested', ok: !!result.ok }));
      onTested(requireSaveBeforeTest ? !!result.ok && wizardTest.saved : !!result.ok);
    } catch (err) {
      setWizardTest(current => llmSetupReducer(current, { type: 'tested', ok: false }));
      onTested(false);
      setNotice({ ok: false, text: err.message });
    }
    finally { setBusy(''); }
  }

  const provider = llm?.provider || 'anthropic';
  const listId = `llm-models-${provider}`;
  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-5 md:p-6">
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-white">AI model</h2>
        {!compact && <p className="mt-1 text-sm text-slate-400">Choose the model used to tailor your application materials.</p>}
      </div>
      {loadError && <div role="alert" className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">Your settings file was unreadable; defaults are in use. Saving will back it up and start fresh.</div>}
      <div className={`grid gap-4 ${compact ? '' : 'md:grid-cols-2'}`}>
        <label className="text-sm text-slate-300">Provider
          <select className={fieldClass} value={provider} disabled={!!busy} onChange={e => change('provider', e.target.value)}>
            {PROVIDERS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
        <label className="text-sm text-slate-300">Model
          <input className={fieldClass} disabled={!!busy} value={llm?.model || ''} list={listId} onChange={e => change('model', e.target.value)} placeholder="Enter a model name" />
          <datalist id={listId}>{(MODELS[provider] || []).map(model => <option key={model} value={model} />)}</datalist>
        </label>
        <label className="text-sm text-slate-300">API key
          <input className={fieldClass} disabled={!!busy} type="password" autoComplete="new-password" value={apiKey} onChange={e => changeApiKey(e.target.value)} placeholder={llm?.api_key || ''} />
          <span className="mt-1 block text-xs text-slate-500">Leave blank to keep the saved key.</span>
        </label>
        {provider === 'openai_compatible' && <label className="text-sm text-slate-300">Base URL
          <input className={fieldClass} disabled={!!busy} value={llm?.base_url || ''} onChange={e => change('base_url', e.target.value)} placeholder="http://localhost:11434/v1" />
        </label>}
        {provider === 'bedrock' && <label className="text-sm text-slate-300">AWS region
          <input className={fieldClass} disabled={!!busy} value={llm?.aws_region || ''} onChange={e => change('aws_region', e.target.value)} placeholder="us-east-1" />
          <span className="mt-1 block text-xs text-slate-500">Uses your AWS credentials from environment variables. See docs/integrations/bedrock.md.</span>
        </label>}
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button type="button" onClick={save} disabled={!!busy} className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50">{busy === 'save' ? 'Saving…' : 'Save'}</button>
        <button type="button" onClick={test} disabled={!!busy || (requireSaveBeforeTest && !wizardTest.saved)} className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-800 disabled:opacity-50">{busy === 'test' ? 'Testing…' : 'Test connection'}</button>
        {notice && <span role="status" className={`text-sm ${notice.ok ? 'text-emerald-300' : 'text-red-300'}`}>{notice.text}</span>}
      </div>
    </section>
  );
}
