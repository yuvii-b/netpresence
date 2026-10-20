import type { AttendanceSheet, MySession, MyStatus, Neighbour, OpenSession, SubjectInfo, TeacherLive, TeacherStart } from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
  /** Worth retrying: network failure (status 0), 5xx, 429. A 4xx means the request itself is wrong. */
  get transient(): boolean {
    return this.status === 0 || this.status >= 500 || this.status === 429;
  }
}

/** One request never waits longer than this: a lost packet on a congested classroom Wi-Fi must turn into a retry, not a hang. */
export const REQUEST_TIMEOUT_MS = 5000;

/** A long-poll waits `wait` s on the server, so its client timeout is wait + this margin. */
export const LONGPOLL_WAIT_S = 25;
export const LONGPOLL_MARGIN_MS = 6000;

export interface CallOpts { teacherToken?: string; bearer?: string; timeoutMs?: number; signal?: AbortSignal }
type Fetch = typeof fetch;

export class NetPresenceApi {
  constructor(private readonly baseUrl: string, private readonly fetchImpl: Fetch = (...a) => fetch(...a)) {}

  private async call<T>(method: string, path: string, body?: unknown, auth?: string | CallOpts): Promise<T> {
    const o: CallOpts = typeof auth === 'string' ? { teacherToken: auth } : auth ?? {};
    const teacherToken = o.teacherToken;
    let res: Response;
    let json: any = null;
    const ctl = typeof AbortController !== 'undefined' ? new AbortController() : undefined;
    const outer = o.signal;
    const onAbort = () => ctl?.abort();
    if (outer) outer.aborted ? ctl?.abort() : outer.addEventListener('abort', onAbort);
    const timer = setTimeout(() => ctl?.abort(), o.timeoutMs ?? REQUEST_TIMEOUT_MS);
    try {
      try {
        res = await this.fetchImpl(`${this.baseUrl}${path}`, {
          method,
          headers: {
            'ngrok-skip-browser-warning': 'true',
            ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
            ...(teacherToken ? { 'X-Teacher-Token': teacherToken } : {}),
            ...(o.bearer ? { Authorization: `Bearer ${o.bearer}` } : {}),
          },
          body: body !== undefined ? JSON.stringify(body) : undefined,
          signal: ctl?.signal,
        });
      } catch (e) {
        throw new ApiError(0, outer?.aborted ? 'cancelled' : ctl?.signal.aborted ? 'request timed out' : e instanceof Error ? e.message : 'network error');
      }
      try {
        json = await res.json();
      } catch {
        /* no body */
      }
    } finally {
      clearTimeout(timer);
      outer?.removeEventListener('abort', onAbort);
    }
    if (!res.ok) {
      const d = json?.detail;
      throw new ApiError(res.status, typeof d === 'string' ? d : res.statusText || 'request failed');
    }
    return json as T;
  }

  register(body: { student_id: string; name: string; model: string; public_key: string; signature: string; enrol_code?: string; install_id?: string; platform?: string }) {
    return this.call<{ status: string }>('POST', '/api/devices/register', body);
  }
  openSession() {
    return this.call<OpenSession>('GET', '/api/sessions/open');
  }
  checkin(sessionId: string, studentId: string, signature: string) {
    return this.call<{
      eph_id: string; advertise_name: string; service_uuid: string; advertise_uuid?: string;
      window_ends_at: number; discovery_ends_at?: number; report_deadline: number; server_time: number;
    }>('POST', `/api/sessions/${sessionId}/checkin`, { student_id: studentId, signature });
  }
  report(sessionId: string, studentId: string, neighbours: Neighbour[], signature: string) {
    return this.call<{ status: string; neighbours: number }>('POST', `/api/sessions/${sessionId}/report`, {
      student_id: studentId, neighbours, signature,
    });
  }

  // ---- protocol v3 ---------------------------------------------------------------------------------------------------
  health() {
    return this.call<{ status: string; server_time?: number }>('GET', '/api/health');
  }
  teacherLogin(code: string) {
    return this.call<{ token: string; teacher: { name: string }; subjects: SubjectInfo[] }>('POST', '/api/auth/teacher', { code });
  }
  teacherSubjects(token: string) {
    return this.call<SubjectInfo[]>('GET', '/api/teacher/subjects', undefined, { bearer: token });
  }
  teacherSheet(token: string, subjectId: string) {
    return this.call<AttendanceSheet>('GET', `/api/teacher/subjects/${subjectId}/sheet`, undefined, { bearer: token });
  }
  startSubject(token: string, subjectId: string, device: { public_key: string; model: string }) {
    return this.call<TeacherStart>('POST', `/api/teacher/subjects/${subjectId}/start`, { device }, { bearer: token });
  }
  teacherLive(token: string, sessionId: string, since: number, wait: number, signal?: AbortSignal) {
    return this.call<TeacherLive>('GET', `/api/teacher/sessions/${sessionId}/live?since=${since}&wait=${wait}`, undefined,
      { bearer: token, timeoutMs: wait * 1000 + LONGPOLL_MARGIN_MS, signal });
  }
  teacherFinish(token: string, sessionId: string) {
    return this.call<{ counts: Record<string, number>; rows: Array<{ student_id: string; name: string; status: string }> }>(
      'POST', `/api/teacher/sessions/${sessionId}/finish`, {}, { bearer: token });
  }
  teacherAdjudicate(token: string, sessionId: string, studentId: string, status: 'PRESENT' | 'ABSENT') {
    return this.call('POST', `/api/teacher/sessions/${sessionId}/adjudicate`, { student_id: studentId, status }, { bearer: token });
  }
  studentLogin(studentId: string, ts: number, signature: string) {
    return this.call<{ token: string; name: string }>('POST', '/api/auth/student', { student_id: studentId, ts, signature });
  }
  me(token: string) {
    return this.call<{ student_id: string; name: string; subjects: Array<{ subject_id: string; code: string; name: string }> }>(
      'GET', '/api/me', undefined, { bearer: token });
  }
  meSession(token: string, wait: number, signal?: AbortSignal) {
    return this.call<MySession>('GET', `/api/me/session?wait=${wait}`, undefined, { bearer: token, timeoutMs: wait * 1000 + LONGPOLL_MARGIN_MS, signal });
  }
  myStatus(token: string, sessionId: string, since: number, wait: number, signal?: AbortSignal) {
    return this.call<MyStatus>('GET', `/api/sessions/${sessionId}/me?since=${since}&wait=${wait}`, undefined,
      { bearer: token, timeoutMs: wait * 1000 + LONGPOLL_MARGIN_MS, signal });
  }

  // teacher helpers (used by tests and tooling; the teacher UI is the web console)
  teacher = {
    startSession: (token: string, opts: object = {}) =>
      this.call<{ session_id: string; nonce: string; window_ends_at: number; discovery_ends_at: number; report_deadline: number }>('POST', '/api/sessions/start', opts, token),
    verifySeeds: (token: string, sessionId: string, studentIds: string[]) =>
      this.call<{ seeds: string[] }>('POST', `/api/sessions/${sessionId}/verify-seeds`, { student_ids: studentIds }, token),
    close: (token: string, sessionId: string, headcount?: number) =>
      this.call<{ counts: Record<string, number>; rows: Array<{ student_id: string; status: string; review?: boolean }> }>(
        'POST', `/api/sessions/${sessionId}/close`, headcount === undefined ? {} : { headcount }, token),
    addTeacher: (token: string, name: string, code: string) =>
      this.call<{ teacher_id: string }>('POST', '/api/admin/teachers', { name, code }, token),
    addSubject: (token: string, teacherCode: string, code: string, name: string, roster: string[]) =>
      this.call<{ subject_id: string }>('POST', '/api/admin/subjects', { teacher_code: teacherCode, code, name, roster }, token),
    setCalibration: (token: string, model: string, rssi_offset_db: number) =>
      this.call('PUT', '/api/devices/calibration', { model, rssi_offset_db }, token),
  };
}
