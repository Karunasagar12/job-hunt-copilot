export default function DedupWarning({ warning, onAddAnyway, onDismiss }) {
  if (!warning?.previous_job_company || !warning?.previous_job_role) return null;

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
      <p>
        Previously contacted at {warning.previous_job_company} for {warning.previous_job_role}
      </p>
      {onAddAnyway && onDismiss ? (
        <div className="mt-3 flex items-center gap-3">
          <button
            type="button"
            onClick={onAddAnyway}
            className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700"
          >
            Add Anyway
          </button>
          <button
            type="button"
            onClick={onDismiss}
            className="text-xs font-medium text-gray-600 hover:text-gray-900"
          >
            Cancel
          </button>
        </div>
      ) : null}
    </div>
  );
}
