"""Шифрование refresh-токенов Google в базе (Fernet: AES + подпись).

Ключ — `GOOGLE_TOKEN_KEY` в `.env`. Сгенерировать:
    uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Утечка базы без ключа не даёт доступа к календарям пользователей.
"""

from cryptography.fernet import Fernet, InvalidToken


class TokenKeyError(ValueError):
    """Ключ не подходит: другой ключ или повреждённые данные."""


def _fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as error:
        raise TokenKeyError("GOOGLE_TOKEN_KEY — не ключ Fernet (32 байта в base64)") from error


def encrypt_token(token: str, key: str) -> str:
    return _fernet(key).encrypt(token.encode()).decode()


def decrypt_token(encrypted: str, key: str) -> str:
    try:
        return _fernet(key).decrypt(encrypted.encode()).decode()
    except InvalidToken as error:
        raise TokenKeyError("Токен не расшифровывается этим ключом") from error
