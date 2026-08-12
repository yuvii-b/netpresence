import React, { useState, useRef, useEffect } from 'react';
import { ToneEncoder } from '../audio/toneEncoder';
import { startSession, connectWebSocket } from '../services/api';

export default function TeacherDashboard() {
  const [token, setToken] = useState('A7X');
  const [sessionId] = useState('SESS-101');
  const [isEmitting, setIsEmitting] = useState(false);
  const [students, setStudents] = useState([]);
  const encoderRef = useRef(new ToneEncoder());

  useEffect(() => {
    const ws = connectWebSocket((data) => {
      if (data.type === 'ATTENDANCE_RECORDED') {
        setStudents((prev) => [...new Set([...prev, data.student_id])]);
      }
    });
    return () => ws.close();
  }, []);

  const handleStartEmit = async () => {
    await startSession(sessionId, token);
    setIsEmitting(true);
    encoderRef.current.playing = true;

    const loop = async () => {
      if (encoderRef.current.playing) {
        const duration = await encoderRef.current.playToken(token);
        setTimeout(loop, duration + 400); // small pause before repeating
      }
    };
    loop();
  };

  const handleStopEmit = () => {
    setIsEmitting(false);
    encoderRef.current.stop();
    encoderRef.current = new ToneEncoder(); // fresh instance for next session
  };

  return (
    <div style={{ padding: '20px', border: '1px solid #ccc', borderRadius: '8px' }}>
      <h2>Teacher Dashboard</h2>
      <p>Session ID: <strong>{sessionId}</strong></p>
      <input
        type="text"
        maxLength={4}
        value={token}
        onChange={(e) => setToken(e.target.value.toUpperCase())}
        disabled={isEmitting}
      />
      <br /><br />
      {!isEmitting ? (
        <button onClick={handleStartEmit} style={{ padding: '10px 20px', background: 'green', color: '#fff' }}>
          Start Session & Emit Sound
        </button>
      ) : (
        <button onClick={handleStopEmit} style={{ padding: '10px 20px', background: 'red', color: '#fff' }}>
          Stop Session
        </button>
      )}

      <h3>Live Submissions ({students.length}):</h3>
      <ul>
        {students.map((st, i) => (
          <li key={i}>{st} - Present</li>
        ))}
      </ul>
    </div>
  );
}