import base64

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def decode_user_id(*, encoded_user_id: str, encryption_key: bytes) -> str:
    padding_needed = len(encoded_user_id) % 4
    if padding_needed:
        encoded_user_id += "=" * (4 - padding_needed)

    encrypted_data = base64.urlsafe_b64decode(encoded_user_id)

    cipher = Cipher(
        algorithms.AES(encryption_key),
        modes.CBC(b"\x00" * 16),
        backend=default_backend(),
    )
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(encrypted_data) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    decoded_user_id = unpadder.update(padded_data) + unpadder.finalize()

    return decoded_user_id.decode()
