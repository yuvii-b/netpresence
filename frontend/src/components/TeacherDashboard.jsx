import React, { useState, useRef, useEffect } from 'react';
import { ToneEncoder } from '../audio/toneEncoder';
import { startSession, stopSession, connectWebSocket } from '../services/api';

function generateSessionId() {
  return `SESS-${Date.now().toString(36).toUpperCase()}`;
}

export default function TeacherDashboard() {
  const [token, setToken] = useState('A7X');
  const [sessionId, setSessionId] = useState(null);
  const [isEmitting, setIsEmitting] = useState(false);
  const [students, setStudents] = useState([]);
  const encoderRef = useRef(new ToneEncoder());
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  useEffect(() => {
    const ws = connectWebSocket((data) => {
      if (data.type === 'ATTENDANCE_RECORDED' && data.session_id === sessionIdRef.current) {
        setStudents((prev) => [...new Set([...prev, data.student_id])]);
      }
    });
    return () => ws.close();
  }, []);

  const handleStartEmit = async () => {
    // iOS Safari only unlocks the AudioContext when it is created/resumed
    // synchronously inside the user-gesture (click). Do this BEFORE any await —
    // the network round-trip below would otherwise end the gesture window and
    // leave the speaker permanently muted on iOS.
    await encoderRef.current.initContext();

    const newSessionId = generateSessionId();
    await startSession(newSessionId, token);
    setSessionId(newSessionId);
    setStudents([]);
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
    if (sessionId) stopSession(sessionId);
  };

  return (
    <div style={{ padding: '20px', border: '1px solid #ccc', borderRadius: '8px' }}>
      <h2>Teacher Dashboard</h2>
      <p>Session ID: <strong>{sessionId || 'Not started'}</strong></p>
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