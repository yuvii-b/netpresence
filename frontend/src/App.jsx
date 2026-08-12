import React from 'react';
import TeacherDashboard from './components/TeacherDashboard';
import StudentScanner from './components/StudentScanner';

export default function App() {
  return (
    <div style={{ maxWidth: '600px', margin: '0 auto', fontFamily: 'sans-serif' }}>
      <h1>NetPresence Demo</h1>
      <TeacherDashboard />
      <StudentScanner />
    </div>
  );
}