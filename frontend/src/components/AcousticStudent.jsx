import { useState, useRef, useEffect } from 'react';
import { ToneDecoder } from '../audio/toneDecoder';
import { getOS, getDeviceType } from '../audio/platform';
import { acoustic } from '../services/api';

const LISTEN_TIMEOUT_MS = 30000;

// v1 baseline student. "Trial mode" logs every attempt (success or timeout) for the dead-end characterisation.
export default function AcousticStudent() {
  const [isScanning, setIsScanning] = useState(false);
  const [studentId, setStudentId] = useState('STU-2024');
  const [statusMsg, setStatusMsg] = useState('');
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [trialMode, setTrialMode] = useState(false);
  const [distance, setDistance] = useState('');
  const [seat, setSeat] = useState('front');
  const [fanOn, setFanOn] = useState(false);
  const [model, setModel] = useState('');
  const decoderRef = useRef(null);
  const timeoutRef = useRef(null);
  const mountedRef = useRef(true);
  const detectedOS = getOS();
  const detectedDeviceType = getDeviceType();

  const refreshActiveSession = async () => {
    try {
      const sessions = await acoustic.list();
      const active = Array.isArray(sessions) ? sessions.find((s) => s.status === 'active') : null;
      const id = active ? active.session_id : null;
      if (mountedRef.current) setActiveSessionId(id);
      return id;
    } catch {
      if (mountedRef.current) setActiveSessionId(null);
      return null;
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    // One-time seed of the active-session indicator; the async setState is guarded by mountedRef.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refreshActiveSession();
    return () => {
      mountedRef.current = false;
      clearTimeout(timeoutRef.current);
      decoderRef.current?.stop();
    };
  }, []);

  const handleStartScan = async () => {
    const currentSessionId = await refreshActiveSession();
    if (!currentSessionId) {
      setStatusMsg('No active session found. Ask the teacher to start one and tap again.');
      return;
    }

    setStatusMsg('Listening for tone sequence...');
    setIsScanning(true);
    const decoder = new ToneDecoder();
    decoderRef.current = decoder;
    const startedAt = performance.now();
    let bestSnr = 0;
    let finished = false;

    const logTrial = (success) => {
      if (!trialMode) return;
      acoustic.logTrial({
        session_id: currentSessionId, success,
        distance_m: distance === '' ? null : Number(distance),
        device_model: model || null, os: detectedOS, fan_on: fanOn, seat_position: seat,
        time_to_detect_ms: success ? Math.round(performance.now() - startedAt) : null,
        best_snr: Number(bestSnr.toFixed(2)), snr_threshold: decoder.powerThreshold,
      }).catch(() => {});
    };

    timeoutRef.current = setTimeout(() => {
      if (finished) return;
      finished = true;
      decoder.stop();
      setIsScanning(false);
      setStatusMsg(`No complete token heard in ${LISTEN_TIMEOUT_MS / 1000}s.`);
      logTrial(false);
    }, LISTEN_TIMEOUT_MS);

    try {
      await decoder.startListening(async (token) => {
        if (finished) return;
        finished = true;
        clearTimeout(timeoutRef.current);
        decoder.stop();
        setIsScanning(false);
        logTrial(true);
        setStatusMsg(`Token captured: ${token}. Submitting...`);
        try {
          await acoustic.submit(currentSessionId, studentId, token.trim());
          setStatusMsg('Attendance marked successfully!');
        } catch (err) {
          const reason = err.status ? err.message : 'could not reach the server.';
          setStatusMsg(`Submission failed (captured "${token}"): ${reason}`);
        }
      }, (debugData) => {
        bestSnr = Math.max(bestSnr, debugData.bestPower);
        if (!finished) {
          setStatusMsg(`Listening... ${debugData.bestFreq ?? '–'} Hz, SNR ${debugData.bestPower.toFixed(2)} (threshold ${decoder.powerThreshold})`);
        }
      });
    } catch {
      finished = true;
      clearTimeout(timeoutRef.current);
      setIsScanning(false);
      setStatusMsg('Error: could not access microphone (needs HTTPS + mic permission).');
    }
  };

  const handleStopScan = () => {
    clearTimeout(timeoutRef.current);
    decoderRef.current?.stop();
    setIsScanning(false);
    setStatusMsg('Stopped listening.');
  };

  return (
    <div className="card">
      <h2>Acoustic v1 — Student</h2>
      <p className="hint">Detected: {detectedOS} ({detectedDeviceType}) · active session: {activeSessionId || 'none'}</p>
      <div className="row">
        <label>Student ID <input value={studentId} onChange={(e) => setStudentId(e.target.value)} /></label>
        <label><input type="checkbox" checked={trialMode} onChange={(e) => setTrialMode(e.target.checked)} /> Trial mode (log attempts)</label>
      </div>
      {trialMode && (
        <div className="row">
          <label>Distance m <input type="number" min="0" step="0.5" value={distance} onChange={(e) => setDistance(e.target.value)} style={{ width: 70 }} /></label>
          <label>Seat <select value={seat} onChange={(e) => setSeat(e.target.value)}><option>front</option><option>middle</option><option>back</option></select></label>
          <label><input type="checkbox" checked={fanOn} onChange={(e) => setFanOn(e.target.checked)} /> Fan on</label>
          <label>Phone model <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="e.g. Redmi Note 9" /></label>
        </div>
      )}
      {!isScanning
        ? <button className="primary" onClick={handleStartScan}>Tap to verify attendance</button>
        : <button onClick={handleStopScan}>Cancel</button>}
      <p><strong>Status:</strong> {statusMsg}</p>
    </div>
  );
}
