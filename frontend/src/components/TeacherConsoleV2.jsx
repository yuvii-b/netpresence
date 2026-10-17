import { useCallback, useEffect, useRef, useState } from 'react';
import { v2, getTeacherToken, setTeacherToken } from '../services/api';

const STATUS_COLOR = { PRESENT: '#1b7f3b', FLAGGED: '#b26a00', ABSENT: '#a11' };
// Rows that need a teacher decision first (review, then flagged), then the rest.
const rank = (r) => (r.review ? 0 : r.status === 'FLAGGED' ? 1 : r.status === 'PRESENT' ? 2 : 3);

export default function TeacherConsoleV2() {
  const [token, setToken] = useState(getTeacherToken());
  const [room, setRoom] = useState('');
  const [kWit, setKWit] = useState('');                // blank = server default (2); 1 for small tests
  const [session, setSession] = useState(null);
  const [roster, setRoster] = useState({});            // student_id -> name
  const [checkedIn, setCheckedIn] = useState([]);      // student_ids in arrival order
  const [reports, setReports] = useState(0);
  const [seeds, setSeeds] = useState([]);              // confirmed on server
  const [pick, setPick] = useState(new Set());         // pending selection
  const [result, setResult] = useState(null);
  const [headcount, setHeadcount] = useState('');
  const [q, setQ] = useState('');
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
      setResult((r) => r && { ...r, rows: r.rows.map((x) => (x.student_id === e.student_id ? { ...x, status: e.status, decided_by: 'teacher', review: false } : x)) });
    }
  }, []);

  const guard = async (fn) => {
    setMsg('');
    try { await fn(); } catch (err) { setMsg(err.status === 401 ? 'Wrong or missing teacher token.' : err.message); }
  };

  const start = () => guard(async () => {
    setTeacherToken(token);
    const [s, studs] = await Promise.all([v2.start({ room, ...(kWit ? { k: Number(kWit) } : {}) }), v2.students()]);
    setRoster(Object.fromEntries(studs.map((x) => [x.student_id, x.name])));
    setSession(s); setQ(''); setCheckedIn([]); setReports(0); setSeeds([]); setPick(new Set()); setResult(null); setHeadcount('');
    wsRef.current?.close();
    wsRef.current = v2.socket(s.session_id, onEvent);
  });

  const confirmSeeds = () => guard(async () => { await v2.verifySeeds(session.session_id, [...pick]); });
  const closeAndCompute = () => guard(async () => { setResult(await v2.close(session.session_id, headcount)); });
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
          <input type="number" min="1" max="10" style={{ width: 150 }} placeholder="Witnesses k (default 2)" title="Use 1 only for tiny tests with 2-3 phones" value={kWit} onChange={(e) => setKWit(e.target.value)} />
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
          <p className="hint">Tick the students on the <b>front bench</b> (the middle column works best) whom you can see, then confirm. They anchor the flood.</p>
          <input type="search" placeholder="Search name or roll no." value={q} onChange={(e) => setQ(e.target.value)} style={{ width: '100%', boxSizing: 'border-box' }} />
          <ul className="plain">
            {checkedIn.filter((id) => pick.has(id) || seeds.includes(id) || `${id} ${roster[id] || ''}`.toLowerCase().includes(q.trim().toLowerCase())).map((id) => (
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
              <label>Heads in the room (optional) <input type="number" min="0" max="500" style={{ width: 80 }} value={headcount}
                onChange={(e) => setHeadcount(e.target.value)} /></label>
              <button onClick={confirmSeeds} disabled={pick.size === 0}>Confirm {pick.size} verified</button>
              <button className="primary" onClick={closeAndCompute} disabled={seeds.length === 0}>Close &amp; compute attendance</button>
            </div>
          )}
        </>
      )}

      {result && (
        <>
          <h3>Result</h3>
          <p data-testid="counts">
            {Object.entries(result.counts).map(([k, v]) => <span key={k} style={{ color: STATUS_COLOR[k], marginRight: 12 }}><b>{v}</b> {k}</span>)}
            {result.edges != null && <span className="hint">· {result.edges} admitted links</span>}
            {result.params && <span className="hint"> · link range {result.params.max_edge_m} m</span>}
          </p>
          {result.review > 0 && (
            <p className="warn">
              You counted {result.headcount} but {result.counts.PRESENT} are marked present. The {result.review} least-corroborated
              {' '}are highlighted below — look for anyone standing at the door or in the corridor.
            </p>
          )}
          <table>
            <thead><tr><th>Student</th><th>Status</th><th>Hops</th><th>Path m</th><th>By</th><th /></tr></thead>
            <tbody>
              {[...result.rows].sort((a, b) => rank(a) - rank(b) || a.student_id.localeCompare(b.student_id, undefined, { numeric: true })).map((r) => (
                <tr key={r.student_id} className={r.review ? 'review' : ''}>
                  <td>{r.name} <span className="hint">({r.student_id})</span></td>
                  <td style={{ color: STATUS_COLOR[r.status], fontWeight: 600 }}>{r.status}{r.review ? ' · check' : ''}
                    {r.reason === 'co-located' && <div className="hint" style={{ fontWeight: 400 }}>same radio as {r.partner_name} ({r.partner}) — one phone sending two ids?</div>}</td>
                  <td>{r.hops ?? '–'}</td><td>{r.path_m ?? '–'}</td><td>{r.decided_by}</td>
                  <td>
                    {(r.status === 'FLAGGED' || r.review) && (
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
          <p className="hint">FLAGGED = checked in on the phone but not corroborated by enough nearby students. "check" = marked present but
            thinly corroborated while your headcount is lower. You decide both.</p>
        </>
      )}
    </div>
  );
}
