import { useRef, useState } from 'react';

const fieldClass = 'mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500';
const split = value => Array.isArray(value) ? value.join(', ') : (value || '');
const errorClass = 'mt-1 block text-xs text-red-300';

export default function ProfileForm({ value = {}, onChange = () => {}, errors = {} }) {
  const [photoVersion, setPhotoVersion] = useState(Date.now());
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoNotice, setPhotoNotice] = useState('');
  const inputRef = useRef(null);
  const timezone = value.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const fields = [
    ['name', 'Name'], ['email', 'Email'], ['linkedin', 'LinkedIn URL'], ['github', 'GitHub URL'],
    ['headline', 'Professional headline'], ['signoff_name', 'Sign-off name'],
    ['signoff_title', 'Sign-off title'], ['timezone', 'Timezone'],
  ];
  function change(key, next) { onChange({ ...value, [key]: next }); }
  async function photoRequest(method, file) {
    setPhotoBusy(true); setPhotoNotice('');
    try {
      let response;
      if (method === 'POST') { const data = new FormData(); data.append('photo', file); response = await fetch('/api/profile/photo', { method, body: data }); }
      else response = await fetch('/api/profile/photo', { method });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) { const error = new Error(payload.error || payload.message || 'Photo update failed'); error.field = payload.field; throw error; }
      if (payload.profile) onChange({ ...value, ...payload.profile });
      else if (Object.hasOwn(payload, 'photo')) onChange({ ...value, photo: payload.photo });
      else if (method === 'DELETE') onChange({ ...value, photo: '' });
      setPhotoVersion(Date.now()); setPhotoNotice(method === 'DELETE' ? 'Photo removed.' : 'Photo updated.');
    } catch (error) { setPhotoNotice(error.message); }
    finally { setPhotoBusy(false); if (inputRef.current) inputRef.current.value = ''; }
  }
  const photoUrl = value.photo ? `/api/profile/photo?ts=${photoVersion}` : '';
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center gap-4">
      {photoUrl ? <img src={photoUrl} alt="Profile" className="h-20 w-20 rounded-full object-cover" /> : <div aria-label="No profile photo" className="flex h-20 w-20 items-center justify-center rounded-full bg-slate-800 text-2xl text-slate-400">{value.name?.trim()?.[0]?.toUpperCase() || '?'}</div>}
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={photoBusy} onClick={() => inputRef.current?.click()} className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">{photoBusy ? 'Working…' : 'Upload photo'}</button>
        {value.photo && <button type="button" disabled={photoBusy} onClick={() => photoRequest('DELETE')} className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">Remove photo</button>}
        <input ref={inputRef} hidden type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" onChange={event => photoRequest('POST', event.target.files?.[0])} />
      </div>
      {(errors.photo || photoNotice) && <span role="status" className={errors.photo ? errorClass : 'text-xs text-slate-400'}>{errors.photo || photoNotice}</span>}
    </div>
    <div className="grid gap-4 md:grid-cols-2">
      {fields.map(([key, label]) => <label key={key} className="text-sm text-slate-300">{label}
        <input className={fieldClass} type={key === 'email' ? 'email' : 'text'} value={key === 'timezone' ? timezone : (value[key] || '')} onChange={event => change(key, event.target.value)} />
        {errors[key] && <span className={errorClass}>{errors[key]}</span>}
      </label>)}
      {[['target_titles', 'Target job titles'], ['target_locations', 'Target locations'], ['extra_agencies', 'Extra agencies']].map(([key, label]) => <label key={key} className="text-sm text-slate-300">{label}
        <input className={fieldClass} value={split(value[key])} onChange={event => change(key, event.target.value.split(',').map(item => item.trim()).filter(Boolean))} placeholder="Separate values with commas" />
        {errors[key] && <span className={errorClass}>{errors[key]}</span>}
      </label>)}
    </div>
  </div>;
}
