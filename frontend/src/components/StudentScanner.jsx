import React, { useState, useRef, useEffect } from 'react';
import { ToneDecoder } from '../audio/toneDecoder';
import { getOS, getDeviceType } from '../audio/platform';
import { submitAttendance, listSessions } from '../services/api';

export default function StudentScanner() {
  const [isScanning, setIsScanning] = useState(false);
  const [studentId, setStudentId] = useState('STU-2024');
  const [statusMsg, setStatusMsg] = useState('');
  const [activeSessionId, setActiveSessionId] = useState(null);
  const decoderRef = useRef(null);
  const detectedOS = getOS();
  const detectedDeviceType = getDeviceType();

  const refreshActiveSession = async () => {
    try {
      const sessions = await listSessions();
      const active = Array.isArray(sessions) ? sessions.find((s) => s.status === 'active') : null;
      const id = active ? active.session_id : null;
      setActiveSessionId(id);
      return id;
    } catch {
      setActiveSessionId(null);
      return null;
    }
  };

  useEffect(() => {
    refreshActiveSession();
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
        console.log('DECODED:', token);
        setStatusMsg(`Token captured: ${token}. Submitting...`);
        decoderRef.current.stop();
        setIsScanning(false);

        try {
          const res = await submitAttendance(currentSessionId, studentId, token.trim());
          if (res.status === 'success') {
            setStatusMsg('Attendance marked successfully!');
          } else {
            setStatusMsg(`Submission Failed (Captured: "${token}"): ${res.detail || res.error}`);
          }
        } catch (err) {
          console.error(err);
          setStatusMsg(`Submission error (Captured: "${token}"): could not reach server. Check the backend/ngrok URL in api.js.`);
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