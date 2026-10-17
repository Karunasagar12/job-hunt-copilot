import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import JobDetail from './pages/JobDetail.jsx';
import Analytics from './pages/Analytics.jsx';
import Contacts from './pages/Contacts.jsx';
import Pipeline from './pages/Pipeline.jsx';
import Shortlist from './pages/Shortlist.jsx';
import Today from './pages/Today.jsx';

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
      </Route>
    </Routes>
  );
}
