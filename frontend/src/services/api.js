const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;
const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL;

const JSON_HEADERS = {
  'Content-Type': 'application/json',
  'ngrok-skip-browser-warning': 'true',
};

async function parseJsonResponse(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    // No/invalid JSON body — fall through and use the status text instead.
  }

  if (!res.ok) {
    const detail = body && (body.detail || body.error);
    // FastAPI validation errors (422) send `detail` as an array of issue objects
    // rather than a plain string — fall back to a generic message in that case.
    const message = (typeof detail === 'string' && detail) || res.statusText || 'Request failed';
    const error = new Error(message);
    error.status = res.status;
    error.body = body;
    throw error;
  }

  return body;
}

export async function startSession(sessionId, token) {
  const res = await fetch(`${API_BASE_URL}/api/sessions/start`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ session_id: sessionId, token }),
  });
  return parseJsonResponse(res);
}

export async function listSessions() {
  const res = await fetch(`${API_BASE_URL}/api/sessions/list`, {
    headers: { 'ngrok-skip-browser-warning': 'true' },
  });
  return parseJsonResponse(res);
}

export async function stopSession(sessionId) {
  const res = await fetch(`${API_BASE_URL}/api/sessions/stop/${sessionId}`, {
    method: 'POST',
    headers: { 'ngrok-skip-browser-warning': 'true' },
  });
  return parseJsonResponse(res);
}

export async function submitAttendance(sessionId, studentId, decodedToken) {
  const res = await fetch(`${API_BASE_URL}/api/attendance/submit`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      session_id: sessionId,
      student_id: studentId,
      decoded_token: decodedToken,
    }),
  });
  return parseJsonResponse(res);
}

export function connectWebSocket(onMessage) {
  const ws = new WebSocket(WS_BASE_URL);
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    onMessage(data);
  };
  return ws;
}
