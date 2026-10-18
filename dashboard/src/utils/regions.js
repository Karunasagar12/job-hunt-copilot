export function regionLabel(regions, id) {
  if (!id) return '—';
  const region = (regions || []).find(item => item.id === id);
  return region ? region.label : String(id).toUpperCase();
}

export function regionOptions(regions, { includeAuto = false } = {}) {
  const options = (regions || []).map(region => ({ value: region.id, label: region.label }));
  return includeAuto && options.length
    ? [{ value: 'auto', label: 'Auto-detect' }, ...options]
    : options;
}

export function updateProfileRegions(profile, regions, defaultRegion) {
  return { ...profile, regions: [...regions], default_region: defaultRegion };
}
