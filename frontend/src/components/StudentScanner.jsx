import React, { useState, useRef } from 'react';
import { ToneDecoder } from '../audio/toneDecoder';
import { submitAttendance } from '../services/api';

export default function StudentScanner() {
  const [isScanning, setIsScanning] = useState(false);
  const [studentId, setStudentId] = useState('STU-2024');
  const [statusMsg, setStatusMsg] = useState('');
  const decoderRef = useRef(null);

  const handleStartScan = async () => {
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

        const res = await submitAttendance('SESS-101', studentId, token.trim());
        if (res.status === 'success') {
          setStatusMsg('Attendance marked successfully!');
        } else {
          setStatusMsg(`Submission Failed (Captured: "${token}"): ${res.detail || res.error}`);
        }
      }, (debugData) => {
        if (!captured) {
          setStatusMsg(`Listening... Freq: ${debugData.bestFreq}Hz, Power Ratio: ${debugData.bestPower.toFixed(2)} (Threshold: 8.0)`);
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
      <label>Student ID: </label>
      <input type="text" value={studentId} onChange={(e) => setStudentId(e.target.value)} />
      <br /><br />
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