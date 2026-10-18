import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchProfile, saveProfile, fetchProfileSource, saveProfileSource } from '../api.js';
import ProfileForm from '../components/ProfileForm.jsx';
import RegionEditor from '../components/RegionEditor.jsx';
import KnowledgeReview from '../components/KnowledgeReview.jsx';
import { unverifiedIds } from '../utils/knowledge.js';
import { updateProfileRegions } from '../utils/regions.js';

const panel = 'rounded-xl border border-slate-700 bg-slate-900 p-5 md:p-6';
const button = 'rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50';

function browserRegion() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  if (['Asia/Dubai','Asia/Riyadh','Asia/Qatar'].includes(tz)) return 'gcc';
  if (tz === 'Asia/Kolkata') return 'india';
  if (tz === 'Europe/London') return 'uk';
  if (tz.startsWith('America/')) return 'us';
  if (tz.startsWith('Europe/')) return 'eu';
  return 'eu';
}

export default function Profile() {
  const [tab, setTab] = useState('about');
  const [profile, setProfile] = useState(null);
  const [presets, setPresets] = useState([]);
  const [source, setSource] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState({});
  const [notice, setNotice] = useState(null);
  useEffect(() => {
    let active = true;
    Promise.all([fetchProfile(), fetchProfileSource(), fetch('/api/profile/region-presets').then(async res => { if (!res.ok) throw new Error('Could not load region presets'); return res.json(); })])
      .then(([saved, knowledge, regionPresets]) => {
        if (!active) return;
        const p = saved || { name: '', email: '', linkedin: '', github: '', headline: '', signoff_name: '', signoff_title: '', timezone: '', regions: [], default_region: '', target_titles: [], target_locations: [], extra_agencies: [], photo: '' };
        p.timezone = p.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
        if (!saved) p.regions = [regionPresets.find(region => region.id === browserRegion()) || regionPresets.find(region => region.id === 'eu')].filter(Boolean).map(region => ({ ...region, phone: '', location: '' }));
        if (!p.default_region && p.regions.length) p.default_region = p.regions[0].id;
        setProfile(p); setSource(knowledge); setPresets(regionPresets);
      }).catch(error => { if (active) setNotice({ ok: false, text: error.message }); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  async function saveAbout() {
    setBusy(true); setNotice(null); setErrors({});
    try {
      const result = await saveProfile(profile); setProfile(result); setNotice({ ok: true, text: 'Profile saved.' });
    } catch (error) { if (error.field) setErrors({ [error.field]: error.message }); setNotice({ ok: false, text: error.message }); }
    finally { setBusy(false); }
  }
  async function saveKnowledge() {
    setBusy(true); setNotice(null);
    try { setSource(await saveProfileSource(source)); setNotice({ ok: true, text: 'Career knowledge saved.' }); }
    catch (error) {
      if (error.status === 400) {
        const ids = error.unverified || unverifiedIds(source);
        setNotice({ ok: false, text: `${ids.length} ${ids.length === 1 ? 'number needs' : 'numbers need'} confirming.` });
        setTimeout(() => document.querySelector('[data-unverified="true"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0);
      } else setNotice({ ok: false, text: error.message });
    } finally { setBusy(false); }
  }
  if (loading) return <div className="text-sm text-slate-400">Loading profile…</div>;
  if (!profile) return <div role="alert" className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-red-200">{notice?.text || 'Could not load your profile.'}</div>;
  return <div className="space-y-5">
    <div className="flex gap-2 border-b border-slate-700" role="tablist" aria-label="Profile sections">
      {[['about','About you'],['knowledge','Career knowledge']].map(([id,label]) => <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => { setTab(id); setNotice(null); }} className={`border-b-2 px-4 py-3 text-sm font-medium ${tab === id ? 'border-cyan-400 text-cyan-300' : 'border-transparent text-slate-400'}`}>{label}</button>)}
    </div>
    {tab === 'about' ? <section className={`${panel} space-y-6`}>
      <ProfileForm value={profile} onChange={setProfile} errors={errors} />
      <RegionEditor regions={profile.regions || []} defaultRegion={profile.default_region} presets={presets} errors={errors} onChange={(regions, default_region) => setProfile(current => updateProfileRegions(current, regions, default_region))} />
      <div className="flex flex-wrap items-center gap-3"><button type="button" disabled={busy} onClick={saveAbout} className={button}>{busy ? 'Saving…' : 'Save profile'}</button>{notice && <span role="status" className={`text-sm ${notice.ok ? 'text-emerald-300' : 'text-red-300'}`}>{notice.text}</span>}</div>
    </section> : source == null ? <section className={panel}><h2 className="text-lg font-semibold text-white">Build your career knowledge</h2><p className="mt-2 text-sm text-slate-400">Upload your CV to create an editable career profile.</p><Link className="mt-4 inline-block rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950" to="/setup?step=cv">Upload your CV to build this</Link></section> : <>
      <KnowledgeReview source={source} onChange={setSource} />
      <div className="flex flex-wrap items-center gap-3"><button type="button" disabled={busy} onClick={saveKnowledge} className={button}>{busy ? 'Saving…' : 'Save career knowledge'}</button><Link className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800" to="/setup?step=cv">Upload a new CV</Link>{notice && <span role="status" className={`text-sm ${notice.ok ? 'text-emerald-300' : 'text-red-300'}`}>{notice.text}</span>}</div>
    </>}
  </div>;
}
