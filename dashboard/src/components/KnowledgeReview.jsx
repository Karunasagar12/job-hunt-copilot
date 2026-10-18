import { gapItems, removeAt, updateAchievement } from '../utils/knowledge.js';

const input = 'mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500';
const section = 'rounded-xl border border-slate-700 bg-slate-900 p-5';
const labelClass = 'block text-sm text-slate-300';
const listText = list => (list || []).join(', ');

function Field({ label, value, onChange, multiline = false }) {
  const Tag = multiline ? 'textarea' : 'input';
  return <label className={labelClass}>{label}<Tag className={input} value={value ?? ''} rows={multiline ? 3 : undefined} onChange={event => onChange(event.target.value)} /></label>;
}

function StringList({ label, values = [], onChange }) {
  return <Field label={label} value={listText(values)} onChange={value => onChange(value.split(',').map(item => item.trim()).filter(Boolean))} />;
}

export default function KnowledgeReview({ source = {}, onChange = () => {}, gapMode = false, answers = {}, onAnswer = () => {} }) {
  const career = source.career || {};
  function setCareer(key, value) { onChange({ ...source, career: { ...career, [key]: value } }); }
  function setList(key, list, index, value) { onChange({ ...source, [key]: list.map((item, i) => i === index ? { ...item, ...value } : item) }); }
  function removeList(key, list, index) { onChange({ ...source, [key]: removeAt(list, index) }); }
  function updateRole(index, patch) { setList('roles', source.roles || [], index, patch); }
  function updateRoleList(index, key, value) {
    onChange({ ...source, roles: (source.roles || []).map((role, i) => i === index ? { ...role, [key]: value } : role) });
  }
  function updateAchievementAt(roleIndex, achievementIndex, patch) {
    const roles = (source.roles || []).map((role, i) => i === roleIndex ? { ...role,
      achievements: (role.achievements || []).map((achievement, j) => j === achievementIndex ? { ...achievement, ...patch } : achievement),
    } : role);
    onChange({ ...source, roles });
  }
  function addItem(key, blank) { onChange({ ...source, [key]: [...(source[key] || []), blank] }); }
  if (gapMode) return <section className={section}>
    <h2 className="text-lg font-semibold text-white">Add missing numbers</h2>
    <div className="mt-4 space-y-4">{gapItems(source).map(item => <label key={item.id} className="block text-sm text-slate-300">At {item.company}: {item.text}. Do you have a number for this (users, %, time saved, $)? (optional)
      <textarea className={input} rows="2" value={answers[item.id] || ''} onChange={event => onAnswer(item.id, event.target.value)} />
    </label>)}</div>
  </section>;

  return <div className="space-y-5">
    <section className={section}><h2 className="mb-4 text-lg font-semibold text-white">Career</h2><div className="space-y-4">
      <Field label="Narrative" multiline value={career.narrative} onChange={v => setCareer('narrative', v)} />
      <Field label="Why looking now" multiline value={career.why_looking} onChange={v => setCareer('why_looking', v)} />
      <StringList label="Target roles" values={career.target_roles} onChange={v => setCareer('target_roles', v)} />
      <Field label="Headline variants (one per line; label: text)" multiline value={(career.headline_variants || []).map(x => `${x.label || ''}: ${x.text || ''}`).join('\n')} onChange={v => setCareer('headline_variants', v.split('\n').filter(Boolean).map(line => { const i = line.indexOf(':'); return i < 0 ? { label: '', text: line } : { label: line.slice(0, i).trim(), text: line.slice(i + 1).trim() }; }))} />
      <div className="grid gap-4 md:grid-cols-2">{[['notice_period','Notice period'],['target_compensation','Target compensation'],['work_authorization','Work authorization']].map(([key,label]) => <Field key={key} label={label} value={career[key]} onChange={v => setCareer(key,v)} />)}</div>
    </div></section>

    <section className={section}><h2 className="mb-4 text-lg font-semibold text-white">Roles</h2><div className="space-y-5">
      {(source.roles || []).map((role, ri) => <article key={role.company + role.title + ri} className="rounded-lg border border-slate-700 p-4"><div className="mb-3 flex justify-between"><h3 className="font-medium text-white">Role {ri + 1}</h3><button type="button" onClick={() => removeList('roles', source.roles, ri)} className="text-sm text-red-300">Remove role</button></div>
        <div className="grid gap-3 md:grid-cols-2">{[['company','Company'],['title','Title'],['location','Location'],['start','Start'],['end','End']].map(([key,label]) => <Field key={key} label={label} value={role[key]} onChange={v => updateRole(ri,{[key]:v})} />)}</div>
        <div className="mt-3 space-y-3"><Field label="Description" multiline value={role.description} onChange={v => updateRole(ri,{description:v})} /><Field label="Owned" multiline value={role.owned} onChange={v => updateRole(ri,{owned:v})} />
          <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={!!role.hidden} onChange={e => updateRole(ri,{hidden:e.target.checked})} />Hide from CV (skills only)</label>
          <div><h4 className="mb-2 text-sm font-medium text-slate-200">Achievements</h4><div className="space-y-3">{(role.achievements || []).map((achievement, ai) => <div key={achievement.id || ai} data-unverified={achievement.unverified ? 'true' : undefined} className={`rounded-lg border p-3 ${achievement.unverified ? 'border-amber-400/60 bg-amber-500/10' : 'border-slate-700'}`}>
            <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]"><Field label="Achievement" multiline value={achievement.text} onChange={v => updateAchievementAt(ri,ai,{text:v,unverified:false})} /><div className="space-y-3"><Field label="Metric" value={achievement.metric} onChange={v => updateAchievementAt(ri,ai,{metric:v,unverified:false})} /><Field label="Context" value={achievement.context} onChange={v => updateAchievementAt(ri,ai,{context:v,unverified:false})} /></div><button type="button" onClick={() => updateRoleList(ri,'achievements',removeAt(role.achievements || [],ai))} className="self-end text-sm text-red-300">Remove</button></div>
            {achievement.unverified && <div className="mt-2 flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-amber-200">We couldn't find this number in your CV — edit it or confirm it's correct</p><button type="button" onClick={() => onChange(updateAchievement(source,achievement.id,{unverified:false}))} className="rounded-lg border border-amber-400/50 px-3 py-2 text-sm text-amber-100">This number is correct</button></div>}
          </div>)}<button type="button" onClick={() => updateRoleList(ri,'achievements',[...(role.achievements || []),{id:`new-${Date.now()}`,text:'',metric:'',context:'',needs_metric:false,unverified:false}])} className="text-sm text-cyan-300">Add achievement</button></div></div>
          <StringList label="Technologies" values={role.technologies} onChange={v => updateRoleList(ri,'technologies',v)} /><StringList label="Keywords" values={role.keywords} onChange={v => updateRoleList(ri,'keywords',v)} />
        </div></article>)}
      <button type="button" onClick={() => addItem('roles',{company:'',title:'',location:'',start:'',end:'',description:'',owned:'',hidden:false,achievements:[],technologies:[],keywords:[]})} className="text-sm text-cyan-300">Add role</button>
    </div></section>

    {['education','projects'].map(key => { const isEducation = key === 'education'; const label = isEducation ? 'Education' : 'Projects'; const fields = isEducation ? [['degree','Degree'],['school','School'],['dates','Dates'],['detail','Detail']] : [['name','Name'],['context','Context'],['text','Description']]; return <section key={key} className={section}><h2 className="mb-4 text-lg font-semibold text-white">{label}</h2><div className="space-y-3">{(source[key] || []).map((item,i) => <div key={i} className="rounded-lg border border-slate-700 p-3"><div className="mb-2 flex justify-between"><strong className="text-sm text-slate-200">{label} {i+1}</strong><button type="button" onClick={() => removeList(key,source[key],i)} className="text-sm text-red-300">Remove</button></div><div className="grid gap-3 md:grid-cols-2">{fields.map(([field,name]) => <Field key={field} label={name} value={item[field]} onChange={v => setList(key,source[key],i,{[field]:v})} />)}</div></div>)}<button type="button" onClick={() => addItem(key,isEducation?{degree:'',school:'',dates:'',detail:''}:{name:'',context:'',text:''})} className="text-sm text-cyan-300">Add {label.toLowerCase()}</button></div></section>; })}

    <section className={section}><h2 className="mb-4 text-lg font-semibold text-white">Skills</h2><div className="space-y-3">{Object.entries(source.skills || {}).map(([category, values]) => <div key={category} className="grid gap-3 md:grid-cols-[12rem_1fr_auto]"><Field label="Category" value={category} onChange={name => { const skills = { ...source.skills }; delete skills[category]; skills[name] = values; onChange({ ...source, skills }); }} /><StringList label="Skills" values={values} onChange={next => onChange({ ...source, skills: { ...source.skills, [category]: next } })} /><button type="button" onClick={() => { const skills={...source.skills};delete skills[category];onChange({...source,skills}); }} className="self-end text-sm text-red-300">Remove</button></div>)}<button type="button" onClick={() => onChange({...source,skills:{...(source.skills||{}),'New category':[]}})} className="text-sm text-cyan-300">Add category</button></div></section>
    <section className={section}><h2 className="mb-4 text-lg font-semibold text-white">Certifications</h2><div className="space-y-3">{(source.certifications || []).map((item,i) => <div key={i} className="flex items-end gap-3"><Field label={`Certification ${i+1}`} value={item} onChange={v => onChange({...source,certifications:source.certifications.map((x,j)=>j===i?v:x)})} /><button type="button" onClick={() => onChange({...source,certifications:removeAt(source.certifications,i)})} className="pb-2 text-sm text-red-300">Remove</button></div>)}<button type="button" onClick={() => addItem('certifications','')} className="text-sm text-cyan-300">Add certification</button></div></section>
  </div>;
}
