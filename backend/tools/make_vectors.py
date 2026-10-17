"""Write cross-language test vectors (canonical messages + a Python-made signature) to docs/test-vectors.json.

The mobile core (TypeScript) must reproduce these messages byte-for-byte and verify the signature, so any drift
between what phones sign and what the server verifies fails a test instead of failing in a classroom.
"""
import base64
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.services import crypto


def main(out="../../docs/test-vectors.json"):
    # fixed key so the vector file is stable across runs
    key = ec.derive_private_key(0x1D3F5A7B9C2E4F60718293A4B5C6D7E8F9012345678ABCDEF0123456789ABCDE % (2**255), ec.SECP256R1())
    pub = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    neighbours = [
        {"peer_id": "ff00aa11", "rssi_median": -71, "sample_count": 9},
        {"peer_id": "0a1b2c3d", "rssi_median": -58, "sample_count": 14},
        {"peer_id": "0a1b2c3d", "rssi_median": -60, "sample_count": 3},   # same peer twice: ordering by rssi next
        {"peer_id": "7c7c7c7c", "rssi_median": -64, "sample_count": 20},
    ]
    msgs = {
        "register": crypto.register_message("21CT042", "Redmi Note 9"),
        "checkin": crypto.checkin_message("S-1a2b3c4d5e", "9f8e7d6c5b4a39281706f5e4d3c2b1a0"),
        "report": crypto.report_message("S-1a2b3c4d5e", "21CT042", neighbours),
    }
    sig = {k: base64.b64encode(key.sign(v.encode(), ec.ECDSA(hashes.SHA256()))).decode() for k, v in msgs.items()}
    for k in msgs:
        assert crypto.verify(pub, msgs[k], sig[k])
    doc = {"public_key_spki_b64": pub, "neighbours": neighbours, "messages": msgs, "signatures_by_python": sig}
    path = os.path.join(os.path.dirname(__file__), out)
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
    print("wrote", os.path.abspath(path))


if __name__ == "__main__":
    main()
