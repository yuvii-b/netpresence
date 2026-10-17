import type { Neighbour, OpenSession } from './types';

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

type Fetch = typeof fetch;

export class NetPresenceApi {
  constructor(private readonly baseUrl: string, private readonly fetchImpl: Fetch = (...a) => fetch(...a)) {}

  private async call<T>(method: string, path: string, body?: unknown, teacherToken?: string): Promise<T> {
    let res: Response;
    let json: any = null;
    const ctl = typeof AbortController !== 'undefined' ? new AbortController() : undefined;
    const timer = setTimeout(() => ctl?.abort(), REQUEST_TIMEOUT_MS);
    try {
      try {
        res = await this.fetchImpl(`${this.baseUrl}${path}`, {
          method,
          headers: {
            'ngrok-skip-browser-warning': 'true',
            ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
            ...(teacherToken ? { 'X-Teacher-Token': teacherToken } : {}),
          },
          body: body !== undefined ? JSON.stringify(body) : undefined,
          signal: ctl?.signal,
        });
      } catch (e) {
        throw new ApiError(0, ctl?.signal.aborted ? 'request timed out' : e instanceof Error ? e.message : 'network error');
      }
      try {
        json = await res.json();
      } catch {
        /* no body */
      }
    } finally {
      clearTimeout(timer);
    }
    if (!res.ok) {
      const d = json?.detail;
      throw new ApiError(res.status, typeof d === 'string' ? d : res.statusText || 'request failed');
    }
    return json as T;
  }

  register(body: { student_id: string; name: string; model: string; public_key: string; signature: string; enrol_code?: string }) {
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

  // teacher helpers (used by tests and tooling; the teacher UI is the web console)
  teacher = {
    startSession: (token: string, opts: object = {}) =>
      this.call<{ session_id: string; nonce: string; window_ends_at: number; discovery_ends_at: number; report_deadline: number }>('POST', '/api/sessions/start', opts, token),
    verifySeeds: (token: string, sessionId: string, studentIds: string[]) =>
      this.call<{ seeds: string[] }>('POST', `/api/sessions/${sessionId}/verify-seeds`, { student_ids: studentIds }, token),
    close: (token: string, sessionId: string, headcount?: number) =>
      this.call<{ counts: Record<string, number>; rows: Array<{ student_id: string; status: string; review?: boolean }> }>(
        'POST', `/api/sessions/${sessionId}/close`, headcount === undefined ? {} : { headcount }, token),
    setCalibration: (token: string, model: string, rssi_offset_db: number) =>
      this.call('PUT', '/api/devices/calibration', { model, rssi_offset_db }, token),
  };
}
