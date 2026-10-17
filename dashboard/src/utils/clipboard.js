export async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text || '');
    return;
  }
  // Plain-HTTP deployment: execCommand is the only path, and it reports
  // failure by returning false rather than throwing.
  const el = document.createElement('textarea');
  el.value = text || '';
  el.style.position = 'fixed';
  el.style.opacity = '0';
  document.body.appendChild(el);
  el.focus();
  el.select();
  let copied = false;
  try { copied = document.execCommand('copy'); }
  finally { document.body.removeChild(el); }
  if (!copied) throw new Error('Copy failed — select the text and copy it manually.');
}
