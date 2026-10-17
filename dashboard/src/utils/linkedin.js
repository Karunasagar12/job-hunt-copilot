// LinkedIn free plan: personalized connection notes are capped at 200 characters.
export const LINKEDIN_NOTE_LIMIT = 200;

const PROFILE_RE = /^https?:\/\/([a-z]{2,3}\.)?linkedin\.com\/in\/[^/?#\s]+\/?([?#]\S*)?$/i;

export function isLinkedInProfileUrl(url) {
  return PROFILE_RE.test((url || '').trim());
}

// outreach_manager.py stores this placeholder when the drafter produced no
// content for a contact -- it must never be copied into a real invite.
const PLACEHOLDER_PREFIX = '[Outreach content not yet generated';

export function noteText(content) {
  const text = (content || '').trim();
  return text.startsWith(PLACEHOLDER_PREFIX) ? '' : text;
}

export function noteLength(text) {
  return [...text].length;
}

// Backend writes datetime.utcnow().isoformat() -- naive, but UTC.
export function formatSentAt(sentAt) {
  if (!sentAt) return '';
  const hasZone = /([zZ]|[+-]\d\d:\d\d)$/.test(sentAt);
  return new Date(hasZone ? sentAt : `${sentAt}Z`).toLocaleString();
}
