import time
from fastapi import HTTPException
from app.config import settings

class TokenService:
    def __init__(self):
        self.active_sessions = {}  # session_id -> {"token": str, "expires_at": float}
        self.used_tokens = set()   # Nonces to prevent replay attacks

    def register_session(self, session_id: str, token: str):
        expires_at = time.time() + settings.TOKEN_VALIDITY_SECONDS
        self.active_sessions[session_id] = {
            "token": token,
            "expires_at": expires_at
        }

    def validate_submission(self, session_id: str, student_id: str, decoded_token: str):
        now = time.time()
        session = self.active_sessions.get(session_id)

        if not session:
            raise HTTPException(status_code=400, detail="Invalid or inactive session.")

        if now > session["expires_at"]:
            raise HTTPException(status_code=400, detail="Audio token expired.")

        if decoded_token != session["token"]:
            raise HTTPException(status_code=400, detail="Audio token mismatch.")

        nonce_key = f"{session_id}:{student_id}:{decoded_token}"
        if nonce_key in self.used_tokens:
            raise HTTPException(status_code=400, detail="Token already submitted.")

        self.used_tokens.add(nonce_key)
        return True

token_service = TokenService()