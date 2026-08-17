const API_BASE_URL = 'https://f2b2-152-57-90-114.ngrok-free.app';
const WS_BASE_URL = 'wss://f2b2-152-57-90-114.ngrok-free.app/ws';

export async function startSession(sessionId, token) {
  const res = await fetch(`${API_BASE_URL}/api/sessions/start`, {
    method: 'POST',
    headers: { 
      'Content-Type': 'application/json',
      'ngrok-skip-browser-warning': 'true'
    },
    body: JSON.stringify({ session_id: sessionId, token }),
  });
  return res.json();
}

export async function getActiveSession(sessionId) {
  const res = await fetch(`${API_BASE_URL}/api/sessions/active/${sessionId}`, {
    headers: {
      'ngrok-skip-browser-warning': 'true'
    }
  });
  return res.json();
}

export async function submitAttendance(sessionId, studentId, decodedToken) {
  const res = await fetch(`${API_BASE_URL}/api/attendance/submit`, {
    method: 'POST',
    headers: { 
      'Content-Type': 'application/json',
      'ngrok-skip-browser-warning': 'true'
    },
    body: JSON.stringify({
      session_id: sessionId,
      student_id: studentId,
      decoded_token: decodedToken,
    }),
  });
  return res.json();
}

export function connectWebSocket(onMessage) {
  const ws = new WebSocket(WS_BASE_URL);
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    onMessage(data);
  };
  return ws;
}