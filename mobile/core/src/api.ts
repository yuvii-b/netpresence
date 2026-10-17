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

type Fetch = typeof fetch;

export class NetPresenceApi {
  constructor(private readonly baseUrl: string, private readonly fetchImpl: Fetch = (...a) => fetch(...a)) {}

  private async call<T>(method: string, path: string, body?: unknown, teacherToken?: string): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers: {
          'ngrok-skip-browser-warning': 'true',
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
          ...(teacherToken ? { 'X-Teacher-Token': teacherToken } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      throw new ApiError(0, e instanceof Error ? e.message : 'network error');
    }
    let json: any = null;
    try {
      json = await res.json();
    } catch {
      /* no body */
    }
    if (!res.ok) {
      const d = json?.detail;
      throw new ApiError(res.status, typeof d === 'string' ? d : res.statusText || 'request failed');
    }
    return json as T;
  }

  register(body: { student_id: string; name: string; model: string; public_key: string; signature: string }) {
    return this.call<{ status: string }>('POST', '/api/devices/register', body);
  }
  openSession() {
    return this.call<OpenSession>('GET', '/api/sessions/open');
  }
  checkin(sessionId: string, studentId: string, signature: string) {
    return this.call<{
      eph_id: string; advertise_name: string; service_uuid: string;
      window_ends_at: number; report_deadline: number; server_time: number;
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
      this.call<{ session_id: string; nonce: string; window_ends_at: number; report_deadline: number }>('POST', '/api/sessions/start', opts, token),
    verifySeeds: (token: string, sessionId: string, studentIds: string[]) =>
      this.call<{ seeds: string[] }>('POST', `/api/sessions/${sessionId}/verify-seeds`, { student_ids: studentIds }, token),
    close: (token: string, sessionId: string, headcount?: number) =>
      this.call<{ counts: Record<string, number>; rows: Array<{ student_id: string; status: string; review?: boolean }> }>(
        'POST', `/api/sessions/${sessionId}/close`, headcount === undefined ? {} : { headcount }, token),
    setCalibration: (token: string, model: string, rssi_offset_db: number) =>
      this.call('PUT', '/api/devices/calibration', { model, rssi_offset_db }, token),
  };
}
