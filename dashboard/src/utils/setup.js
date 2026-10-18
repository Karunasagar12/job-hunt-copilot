export const STEPS = ['llm', 'profile', 'regions', 'cv', 'integrations', 'done'];

function flag(key) {
  try { return globalThis.localStorage?.getItem(key) === '1'; } catch { return false; }
}

export function setFlag(key) {
  try { globalThis.localStorage?.setItem(key, '1'); } catch { /* Private windows may not persist wizard progress. */ }
}

export function firstIncompleteStep(status = {}, profile) {
  if (!status.llm) return 'llm';
  if (!status.profile) return 'profile';
  if ((profile?.regions?.length ?? 0) <= 1 && !flag('jhc.regionsConfirmed')) return 'regions';
  if (!status.knowledge) return 'cv';
  if (!flag('jhc.integrationsSeen')) return 'integrations';
  return 'done';
}

export const shouldGate = (pathname, status) => !status?.complete && pathname !== '/setup';

export function setupGateMode(pathname, status, error = '') {
  if (error) return 'error';
  if (!status) return 'loading';
  return shouldGate(pathname, status) ? 'redirect' : 'content';
}
