import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import JobDetail from './pages/JobDetail.jsx';
import Analytics from './pages/Analytics.jsx';
import Contacts from './pages/Contacts.jsx';
import Pipeline from './pages/Pipeline.jsx';
import Shortlist from './pages/Shortlist.jsx';
import Today from './pages/Today.jsx';
import Settings from './pages/Settings.jsx';
import Profile from './pages/Profile.jsx';
import Setup from './pages/Setup.jsx';
import SetupGate from './components/SetupGate.jsx';

export default function App() {
  return (
    <Routes>
      <Route path="/setup" element={<Setup />} />
      <Route element={<SetupGate><Layout /></SetupGate>}>
        <Route index element={<Navigate to="/pipeline" replace />} />
        <Route path="/pipeline" element={<Pipeline />} />
        <Route path="/job/:id" element={<JobDetail />} />
        <Route path="/today" element={<Today />} />
        <Route path="/shortlist" element={<Shortlist />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
