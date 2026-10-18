import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { prepareOutreach, sendOutreach } from '../api.js';
import useIntegrations from '../hooks/useIntegrations.js';
import { integrationErrorMessage } from '../utils/integrations.js';

export default function ReviewSendDrawer({ entry, onClose, onSent, onUncertain, onRequestRedraft }) {
  const { isConnected } = useIntegrations();
  const agentmailOk = isConnected('agentmail');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [prepared, setPrepared] = useState(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!agentmailOk) {
      setLoading(false);
      setError('Connect AgentMail in Settings');
      setPrepared(null);
      return () => { cancelled = true; };
    }
    setLoading(true);
    setError('');
    prepareOutreach(entry.id)
      .then(data => { if (!cancelled) setPrepared(data); })
      .catch(e => { if (!cancelled) setError(integrationErrorMessage(e, 'Failed to prepare for review.')); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [entry.id, agentmailOk]);

  async function handleSend() {
    if (!prepared || !prepared.can_send) return;
    setSending(true);
    setError('');
    try {
      const result = await sendOutreach(entry.id, prepared.fingerprint);
      if (result.status === 'uncertain') {
        onUncertain?.();
      } else {
        onSent?.();
      }
      onClose();
    } catch (e) {
      setError(integrationErrorMessage(e, 'Send failed.'));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-gray-950/30">
      <div className="h-full w-full max-w-2xl overflow-y-auto bg-white shadow-2xl">
        <div className="sticky top-0 flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
          <h3 className="text-lg font-semibold text-gray-950">Review and Send</h3>
          <button type="button" onClick={onClose} className="text-gray-500 hover:text-gray-700">Close</button>
        </div>

        <div className="space-y-4 p-6">
          {loading && <p className="text-sm text-gray-500">Preparing…</p>}
          {error && <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
          {!agentmailOk && <Link to="/settings" className="text-sm text-indigo-700 underline">Connect AgentMail in Settings</Link>}

          {prepared && !loading && (
            <>
              <div className="text-sm text-gray-500">
                <p><span className="font-medium text-gray-700">From:</span> {prepared.from_address}</p>
                <p><span className="font-medium text-gray-700">To:</span> {entry.contact_email}</p>
                {prepared.cv_filename && (
                  <p className="mt-1">
                    <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                      CV attached: {prepared.cv_filename}
                    </span>
                  </p>
                )}
                {entry.sequence_num !== 1 && (
                  <p className="mt-1 text-xs text-gray-400">Reply in thread with this contact's Email 1.</p>
                )}
                {!prepared.can_send && (
                  <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
                    {prepared.cannot_send_reason} You can review now, but Send is disabled until this clears.
                  </p>
                )}
              </div>
              <div>
                <p className="text-sm font-medium text-gray-700">Subject</p>
                <p className="mt-1 text-sm text-gray-900">{prepared.subject}</p>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-700">Body</p>
                <div className="mt-1 rounded-lg border border-gray-200 p-4 text-sm text-gray-900"
                  dangerouslySetInnerHTML={{ __html: prepared.body }} />
              </div>
            </>
          )}
        </div>

        <div className="sticky bottom-0 flex gap-2 border-t border-gray-200 bg-white px-6 py-4">
          <button type="button" disabled={!agentmailOk || !prepared || sending || !prepared.can_send} onClick={handleSend}
            title={prepared && !prepared.can_send ? prepared.cannot_send_reason : undefined}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60">
            {sending && <span className="h-4 w-4 animate-spin rounded-full border-2 border-gray-200 border-t-white" />}
            Send
          </button>
          <button type="button" onClick={() => { onRequestRedraft?.(); onClose(); }}
            className="rounded-lg bg-amber-500 px-3 py-1.5 text-sm font-medium text-slate-950 hover:bg-amber-400">
            Request Redraft
          </button>
          <button type="button" onClick={onClose}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
