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

/** BLE: advertise `name` + `serviceUuid` while continuously scanning, reporting every advertisement heard. */
export interface Radio {
  start(advertiseName: string, serviceUuid: string, onSample: (s: RadioSample) => void): Promise<void>;
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
  report_deadline?: number;
  service_uuid?: string;
  server_time?: number;
}

export interface Joined {
  sessionId: string;
  ephId: string;
  advertiseName: string;
  serviceUuid: string;
  /** Local-clock deadlines (epoch ms), already corrected for phone/server clock skew. */
  discoveryEndsAtMs: number;
  reportDeadlineMs: number;
}
