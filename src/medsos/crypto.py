"""Fernet token encryption at rest."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken  # re-exported for callers


def _fernet(key: str) -> Fernet:
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(key: str, plaintext: str) -> str:
    """Encrypt a token for at-rest storage. Returns a urlsafe-base64 string."""
    return _fernet(key).encrypt(plaintext.encode()).decode()


def decrypt_token(key: str, ciphertext: str) -> str:
    """Decrypt a token. Raises cryptography.fernet.InvalidToken on failure."""
    return _fernet(key).decrypt(ciphertext.encode()).decode()