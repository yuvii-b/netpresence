/** Hardware-backed ECDSA P-256 key (Secure Enclave on iOS, Android Keystore on Android). */
export interface KeyStore {
  /** Base64 X.509 SubjectPublicKeyInfo DER (Android native export) - or a raw 65-byte X9.63 point (iOS native export). */
  publicKeyB64(): Promise<string>;
  /** Base64 ASN.1-DER ECDSA signature over SHA-256(message as UTF-8). */
  signB64(message: string): Promise<string>;
}

export interface RadioSample {
  /** Advertised local name, e.g. "NP-1a2b3c4d". Anything else is ignored. */
  name: string;
  /** dBm as reported by the OS. 127 (Android "unavailable") and non-negative values are ignored. */
  rssi: number;
}

/**
 * BLE: advertise `advertiseUuid` (identity inside the service UUID, see ble.ts) while continuously scanning, reporting
 * every NetPresence advertisement heard as { name: "NP-<eph>", rssi }.
 */
export interface Radio {
  /** Optional: create the BLE managers and ask for permissions while idle, so start() is instant. */
  prepare?(): Promise<void>;
  start(advertiseName: string, advertiseUuid: string, onSample: (s: RadioSample) => void): Promise<void>;
  stop(): Promise<void>;
}

export interface Clock {
  now(): number; // epoch ms
  sleep(ms: number): Promise<void>;
}

export const systemClock: Clock = {
  now: () => Date.now(),
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
};

export interface Neighbour {
  peer_id: string;
  rssi_median: number;
  sample_count: number;
}

export interface OpenSession {
  status: 'open' | 'none';
  session_id?: string;
  nonce?: string;
  window_ends_at?: number;
  discovery_ends_at?: number;
  report_deadline?: number;
  service_uuid?: string;
  server_time?: number;
}

export interface Joined {
  sessionId: string;
  ephId: string;
  advertiseName: string;
  serviceUuid: string;
  /** Per-phone service UUID to advertise (prefix + eph id). */
  advertiseUuid: string;
  /** Local-clock deadlines (epoch ms), already corrected for phone/server clock skew. Discovery runs until
   * discoveryEndsAtMs, which is a few seconds AFTER check-in closes, so even the last student to tap overlaps
   * everyone for that long. */
  discoveryEndsAtMs: number;
  reportDeadlineMs: number;
}

// ---------------- protocol v3 ----------------
export interface SubjectInfo { subject_id: string; code: string; name: string; roster_size: number; last_pct: number | null }

export interface TeacherStart {
  session_id: string; nonce: string; tag: string; teacher_student_id: string; teacher_eph: string;
  advertise_name: string; advertise_uuid: string; server_time: number; live_ends_at: number;
  subject: { subject_id: string; code: string; name: string; roster_size: number };
}

export type LiveStatus = 'PRESENT' | 'PENDING' | 'FLAGGED' | 'NOT_JOINED' | 'ABSENT';
export interface LiveRow { student_id: string; name: string; status: LiveStatus; reason?: string; partner_name?: string; decided_by?: string }
export interface TeacherLive {
  rev: number; status: 'open' | 'closed'; counts: Record<string, number>; rows: LiveRow[];
  stable_for_s: number; elapsed_s: number; roster_size: number; ends_in_s?: number;
}

export interface MySession {
  status: 'open' | 'none'; session_id?: string; nonce?: string; tag?: string; server_time?: number; live_ends_at?: number;
  subject?: { subject_id: string; code: string; name: string };
}
export interface MyStatus { rev: number; status: 'NONE' | 'PENDING' | 'PRESENT' | 'FLAGGED' | 'ABSENT' | 'CLOSED'; at: number | null; result?: string | null }

/** The register: roster students x finished roll calls (GET /teacher/subjects/{id}/sheet). marks: P present, A absent, F flagged, - no record. */
export interface AttendanceSheet {
  subject: { subject_id: string; code: string; name: string };
  sessions: Array<{ session_id: string; at: number | null; present: number; total: number }>;
  students: Array<{ student_id: string; name: string; marks: string[]; present: number; pct: number | null }>;
}
