import { useMemo, useState } from 'react';

const fieldClass = 'mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500';
const csv = value => Array.isArray(value) ? value.join(', ') : '';
const parseCsv = value => value.split(',').map(item => item.trim()).filter(Boolean);

export default function RegionEditor({ regions = [], defaultRegion = '', presets = [], errors = {}, onChange = () => {} }) {
  const [choice, setChoice] = useState('');
  const used = new Set(regions.map(region => region.id));
  const available = useMemo(() => presets.filter(region => !used.has(region.id)), [presets, regions]);
  function update(next, nextDefault = defaultRegion) { onChange(next, nextDefault); }
  function add() {
    if (choice === 'custom') {
      const id = `custom_${Date.now().toString(36)}`;
      update([...regions, { id, label: 'Custom region', phone: '', location: '', keywords: [], salary_sites: [] }]);
    } else {
      const preset = presets.find(region => region.id === choice);
      if (preset) update([...regions, { ...preset, phone: '', location: '' }]);
    }
    setChoice('');
  }
  function edit(index, field, value) {
    update(regions.map((region, i) => i === index ? { ...region, [field]: value } : region));
  }
  function remove(index) {
    const next = regions.filter((_, i) => i !== index);
    const fallback = next.some(region => region.id === defaultRegion) ? defaultRegion : next[0]?.id;
    update(next, fallback);
  }
  function move(index, offset) {
    const target = index + offset;
    if (target < 0 || target >= regions.length) return;
    const next = [...regions]; [next[index], next[target]] = [next[target], next[index]]; update(next);
  }
  return <section className="space-y-4">
    <div><h3 className="font-semibold text-white">Job regions</h3><p className="mt-1 text-sm text-slate-400">Job descriptions are matched against these regions top to bottom. Put the most specific places first.</p></div>
    <div className="flex flex-wrap gap-2">
      <select aria-label="Choose region to add" className={`${fieldClass} max-w-xs`} value={choice} onChange={event => setChoice(event.target.value)}>
        <option value="">Add region…</option>
        {available.map(region => <option key={region.id} value={region.id}>{region.label}</option>)}
        <option value="custom">Custom…</option>
      </select>
      <button type="button" disabled={!choice} onClick={add} className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50">Add region</button>
    </div>
    {errors.regions && <p className="text-xs text-red-300" role="alert">{errors.regions}</p>}
    <div className="space-y-4">
      {regions.map((region, index) => <article key={region.id} className="rounded-xl border border-slate-700 bg-slate-900 p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-200"><input type="radio" name="defaultRegion" checked={defaultRegion === region.id} onChange={() => update(regions, region.id)} />Default</label>
          <strong className="text-white">{region.label || region.id}</strong>
          <div className="ml-auto flex gap-2">
            <button type="button" aria-label={`Move ${region.label} up`} disabled={index === 0} onClick={() => move(index, -1)} className="rounded border border-slate-600 px-2 py-1 text-sm disabled:opacity-40">↑</button>
            <button type="button" aria-label={`Move ${region.label} down`} disabled={index === regions.length - 1} onClick={() => move(index, 1)} className="rounded border border-slate-600 px-2 py-1 text-sm disabled:opacity-40">↓</button>
            <button type="button" disabled={regions.length <= 1} onClick={() => remove(index)} className="rounded border border-slate-600 px-2 py-1 text-sm text-red-300 disabled:opacity-40">Remove</button>
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm text-slate-300">Label<input className={fieldClass} value={region.label || ''} onChange={event => edit(index, 'label', event.target.value)} /></label>
          <label className="text-sm text-slate-300">Phone<input className={fieldClass} value={region.phone || ''} onChange={event => edit(index, 'phone', event.target.value)} /></label>
          <label className="text-sm text-slate-300">Location<input className={fieldClass} value={region.location || ''} onChange={event => edit(index, 'location', event.target.value)} /></label>
          <label className="text-sm text-slate-300">Keywords<textarea className={fieldClass} rows="2" value={csv(region.keywords)} onChange={event => edit(index, 'keywords', parseCsv(event.target.value))} /></label>
          <label className="text-sm text-slate-300 md:col-span-2">Salary sites<input className={fieldClass} value={csv(region.salary_sites)} onChange={event => edit(index, 'salary_sites', parseCsv(event.target.value))} /></label>
        </div>
      </article>)}
    </div>
    {errors.default_region && <p className="text-xs text-red-300" role="alert">{errors.default_region}</p>}
  </section>;
}
