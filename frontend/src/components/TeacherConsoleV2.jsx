import { useCallback, useEffect, useRef, useState } from 'react';
import { v2, getTeacherToken, setTeacherToken } from '../services/api';

const STATUS_COLOR = { PRESENT: '#1b7f3b', FLAGGED: '#b26a00', ABSENT: '#a11' };

export default function TeacherConsoleV2() {
  const [token, setToken] = useState(getTeacherToken());
  const [room, setRoom] = useState('');
  const [session, setSession] = useState(null);
  const [roster, setRoster] = useState({});            // student_id -> name
  const [checkedIn, setCheckedIn] = useState([]);      // student_ids in arrival order
  const [reports, setReports] = useState(0);
  const [seeds, setSeeds] = useState([]);              // confirmed on server
  const [pick, setPick] = useState(new Set());         // pending selection
  const [result, setResult] = useState(null);
  const [now, setNow] = useState(() => Date.now());
  const [msg, setMsg] = useState('');
  const wsRef = useRef(null);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);

  useEffect(() => () => wsRef.current?.close(), []);

  const onEvent = useCallback((e) => {
    if (e.type === 'CHECKIN') setCheckedIn((p) => (p.includes(e.student_id) ? p : [...p, e.student_id]));
    else if (e.type === 'REPORT') setReports((n) => n + 1);
    else if (e.type === 'SEEDS') setSeeds(e.student_ids);
    else if (e.type === 'RESULT') setResult(e);
    else if (e.type === 'ADJUDICATED') {
      setResult((r) => r && { ...r, rows: r.rows.map((x) => (x.student_id === e.student_id ? { ...x, status: e.status, decided_by: 'teacher' } : x)) });
    }
  }, []);

  const guard = async (fn) => {
    setMsg('');
    try { await fn(); } catch (err) { setMsg(err.status === 401 ? 'Wrong or missing teacher token.' : err.message); }
  };

  const start = () => guard(async () => {
    setTeacherToken(token);
    const [s, studs] = await Promise.all([v2.start({ room }), v2.students()]);
    setRoster(Object.fromEntries(studs.map((x) => [x.student_id, x.name])));
    setSession(s); setCheckedIn([]); setReports(0); setSeeds([]); setPick(new Set()); setResult(null);
    wsRef.current?.close();
    wsRef.current = v2.socket(s.session_id, onEvent);
  });

  const confirmSeeds = () => guard(async () => { await v2.verifySeeds(session.session_id, [...pick]); });
  const closeAndCompute = () => guard(async () => { setResult(await v2.close(session.session_id)); });
  const adjudicate = (id, status) => guard(async () => { await v2.adjudicate(session.session_id, id, status); });

  const secsLeft = session ? Math.max(0, Math.round((session.window_ends_at * 1000 - now) / 1000)) : 0;
  const togglePick = (id) => setPick((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <div className="card">
      <h2>Teacher Console (proximity graph)</h2>
      {!session || result ? (
        <div className="row">
          <input type="password" placeholder="Teacher token" value={token} onChange={(e) => setToken(e.target.value)} />
          <input placeholder="Room (optional)" value={room} onChange={(e) => setRoom(e.target.value)} />
          <button className="primary" onClick={start}>{result ? 'Start new session' : 'Start roll call'}</button>
        </div>
      ) : null}
      {msg && <p className="err">{msg}</p>}

      {session && (
        <>
          <p>Session <strong>{session.session_id}</strong> — students open the NetPresence app and tap <em>Mark me present</em>.
            {' '}{secsLeft > 0 ? <>Discovery window: <strong>{secsLeft}s</strong></> : <strong>Window closed</strong>}
            {' '}· reports received: {reports}</p>

          <h3>Checked in ({checkedIn.length})</h3>
          <p className="hint">Tick the students sitting on the front bench whom you can see, then confirm. They anchor the flood.</p>
          <ul className="plain">
            {checkedIn.map((id) => (
              <li key={id}>
                <label>
                  <input type="checkbox" disabled={!!result} checked={pick.has(id) || seeds.includes(id)} onChange={() => togglePick(id)} />
                  {' '}{roster[id] || id} <span className="hint">({id})</span>{seeds.includes(id) && <b> ✓ verified</b>}
                </label>
              </li>
            ))}
          </ul>
          {!result && (
            <div className="row">
              <button onClick={confirmSeeds} disabled={pick.size === 0}>Confirm {pick.size} verified</button>
              <button className="primary" onClick={closeAndCompute} disabled={seeds.length === 0}>Close &amp; compute attendance</button>
            </div>
          )}
        </>
      )}

      {result && (
        <>
          <h3>Result</h3>
          <p>
            {Object.entries(result.counts).map(([k, v]) => <span key={k} style={{ color: STATUS_COLOR[k], marginRight: 12 }}><b>{v}</b> {k}</span>)}
            {result.edges != null && <span className="hint">· {result.edges} admitted links</span>}
          </p>
          <table>
            <thead><tr><th>Student</th><th>Status</th><th>Hops</th><th>Path m</th><th>By</th><th /></tr></thead>
            <tbody>
              {result.rows.map((r) => (
                <tr key={r.student_id}>
                  <td>{r.name} <span className="hint">({r.student_id})</span></td>
                  <td style={{ color: STATUS_COLOR[r.status], fontWeight: 600 }}>{r.status}</td>
                  <td>{r.hops ?? '–'}</td><td>{r.path_m ?? '–'}</td><td>{r.decided_by}</td>
                  <td>
                    {r.status === 'FLAGGED' && (
                      <>
                        <button onClick={() => adjudicate(r.student_id, 'PRESENT')}>Present</button>
                        <button onClick={() => adjudicate(r.student_id, 'ABSENT')}>Absent</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint">FLAGGED = checked in on the phone but not corroborated by enough nearby students; you decide.</p>
        </>
      )}
    </div>
  );
}
