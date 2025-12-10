import os
from cryptography.fernet import Fernet

#Put this in env or secret manager (DO NOT COMMIT TO REPO)

KEY = os.getenv("ENCRYPTION_KEY")
if not KEY:
    raise RuntimeError("ENCRYPTION_KEY environment variable not set (Fernet key required)")

fernet = Fernet(KEY.encode() if isinstance(KEY, str) else KEY)

def encrypt_value(plain: str) -> str:
    return fernet.encrypt(plain.encode()).decode()

def decrypt_value(token: str) -> str:
    return fernet.decrypt(token.encode()).decode()
