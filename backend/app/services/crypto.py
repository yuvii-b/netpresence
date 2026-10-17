"""Device-signature verification.

Devices hold an ECDSA P-256 key (Secure Enclave on iOS, Android Keystore on
Android - the only curve both hardware keystores support). Public keys are
accepted as base64 X.509 SubjectPublicKeyInfo DER (what Android exports), or a
raw 65-byte X9.63 uncompressed point (what iOS exports). Signatures are
base64 ASN.1-DER ECDSA over SHA-256 (what both platforms produce natively).
"""
import base64
import binascii
import json

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64") from exc


def load_public_key(public_key_b64: str) -> ec.EllipticCurvePublicKey:
    raw = _b64(public_key_b64)
    if len(raw) == 65 and raw[0] == 0x04:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    key = serialization.load_der_public_key(raw)
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("public key must be ECDSA P-256")
    return key


def verify(public_key_b64: str, message: str, signature_b64: str) -> bool:
    try:
        key = load_public_key(public_key_b64)
        key.verify(_b64(signature_b64), message.encode(), ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, UnsupportedAlgorithm, ValueError, TypeError):   # any malformed key/signature = reject
        return False


# --- canonical messages (clients must build these byte-for-byte) -----------

def register_message(student_id: str, model: str) -> str:
    return f"register:{student_id}:{model}"


def checkin_message(session_id: str, nonce: str) -> str:
    return f"checkin:{session_id}:{nonce}"


def report_message(session_id: str, student_id: str, neighbours: list[dict]) -> str:
    rows = sorted(([n["peer_id"], int(n["rssi_median"]), int(n["sample_count"])] for n in neighbours))
    return f"report:{session_id}:{student_id}:" + json.dumps(rows, separators=(",", ":"))
