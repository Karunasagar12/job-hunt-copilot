import { useState } from 'react';
import { copyToClipboard } from '../utils/clipboard.js';
import {
  LINKEDIN_NOTE_LIMIT, formatSentAt, isLinkedInProfileUrl, noteLength, noteText,
} from '../utils/linkedin.js';

// Free plan allows only a few personalized notes a month -- spend them where
// they matter most. Advisory only.
const NOTE_WORTHY_TYPES = new Set(['hiring_manager', 'executive']);

const secondaryBtn = 'rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60';
const primaryBtn = 'rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60';

export default function LinkedInConnectPanel({ entry, contact, email1Sent, pending, onMarkSent, onAddProfile }) {
  const [opened, setOpened] = useState(false);
  const [copyError, setCopyError] = useState('');

  if (entry.status === 'sent') {
    return <p className="mt-2 text-xs text-green-700">Request sent {formatSentAt(entry.sent_at)}</p>;
  }
  if (entry.status !== 'draft') return null;

  const note = noteText(entry.content);
  const length = noteLength(note);
  const tooLong = length > LINKEDIN_NOTE_LIMIT;
  const url = (contact.linkedin_url || '').trim();
  const hasProfile = isLinkedInProfileUrl(url);

  async function handleConnect() {
    // No preventDefault: the <a target="_blank"> opens the profile natively,
    // so popup blockers never apply. The copy runs in the same click.
    setCopyError(''); setOpened(true);
    try { await copyToClipboard(note); }
    catch { setCopyError('Profile opened, but the note could not be copied — use Copy, or select the note above.'); }
  }

  function handleOpenOnly() {
    setCopyError(''); setOpened(true);
  }

  return (
    <div className="mt-2 space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        {note && (
          <span className={tooLong ? 'font-medium text-red-600' : 'text-gray-500'}>
            {length} / {LINKEDIN_NOTE_LIMIT}{tooLong && ' — too long for a free-plan note, use Edit to trim'}
          </span>
        )}
        <span className="text-gray-500">
          {NOTE_WORTHY_TYPES.has(contact.contact_type) ? 'Worth a note' : 'Fine without a note'}
        </span>
        {!email1Sent && <span className="text-amber-600">Email 1 not sent yet — the note mentions it</span>}
      </div>

      <div className="flex flex-wrap gap-2">
        {hasProfile ? (
          <>
            {note ? (
              <a href={url} target="_blank" rel="noopener noreferrer" onClick={handleConnect} className={primaryBtn}>
                Connect on LinkedIn
              </a>
            ) : (
              <button type="button" disabled title="No note to copy — use Open LinkedIn" className={primaryBtn}>
                Connect on LinkedIn
              </button>
            )}
            <a href={url} target="_blank" rel="noopener noreferrer" onClick={handleOpenOnly} className={secondaryBtn}>
              Open LinkedIn
            </a>
          </>
        ) : (
          <button type="button" onClick={onAddProfile} className={secondaryBtn}>
            Add LinkedIn profile
          </button>
        )}
        {!opened && (
          <button type="button" disabled={pending} onClick={onMarkSent} className={secondaryBtn}>
            Mark request sent
          </button>
        )}
      </div>

      {opened && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm text-indigo-900">
          <span>Request sent?</span>
          <button type="button" disabled={pending} onClick={onMarkSent}
            className="rounded-lg bg-indigo-600 px-3 py-1 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60">
            Yes
          </button>
          <button type="button" onClick={() => setOpened(false)}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50">
            Not yet
          </button>
        </div>
      )}
      {copyError && <p className="text-xs text-red-600">{copyError}</p>}
    </div>
  );
}
