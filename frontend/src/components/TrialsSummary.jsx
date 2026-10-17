import { useState } from 'react';
import { acoustic } from '../services/api';

const LABELS = { seat_position: 'Seat position', fan_on: 'Fan on', device_model: 'Device model', os: 'OS' };

// Detection-rate tables for the v1 acoustic dead-end evidence (report section 3).
export default function TrialsSummary() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const load = async () => {
    setErr('');
    try { setData(await acoustic.trialSummary()); } catch (e) { setErr(e.status === 401 ? 'Set the teacher token on another tab first.' : e.message); }
  };
  return (
    <div className="card">
      <h2>Acoustic v1 — trial results</h2>
      <button onClick={load}>Refresh</button> {err && <span className="err">{err}</span>}
      {data && Object.entries(data).map(([field, rows]) => rows.length > 0 && (
        <div key={field}>
          <h3>{LABELS[field]}</h3>
          <table>
            <thead><tr><th>{LABELS[field]}</th><th>Trials</th><th>Detection rate</th><th>Avg time to detect</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={String(r.key)}><td>{String(r.key)}</td><td>{r.trials}</td>
                <td>{(r.detection_rate * 100).toFixed(0)}%</td><td>{r.avg_time_to_detect_ms ?? '–'} ms</td></tr>
            ))}</tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
