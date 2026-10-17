const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
// WebSocket base defaults to the API origin with ws(s):// (paths are appended below).
const WS_BASE_URL = (import.meta.env.VITE_WS_BASE_URL || API_BASE_URL.replace(/^http/, 'ws')).replace(/\/ws\/?$/, '');

const TOKEN_KEY = 'np_teacher_token';

export function getTeacherToken() {
  try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
}
export function setTeacherToken(t) {
  try { sessionStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable: token lives only until reload */ }
}

function headers(json = true, teacher = false) {
  const h = { 'ngrok-skip-browser-warning': 'true' };
  if (json) h['Content-Type'] = 'application/json';
  if (teacher) h['X-Teacher-Token'] = getTeacherToken();
  return h;
}

async function parseJsonResponse(res) {
  let body = null;
  try { body = await res.json(); } catch { /* no JSON body: fall back to status text */ }
  if (!res.ok) {
    const detail = body && (body.detail || body.error);
    // FastAPI 422s send `detail` as an array of issue objects.
    const message = (typeof detail === 'string' && detail) || res.statusText || 'Request failed';
    const error = new Error(message);
    error.status = res.status;
    error.body = body;
    throw error;
  }
  return body;
}

async function call(method, path, { body, teacher = false } = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: headers(body !== undefined, teacher),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return parseJsonResponse(res);
}

// ---------------- v2 proximity graph (teacher) ----------------
export const v2 = {
  start: (opts = {}) => call('POST', '/api/sessions/start', { body: opts, teacher: true }),
  students: () => call('GET', '/api/devices', { teacher: true }),
  verifySeeds: (id, studentIds) => call('POST', `/api/sessions/${id}/verify-seeds`, { body: { student_ids: studentIds }, teacher: true }),
  close: (id, headcount) => call('POST', `/api/sessions/${id}/close`, { body: headcount === '' || headcount == null ? {} : { headcount: Number(headcount) }, teacher: true }),
  result: (id) => call('GET', `/api/sessions/${id}/result`, { teacher: true }),
  adjudicate: (id, studentId, status) => call('POST', `/api/sessions/${id}/adjudicate`, { body: { student_id: studentId, status }, teacher: true }),
  list: () => call('GET', '/api/sessions', { teacher: true }),
  socket: (id, onMessage) => openSocket(`/api/sessions/ws/${encodeURIComponent(id)}`, onMessage),
};

// ---------------- v1 acoustic baseline ----------------
export const acoustic = {
  start: (sessionId, token) => call('POST', '/api/acoustic/sessions/start', { body: { session_id: sessionId, token }, teacher: true }),
  stop: (sessionId) => call('POST', `/api/acoustic/sessions/stop/${sessionId}`, { teacher: true }),
  list: () => call('GET', '/api/acoustic/sessions/list'),
  submit: (sessionId, studentId, decodedToken) =>
    call('POST', '/api/acoustic/attendance/submit', { body: { session_id: sessionId, student_id: studentId, decoded_token: decodedToken } }),
  logTrial: (trial) => call('POST', '/api/acoustic/trials', { body: trial }),
  trialSummary: () => call('GET', '/api/acoustic/trials/summary', { teacher: true }),
  socket: (onMessage) => openSocket('/api/acoustic/ws', onMessage),
};

function openSocket(path, onMessage) {
  const ws = new WebSocket(`${WS_BASE_URL}${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(getTeacherToken())}`);
  ws.onmessage = (event) => {
    try { onMessage(JSON.parse(event.data)); } catch { /* ignore malformed frame */ }
  };
  return ws;
}
