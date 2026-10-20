import { useState } from 'react';
import TeacherConsoleV2 from './components/TeacherConsoleV2';
import AcousticTeacher from './components/AcousticTeacher';
import AcousticStudent from './components/AcousticStudent';
import TrialsSummary from './components/TrialsSummary';

const TABS = [
  ['v2', 'Teacher (v2 proximity)'],
  ['a-teacher', 'Acoustic v1: teacher'],
  ['a-student', 'Acoustic v1: student'],
  ['trials', 'Acoustic v1: trials'],
];

export default function App() {
  const [tab, setTab] = useState('v2');
  return (
    <div className="app">
      <h1>NetPresence</h1>
      <p className="hint">v2 students use the NetPresence mobile app (see <code>mobile/</code>). The acoustic tabs are the v1 baseline.</p>
      <nav>{TABS.map(([id, label]) => (
        <button key={id} className={tab === id ? 'tab active' : 'tab'} onClick={() => setTab(id)}>{label}</button>
      ))}</nav>
      {tab === 'v2' && <TeacherConsoleV2 />}
      {tab === 'a-teacher' && <AcousticTeacher />}
      {tab === 'a-student' && <AcousticStudent />}
      {tab === 'trials' && <TrialsSummary />}
    </div>
  );
}
