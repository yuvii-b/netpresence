"""A virtual phone: holds a real P-256 key and signs exactly what real clients must sign."""
import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.services import crypto


class Device:
    """A fake phone: holds a P-256 key and signs exactly what the real clients must sign."""

    def __init__(self, student_id, model="Pixel 6"):
        self.student_id, self.model = student_id, model
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = base64.b64encode(self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        self.eph = None

    def sign(self, msg: str) -> str:
        return base64.b64encode(self.key.sign(msg.encode(), ec.ECDSA(hashes.SHA256()))).decode()

    def register_body(self, name=None):
        return {"student_id": self.student_id, "name": name or self.student_id, "model": self.model,
                "public_key": self.pub, "signature": self.sign(crypto.register_message(self.student_id, self.model))}

    def report_body(self, session_id, neighbours):
        return {"student_id": self.student_id, "neighbours": neighbours,
                "signature": self.sign(crypto.report_message(session_id, self.student_id, neighbours))}
