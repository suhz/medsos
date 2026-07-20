"""Tests for medsos.crypto."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from medsos.crypto import decrypt_token, encrypt_token


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode()


def test_round_trip(fernet_key):
    pt = "ya29.a0AfH6SMA..."
    ct = encrypt_token(fernet_key, pt)
    assert ct != pt
    assert decrypt_token(fernet_key, ct) == pt


def test_decrypt_bad_ciphertext_raises(fernet_key):
    with pytest.raises(InvalidToken):
        decrypt_token(fernet_key, "not-a-real-ciphertext")


def test_decrypt_with_wrong_key_raises(fernet_key):
    pt = "secret"
    ct = encrypt_token(fernet_key, pt)
    other_key = Fernet.generate_key().decode()
    with pytest.raises(InvalidToken):
        decrypt_token(other_key, ct)