const STYLES = {
  new:        'bg-slate-700 text-slate-300',
  generating: 'bg-blue-500/20 text-blue-300',
  cv_ready:   'bg-cyan-500/20 text-cyan-300',
  applied:    'bg-cyan-500/10 text-cyan-400',
  sent:       'bg-amber-500/20 text-amber-300 ring-1 ring-inset ring-amber-500/40',
  reply:      'bg-green-500/20 text-green-300 ring-1 ring-inset ring-green-500/40',
  interview:  'bg-purple-500/20 text-purple-300 ring-1 ring-inset ring-purple-500/40',
  offer:      'bg-emerald-500/20 text-emerald-300 ring-1 ring-inset ring-emerald-500/40',
  rejected:   'bg-red-500/20 text-red-400',
  withdrawn:  'bg-slate-700 text-slate-400',
  failed:     'bg-red-500/20 text-red-400',
};

const LABELS = {
  new: 'New', generating: 'Generating', cv_ready: 'CV Ready', applied: 'Applied',
  sent: 'Sent', reply: 'Reply', interview: 'Interview', offer: 'Offer',
  rejected: 'Rejected', withdrawn: 'Withdrawn', failed: 'Failed',
};

export default function StatusBadge({ status = 'new' }) {
  const key = status || 'new';
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${STYLES[key] || STYLES.new}`}>
      {key === 'generating' && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-300" />}
      {LABELS[key] || key}
    </span>
  );
}
