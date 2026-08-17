import { useState, useRef, useEffect } from 'react';
import { ToneDecoder } from '../audio/toneDecoder';
import { getOS, getDeviceType } from '../audio/platform';
import { submitAttendance, listSessions } from '../services/api';

export default function StudentScanner() {
  const [isScanning, setIsScanning] = useState(false);
  const [studentId, setStudentId] = useState('STU-2024');
  const [statusMsg, setStatusMsg] = useState('');
  const [activeSessionId, setActiveSessionId] = useState(null);
  const decoderRef = useRef(null);
  const mountedRef = useRef(true);
  const detectedOS = getOS();
  const detectedDeviceType = getDeviceType();

  const refreshActiveSession = async () => {
    try {
      const sessions = await listSessions();
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
    // One-time fetch on mount to seed the active-session indicator; the async
    // setState is guarded by mountedRef above, so this is safe despite the rule.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refreshActiveSession();
    return () => {
      mountedRef.current = false;
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
    decoderRef.current = new ToneDecoder();

    try {
      let captured = false;
      await decoderRef.current.startListening(async (token) => {
        captured = true;
        setStatusMsg(`Token captured: ${token}. Submitting...`);
        decoderRef.current.stop();
        setIsScanning(false);

        try {
          await submitAttendance(currentSessionId, studentId, token.trim());
          setStatusMsg('Attendance marked successfully!');
        } catch (err) {
          console.error(err);
          const reason = err.status ? err.message : 'could not reach the server.';
          setStatusMsg(`Submission failed (captured "${token}"): ${reason}`);
        }
      }, (debugData) => {
        if (!captured) {
          setStatusMsg(`Listening... Freq: ${debugData.bestFreq}Hz, Power Ratio: ${debugData.bestPower.toFixed(2)} (Threshold: ${decoderRef.current.powerThreshold})`);
        }
      });
    } catch (err) {
      console.error(err);
      setIsScanning(false);
      setStatusMsg('Error: Could not access microphone (needs HTTPS + mic permission).');
    }
  };

  const handleStopScan = () => {
    if (decoderRef.current) decoderRef.current.stop();
    setIsScanning(false);
    setStatusMsg('Stopped listening.');
  };

  return (
    <div style={{ padding: '20px', border: '1px solid #ccc', borderRadius: '8px', marginTop: '20px' }}>
      <h2>Student Scanner</h2>
      <p style={{ fontSize: '0.85em', color: '#666' }}>
        Detected: {detectedOS} ({detectedDeviceType})
      </p>
      <label>Student ID: </label>
      <input type="text" value={studentId} onChange={(e) => setStudentId(e.target.value)} />
      <br />
      <p style={{ fontSize: '0.85em', color: '#666' }}>
        Active session: {activeSessionId || 'none detected'}
      </p>
      <br />
      {!isScanning ? (
        <button onClick={handleStartScan} style={{ padding: '10px 20px', background: 'blue', color: '#fff' }}>
          Tap to Verify Attendance
        </button>
      ) : (
        <>
          <p>Listening...</p>
          <button onClick={handleStopScan}>Cancel</button>
        </>
      )}
      <p><strong>Status:</strong> {statusMsg}</p>
    </div>
  );
}