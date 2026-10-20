import { useState, useRef, useEffect } from 'react';
import { ToneEncoder, ALPHABET } from '../audio/toneEncoder';
import { acoustic, getTeacherToken, setTeacherToken } from '../services/api';

function generateSessionId() {
  return `SESS-${Date.now().toString(36).toUpperCase()}`;
}

function sanitizeToken(raw) {
  return raw.toUpperCase().split('').filter((c) => ALPHABET.includes(c)).join('');
}

// v1 baseline: the teacher's speaker plays an FSK tone token; kept for the head-to-head evaluation.
export default function AcousticTeacher() {
  const [teacherToken, setToken] = useState(getTeacherToken());
  const [token, setTok] = useState('A7X');
  const [sessionId, setSessionId] = useState(null);
  const [isEmitting, setIsEmitting] = useState(false);
  const [students, setStudents] = useState([]);
  const [errorMsg, setErrorMsg] = useState('');
  const encoderRef = useRef(new ToneEncoder());
  const sessionIdRef = useRef(sessionId);
  const wsRef = useRef(null);

  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);
  useEffect(() => () => { wsRef.current?.close(); encoderRef.current.stop(); }, []);

  const handleStartEmit = async () => {
    setErrorMsg('');
    // iOS Safari only unlocks audio inside the click gesture: do this BEFORE any await.
    await encoderRef.current.initContext();
    setTeacherToken(teacherToken);

    const newSessionId = generateSessionId();
    try {
      await acoustic.start(newSessionId, token);
    } catch (err) {
      setErrorMsg(err.status === 401 ? 'Wrong or missing teacher token.' : `Could not start session: ${err.message}`);
      return;
    }

    wsRef.current?.close();
    wsRef.current = acoustic.socket((data) => {
      if (data.type === 'ATTENDANCE_RECORDED' && data.session_id === sessionIdRef.current) {
        setStudents((prev) => [...new Set([...prev, data.student_id])]);
      }
    });

    setSessionId(newSessionId);
    setStudents([]);
    setIsEmitting(true);
    encoderRef.current.playing = true;
    const loop = async () => {
      if (encoderRef.current.playing) {
        const duration = await encoderRef.current.playToken(token);
        setTimeout(loop, duration + 400);
      }
    };
    loop();
  };

  const handleStopEmit = () => {
    setIsEmitting(false);
    encoderRef.current.stop();
    encoderRef.current = new ToneEncoder();
    if (sessionId) acoustic.stop(sessionId).catch(() => {});
  };

  return (
    <div className="card">
      <h2>Acoustic v1 — Teacher</h2>
      <p>Session ID: <strong>{sessionId || 'Not started'}</strong></p>
      <div className="row">
        <input type="password" placeholder="Teacher token" value={teacherToken} onChange={(e) => setToken(e.target.value)} disabled={isEmitting} />
        <input type="text" maxLength={4} value={token} onChange={(e) => setTok(sanitizeToken(e.target.value))} disabled={isEmitting} />
        {errorMsg && <span className="err">{errorMsg}</span>}
        {!isEmitting
          ? <button className="primary" onClick={handleStartEmit}>Start session &amp; emit sound</button>
          : <button className="danger" onClick={handleStopEmit}>Stop session</button>}
      </div>
      <h3>Live submissions ({students.length})</h3>
      <ul className="plain">{students.map((st) => <li key={st}>{st} — present</li>)}</ul>
    </div>
  );
}
