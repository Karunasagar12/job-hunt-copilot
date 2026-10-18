import { Link, Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import JobDetail from './pages/JobDetail.jsx';
import Analytics from './pages/Analytics.jsx';
import Contacts from './pages/Contacts.jsx';
import Pipeline from './pages/Pipeline.jsx';
import Shortlist from './pages/Shortlist.jsx';
import Today from './pages/Today.jsx';

function ComingSoon({ title }) {
  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-6 text-slate-300">
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <p className="mt-2">This page is being set up. Return to the pipeline and try again shortly.</p>
      <Link className="mt-4 inline-block text-cyan-400 underline" to="/pipeline">Go to Pipeline</Link>
    </section>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/pipeline" replace />} />
        <Route path="/pipeline" element={<Pipeline />} />
        <Route path="/job/:id" element={<JobDetail />} />
        <Route path="/today" element={<Today />} />
        <Route path="/shortlist" element={<Shortlist />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/profile" element={<ComingSoon title="Profile" />} />
        <Route path="/settings" element={<ComingSoon title="Settings" />} />
      </Route>
    </Routes>
  );
}
