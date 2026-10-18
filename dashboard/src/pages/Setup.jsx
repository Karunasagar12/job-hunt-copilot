import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { fetchIntegrations, fetchProfile, fetchProfileSource, fetchRegionPresets, fetchSetupStatus, pollTask, saveProfile, saveProfileSource, startDraft, startGaps, uploadCv } from '../api.js';
import IntegrationCard from '../components/IntegrationCard.jsx';
import KnowledgeReview from '../components/KnowledgeReview.jsx';
import LlmSettings from '../components/LlmSettings.jsx';
import ProfileForm from '../components/ProfileForm.jsx';
import RegionEditor from '../components/RegionEditor.jsx';
import { setFlag, STEPS, firstIncompleteStep } from '../utils/setup.js';
import { updateProfileRegions } from '../utils/regions.js';
import { unverifiedIds } from '../utils/knowledge.js';

const titles = { llm: 'Connect an AI model', profile: 'About you', regions: 'Where are you applying?', cv: 'Build your career profile', integrations: 'Optional extras', done: "You're set up" };
const panel = 'rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-xl md:p-8';
const primary = 'rounded-lg bg-cyan-400 px-5 py-2.5 text-sm font-semibold text-slate-950 hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-40';
const secondary = 'rounded-lg border border-slate-600 px-5 py-2.5 text-sm font-medium text-slate-200 hover:bg-slate-800';

function presetForTimezone(tz) {
  if (['Asia/Dubai', 'Asia/Riyadh', 'Asia/Qatar'].includes(tz)) return 'gcc';
  if (tz === 'Asia/Kolkata') return 'india';
  if (tz === 'Europe/London') return 'uk';
  if (tz.startsWith('America/')) return 'us';
  return 'eu';
}

export default function Setup() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [step, setStep] = useState(null);
  const [profile, setProfile] = useState(null);
  const [presets, setPresets] = useState([]);
  const [source, setSource] = useState(null);
  const [integrations, setIntegrations] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [errors, setErrors] = useState({});
  const [llmTested, setLlmTested] = useState(false);
  const [uploadStage, setUploadStage] = useState('upload');
  const [cvFile, setCvFile] = useState(null);
  const [linkedinFile, setLinkedinFile] = useState(null);
  const [answers, setAnswers] = useState({});
  const [profileSourceLoaded, setProfileSourceLoaded] = useState(false);
  const alive = useRef(true);
  const statusRef = useRef(null);
  const requestedStep = params.get('step');

  useEffect(() => {
    alive.current = true;
    Promise.all([fetchSetupStatus(), fetchProfile(), fetchRegionPresets(), fetchIntegrations(), fetchProfileSource()])
      .then(([status, saved, regionPresets, extras, knowledge]) => {
        statusRef.current = status;
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
        const chosen = regionPresets.find(item => item.id === presetForTimezone(timezone)) || regionPresets.find(item => item.id === 'eu');
        const initial = saved || { name: '', email: '', linkedin: '', github: '', headline: '', signoff_name: '', signoff_title: '', timezone,
          regions: chosen ? [{ ...chosen, phone: '', location: '' }] : [], default_region: chosen?.id || '', target_titles: [], target_locations: [], extra_agencies: [], photo: '' };
        if (!saved) initial.phone = '';
        setProfile(initial); setPresets(regionPresets); setIntegrations(extras); setSource(knowledge); setProfileSourceLoaded(true);
        const start = STEPS.includes(requestedStep) ? requestedStep : firstIncompleteStep(status, initial);
        setStep(start);
        if (status.llm) setLlmTested(true);
      }).catch(err => setError(err.message || 'Could not load setup.'));
    return () => { alive.current = false; };
  }, []);

  const reloadIntegrations = useCallback(() => fetchIntegrations().then(setIntegrations).catch(err => setError(err.message)), []);

  async function runTask(taskId, message) {
    setNotice(message);
    while (alive.current) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      if (!alive.current) return null;
      const task = await pollTask(taskId);
      if (task.status === 'done') return task.result;
      if (task.status === 'error') throw new Error(task.error || 'The CV could not be processed.');
    }
    return null;
  }

  async function beginDraft() {
    setBusy(true); setError(''); setNotice('Uploading your CV…');
    try {
      await uploadCv(cvFile, linkedinFile);
      const task = await startDraft();
      const result = await runTask(task.task_id, 'Reading your CV… (this takes about a minute)');
      if (!result || !alive.current) return;
      setSource(result); setUploadStage('gaps'); setNotice('');
    } catch (err) {
      setError(err.message || 'The CV could not be processed.');
      if (/image|scanned|text pdf|export/i.test(err.message || '')) setUploadStage('upload');
    } finally { if (alive.current) setBusy(false); }
  }

  async function applyGaps() {
    setBusy(true); setError('');
    try {
      const task = await startGaps(source, answers);
      const result = await runTask(task.task_id, 'Adding your answers…');
      if (!result || !alive.current) return;
      setSource(result); setUploadStage('review'); setNotice('');
    } catch (err) { setError(err.message); }
    finally { if (alive.current) setBusy(false); }
  }

  async function saveCareerSource() {
    setBusy(true); setError('');
    try { setSource(await saveProfileSource(source)); setUploadStage('review'); setNotice('Career profile saved.'); }
    catch (err) {
      if (err.status === 400) {
        const ids = err.unverified || unverifiedIds(source);
        setError(`${ids.length} achievement number${ids.length === 1 ? ' needs' : 's need'} confirmation before saving.`);
      } else setError(err.message || 'Could not save career profile.');
    } finally { setBusy(false); }
  }

  async function saveAbout() {
    setBusy(true); setError(''); setErrors({});
    try {
      const saved = await saveProfile(profile); setProfile(saved); setStep('regions');
    } catch (err) { if (err.field) setErrors({ [err.field]: err.message }); setError(err.message || 'Could not save your profile.'); }
    finally { setBusy(false); }
  }

  async function saveRegions() {
    setBusy(true); setError(''); setErrors({});
    try { const saved = await saveProfile(profile); setProfile(saved); setFlag('jhc.regionsConfirmed'); setStep('cv'); }
    catch (err) { if (err.field) setErrors({ [err.field]: err.message }); setError(err.message || 'Could not save regions.'); }
    finally { setBusy(false); }
  }

  function advanceIntegrations() { setFlag('jhc.integrationsSeen'); setStep('done'); }

  if (!step || !profile || !profileSourceLoaded) return <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-300"><p role="status">Preparing your setup…</p></main>;
  const stepIndex = STEPS.indexOf(step);
  return <main className="min-h-screen bg-slate-950 px-4 py-8 text-slate-100 md:px-8">
    <div className="mx-auto max-w-4xl">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-3">
        <div><p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">Job Hunt Copilot</p><p className="mt-1 text-sm text-slate-400">Your information stays on this computer.</p></div>
        <span className="text-sm text-slate-400">Step {stepIndex + 1} of {STEPS.length}</span>
      </header>
      <div className="mb-8" aria-label={`Setup progress: step ${stepIndex + 1} of ${STEPS.length}`}><div className="h-2 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan-400 transition-all" style={{ width: `${((stepIndex + 1) / STEPS.length) * 100}%` }} /></div><div className="mt-3 grid grid-cols-6 gap-1">{STEPS.map((item, index) => <div key={item} className={`text-center text-[10px] capitalize sm:text-xs ${index <= stepIndex ? 'text-cyan-200' : 'text-slate-600'}`}>{{ llm: 'AI model', cv: 'Career profile' }[item] || item}</div>)}</div></div>
      <section className={panel}>
        <h1 className="mb-5 text-2xl font-semibold tracking-tight text-white md:text-3xl">{titles[step]}</h1>
        {error && <p role="alert" className="mb-5 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">{error}{step === 'cv' && <button type="button" className="ml-3 underline" onClick={() => { setError(''); setUploadStage('upload'); }}>Try again</button>}</p>}
        {notice && <p role="status" className="mb-5 text-sm text-cyan-200">{notice}</p>}

        {step === 'llm' && <div className="space-y-5"><p className="max-w-2xl text-sm leading-6 text-slate-300">This app uses an AI model to write your CV. You pay the provider directly, usually a few cents per job.</p><LlmSettings compact requireSaveBeforeTest onSaved={() => {}} onTested={setLlmTested} /></div>}
        {step === 'profile' && <div className="space-y-5"><p className="text-sm text-slate-400">Add the details you want on your job applications. You can leave phone and location blank for now.</p><ProfileForm value={profile} onChange={setProfile} errors={errors} /></div>}
        {step === 'regions' && <div className="space-y-5"><p className="text-sm text-slate-400">Choose the places where you want to find jobs. You can add more than one and reorder them.</p><RegionEditor regions={profile.regions || []} defaultRegion={profile.default_region} presets={presets} errors={errors} onChange={(regions, default_region) => setProfile(current => updateProfileRegions(current, regions, default_region))} /></div>}
        {step === 'cv' && <div className="space-y-5">
          {uploadStage === 'upload' && <><p className="text-sm leading-6 text-slate-300">Upload your CV to build an editable career profile. PDF and DOCX files up to 10 MB are supported.</p><label className="block text-sm text-slate-300">Your CV (required)<input className="mt-2 block w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-700 file:px-3 file:py-2 file:text-slate-100" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={e => setCvFile(e.target.files?.[0] || null)} /></label><label className="block text-sm text-slate-300">LinkedIn PDF (optional)<input className="mt-2 block w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-700 file:px-3 file:py-2 file:text-slate-100" type="file" accept=".pdf,application/pdf" onChange={e => setLinkedinFile(e.target.files?.[0] || null)} /></label><p className="text-xs text-slate-500">LinkedIn → your profile → More → Save to PDF</p></>}
          {uploadStage === 'gaps' && <><p className="text-sm text-slate-300">Add a number if you know one. You can skip this and fill in details later.</p><KnowledgeReview source={source || {}} onChange={setSource} gapMode answers={answers} onAnswer={(id, value) => setAnswers(current => ({ ...current, [id]: value }))} /></>}
          {uploadStage === 'review' && <><p className="text-sm text-slate-300">Review and edit your career information. Confirm or edit any highlighted numbers before saving.</p><KnowledgeReview source={source || {}} onChange={setSource} /></>}
        </div>}
        {step === 'integrations' && <div className="space-y-5"><p className="text-sm text-slate-300">All optional — you can do this later in Settings.</p><div className="grid gap-4 md:grid-cols-2">{['agentmail','gmail','fullenrich','apify','firecrawl'].map(id => { const integration = integrations.find(item => item.id === id); return integration ? <IntegrationCard key={id} integration={integration} onChange={reloadIntegrations} /> : null; })}</div></div>}
        {step === 'done' && <div className="space-y-5"><p className="text-slate-300">Your profile is ready. You can add a job now or adjust your preferences in Settings.</p><div className="flex flex-wrap gap-3"><button type="button" className={primary} onClick={() => navigate('/pipeline')}>Add your first job</button><button type="button" className={secondary} onClick={() => navigate('/settings')}>Go to Settings</button></div></div>}

        <footer className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-5">
          {step !== 'llm' && step !== 'done' ? <button type="button" className={secondary} disabled={busy} onClick={() => setStep(STEPS[Math.max(0, stepIndex - 1)])}>Back</button> : <span />}
          {step === 'llm' && <button type="button" className={primary} disabled={!llmTested} onClick={() => setStep('profile')}>Continue</button>}
          {step === 'profile' && <button type="button" className={primary} disabled={busy} onClick={saveAbout}>{busy ? 'Saving…' : 'Save and continue'}</button>}
          {step === 'regions' && <button type="button" className={primary} disabled={busy || !(profile.regions || []).length} onClick={saveRegions}>{busy ? 'Saving…' : 'Save and continue'}</button>}
          {step === 'cv' && uploadStage === 'upload' && <button type="button" className={primary} disabled={busy || !cvFile} onClick={beginDraft}>{busy ? 'Working…' : 'Upload and build profile'}</button>}
          {step === 'cv' && uploadStage === 'gaps' && <div className="flex flex-wrap gap-3"><button type="button" className={secondary} disabled={busy} onClick={() => setUploadStage('review')}>Skip</button><button type="button" className={primary} disabled={busy} onClick={applyGaps}>{busy ? 'Working…' : 'Add these numbers'}</button></div>}
          {step === 'cv' && uploadStage === 'review' && <button type="button" className={primary} disabled={busy} onClick={saveCareerSource}>{busy ? 'Saving…' : 'Save career profile'}</button>}
          {step === 'cv' && uploadStage === 'review' && notice === 'Career profile saved.' && <button type="button" className={primary} onClick={() => { setNotice(''); setStep('integrations'); }}>Continue</button>}
          {step === 'integrations' && <div className="flex flex-wrap gap-3"><button type="button" className={secondary} onClick={advanceIntegrations}>Skip for now</button><button type="button" className={primary} onClick={advanceIntegrations}>Continue</button></div>}
        </footer>
      </section>
      <p className="mt-5 text-center text-xs text-slate-500">You can change these details any time in your profile.</p>
    </div>
  </main>;
}
