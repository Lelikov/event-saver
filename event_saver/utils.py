import base64
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


AES_BLOCK_SIZE = 16
PKCS7_BIT_SIZE = 128


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 string (with optional trailing Z) into a timezone-aware datetime."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def decode_user_id(*, encoded_user_id: str, encryption_key: bytes) -> str:
    padding_needed = len(encoded_user_id) % 4
    if padding_needed:
        encoded_user_id += "=" * (4 - padding_needed)

    encrypted_data = base64.urlsafe_b64decode(encoded_user_id)

    cipher = Cipher(
        algorithms.AES(encryption_key),
        modes.CBC(b"\x00" * AES_BLOCK_SIZE),
        backend=default_backend(),
    )
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(encrypted_data) + decryptor.finalize()

    unpadder = padding.PKCS7(PKCS7_BIT_SIZE).unpadder()
    decoded_user_id = unpadder.update(padded_data) + unpadder.finalize()

    return decoded_user_id.decode()
