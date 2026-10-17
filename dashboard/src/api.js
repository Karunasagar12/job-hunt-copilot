const API_BASE = '/api';

async function parseResponse(res) {
  if (!res.ok) {
    const text = await res.text();
    let msg = `Request failed: ${res.status}`;
    try { msg = JSON.parse(text).error || msg; } catch { msg = text || msg; }
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.headers.get('content-type')?.includes('application/json') ? res.json() : res.text();
}

function q(filters = {}) {
  const p = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => { if (v != null && v !== '') p.set(k, v); });
  const s = p.toString();
  return s ? `?${s}` : '';
}

export async function fetchJobs(filters = {}) {
  const data = await parseResponse(await fetch(`${API_BASE}/jobs${q(filters)}`));
  return Array.isArray(data) ? data : [];
}

export async function fetchJob(id) {
  return parseResponse(await fetch(`${API_BASE}/jobs/${id}`));
}

export async function createJob(data) {
  return parseResponse(await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }));
}

export async function updateJob(id, data) {
  return parseResponse(await fetch(`${API_BASE}/jobs/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }));
}

export async function deleteJob(id) {
  return parseResponse(await fetch(`${API_BASE}/jobs/${id}`, { method: 'DELETE' }));
}

export async function pollJobStatus(id) {
  return parseResponse(await fetch(`${API_BASE}/jobs/${id}/status`));
}

export async function fetchStats() {
  return parseResponse(await fetch(`${API_BASE}/stats`));
}

export async function downloadCV(id) {
  const res = await fetch(`${API_BASE}/jobs/${id}/cv`);
  if (!res.ok) { await parseResponse(res); return; }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const disposition = res.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || `job-${id}-cv.pdf`;
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

export async function downloadCoverLetter(id) {
  const res = await fetch(`${API_BASE}/jobs/${id}/cover-letter/pdf`);
  if (!res.ok) { await parseResponse(res); return; }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const disposition = res.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || `job-${id}-cover-letter.pdf`;
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

// ── CONTACTS ─────────────────────────────────────────────────────────────────

export async function fetchContacts(jobId) {
  return parseResponse(await fetch(`${API_BASE}/jobs/${jobId}/contacts`));
}

export async function addContact(jobId, data) {
  return parseResponse(await fetch(`${API_BASE}/jobs/${jobId}/contacts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }));
}

export async function updateContact(id, data) {
  return parseResponse(await fetch(`${API_BASE}/contacts/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }));
}

export async function deleteContact(id) {
  return parseResponse(await fetch(`${API_BASE}/contacts/${id}`, { method: 'DELETE' }));
}

export async function markReplied(id) {
  return parseResponse(await fetch(`${API_BASE}/contacts/${id}/replied`, { method: 'POST' }));
}

export async function bounceContact(id) {
  return parseResponse(await fetch(`${API_BASE}/contacts/${id}/bounced`, { method: 'POST' }));
}

export async function skipContactOutreach(id) {
  return parseResponse(await fetch(`${API_BASE}/contacts/${id}/skip`, { method: 'POST' }));
}

export async function getContactEmail(contactId) {
  return parseResponse(await fetch(`${API_BASE}/contacts/${contactId}/get-email`, { method: 'POST' }));
}

export async function matchLinkedIn(linkedinUrl) {
  return parseResponse(await fetch(`${API_BASE}/contacts/match-linkedin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ linkedin_url: linkedinUrl }),
  }));
}

export async function fetchAllContacts() {
  return parseResponse(await fetch(`${API_BASE}/contacts/all`));
}

// ── OUTREACH ──────────────────────────────────────────────────────────────────

export async function startOutreach(jobId) {
  return parseResponse(await fetch(`${API_BASE}/jobs/${jobId}/outreach/start`, { method: 'POST' }));
}

export async function fetchDueFollowups(date) {
  const qs = date ? `?date=${date}` : '';
  return parseResponse(await fetch(`${API_BASE}/outreach/due${qs}`));
}

export async function fetchInboxDigest() {
  return parseResponse(await fetch(`${API_BASE}/inbox-digest`));
}

export async function confirmCascade(contactId) {
  return parseResponse(await fetch(`${API_BASE}/inbox-digest/contact/${contactId}/confirm-cascade`, { method: 'POST' }));
}

export async function fetchDigestThread(contactId) {
  return parseResponse(await fetch(`${API_BASE}/inbox-digest/contact/${contactId}/thread`));
}

export async function dismissDigestContact(contactId) {
  return parseResponse(await fetch(`${API_BASE}/inbox-digest/contact/${contactId}/dismiss`, { method: 'POST' }));
}

export async function dismissDigestMessages(messageIds) {
  return parseResponse(await fetch(`${API_BASE}/inbox-digest/dismiss`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_ids: messageIds }),
  }));
}

export async function createGmailDraft(outreachId) {
  return parseResponse(await fetch(`${API_BASE}/outreach/${outreachId}/gmail-draft`, { method: 'POST' }));
}

export async function prepareOutreach(id) {
  return parseResponse(await fetch(`${API_BASE}/outreach/${id}/prepare`, { method: 'POST' }));
}

export async function sendOutreach(id, fingerprint) {
  return parseResponse(await fetch(`${API_BASE}/outreach/${id}/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fingerprint }),
  }));
}

export async function checkOutreachStatus(id) {
  return parseResponse(await fetch(`${API_BASE}/outreach/${id}/check-status`, { method: 'POST' }));
}

export async function retryOutreach(id) {
  return parseResponse(await fetch(`${API_BASE}/outreach/${id}/retry`, { method: 'POST' }));
}

export async function dismissUncertainOutreach(id) {
  return parseResponse(await fetch(`${API_BASE}/outreach/${id}/dismiss-uncertain`, { method: 'POST' }));
}

export async function batchCreateDrafts(ids) {
  return parseResponse(await fetch(`${API_BASE}/outreach/batch-draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  }));
}

export async function skipOutreach(id) {
  return parseResponse(await fetch(`${API_BASE}/outreach/${id}/skip`, { method: 'POST' }));
}

export async function markOutreachSent(id) {
  return parseResponse(await fetch(`${API_BASE}/outreach/${id}/sent`, { method: 'POST' }));
}

export async function editOutreach(id, data) {
  return parseResponse(await fetch(`${API_BASE}/outreach/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }));
}

export async function redraftOutreach(id, feedback = '') {
  return parseResponse(await fetch(`${API_BASE}/outreach/${id}/redraft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback }),
  }));
}

// ── ANALYTICS ─────────────────────────────────────────────────────────────────

export async function fetchFunnel() {
  return parseResponse(await fetch(`${API_BASE}/stats/funnel`));
}

export async function fetchGeoStats(geo) {
  return parseResponse(await fetch(`${API_BASE}/stats/geo/${geo}`));
}

// ── COMPANY PROFILE ────────────────────────────────────────────────────────────

export async function fetchCompanyProfile(id) {
  return parseResponse(await fetch(`${API_BASE}/jobs/${id}/company-profile`));
}

export async function fetchSalaryEstimate(id, { refresh = false } = {}) {
  const qs = refresh ? '?refresh=true' : '';
  return parseResponse(await fetch(`${API_BASE}/jobs/${id}/salary-estimate${qs}`));
}

export async function fetchSourcedJobs(filters = {}) {
  const data = await parseResponse(await fetch(`${API_BASE}/sourced-jobs${q(filters)}`));
  return Array.isArray(data) ? data : [];
}

export async function fetchLatestSourcingRun() {
  return parseResponse(await fetch(`${API_BASE}/sourced-jobs/runs/latest`));
}

export async function approveSourcedJob(id) {
  return parseResponse(await fetch(`${API_BASE}/sourced-jobs/${id}/approve`, { method: 'POST' }));
}

export async function passSourcedJob(id, reason = null) {
  return parseResponse(await fetch(`${API_BASE}/sourced-jobs/${id}/pass`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(reason ? { reason } : {}),
  }));
}
