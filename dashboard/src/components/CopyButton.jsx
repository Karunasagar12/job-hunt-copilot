import { useEffect, useState } from 'react';
import { copyToClipboard } from '../utils/clipboard.js';

export default function CopyButton({ text = '', label = 'Copy' }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);

  async function handleCopy() {
    try {
      await copyToClipboard(text);
      setCopied(true);
    } catch {
      // Silent fail — button state stays unchanged
    }
  }

  return (
    <button type="button" onClick={handleCopy}
      className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition hover:bg-slate-600 hover:text-white ${
        copied ? 'border-cyan-500/50 bg-slate-700 text-cyan-400' : 'border-slate-600 bg-slate-700 text-slate-300'
      }`}>
      {copied ? 'Copied!' : label}
    </button>
  );
}
