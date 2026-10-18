const achievements = source => (source?.roles || []).flatMap(role =>
  (role.achievements || []).map(achievement => ({ ...achievement, company: role.company || '' })));

export const unverifiedIds = source => achievements(source).filter(item => item.unverified).map(item => item.id);
export const gapItems = source => achievements(source).filter(item => item.needs_metric)
  .map(({ id, company, text }) => ({ id, company, text }));

export function updateAchievement(source, id, patch) {
  return { ...source, roles: (source?.roles || []).map(role => ({ ...role,
    achievements: (role.achievements || []).map(item => item.id === id ? { ...item, ...patch } : item),
  })) };
}

export const removeAt = (list, index) => list.filter((_, current) => current !== index);

export function moveItem(list, from, to) {
  const result = [...list];
  if (from < 0 || from >= result.length || to < 0 || to >= result.length) return result;
  const [item] = result.splice(from, 1);
  result.splice(to, 0, item);
  return result;
}
