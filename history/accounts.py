"""DB-local app accounts. Authentication returns identity, never a login session."""

import hashlib
import hmac
import secrets
from uuid import uuid4


PUBLIC_COLUMNS = "user_id::text, username, display_name, created_at"
HASH_PREFIX = "scrypt$131072$8$1"


def _label(value, field):
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise ValueError(f"{field}: nonempty text without surrounding whitespace required")


def _password(value):
    if not isinstance(value, str) or not value:
        raise ValueError("password: nonempty text required")
    encoded = value.encode("utf-8")
    if len(encoded) > 1024:
        raise ValueError("password: maximum 1024 UTF-8 bytes")
    return encoded


def _derive(password, salt):
    # Standard-library scrypt; explicit maxmem covers the 128 MiB working set.
    return hashlib.scrypt(password, salt=salt, n=2**17, r=8, p=1,
                          maxmem=256*1024*1024, dklen=32)


def hash_password(password: str) -> str:
    encoded = _password(password)
    salt = secrets.token_bytes(16)
    digest = _derive(encoded, salt)
    return f"{HASH_PREFIX}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    encoded = _password(password)
    try:
        prefix, salt_hex, digest_hex = stored.rsplit("$",2)
        if prefix != HASH_PREFIX or len(salt_hex) != 32 or len(digest_hex) != 64:
            raise ValueError
        salt, digest = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        if len(salt) != 16 or len(digest) != 32:
            raise ValueError
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("stored password hash is invalid or unsupported") from error
    return hmac.compare_digest(_derive(encoded,salt), digest)


def create_user(connection, username: str, display_name: str, password: str) -> dict:
    _label(username,"username")
    _label(display_name,"display_name")
    hashed = hash_password(password)
    with connection.transaction():
        result = connection.execute(f"""INSERT INTO c2_history.users
            (user_id, username, display_name, password_hash) VALUES (%s,%s,%s,%s)
            ON CONFLICT (username) DO NOTHING RETURNING {PUBLIC_COLUMNS}""",
            (str(uuid4()),username,display_name,hashed)).fetchone()
        if result is None:
            raise ValueError("username already exists; existing account retained")
    return result


def list_users(connection) -> list[dict]:
    return connection.execute(f"SELECT {PUBLIC_COLUMNS} FROM c2_history.users ORDER BY username").fetchall()


def authenticate(connection, username: str, password: str) -> dict | None:
    _label(username,"username")
    _password(password)
    row = connection.execute(f"SELECT {PUBLIC_COLUMNS}, password_hash FROM c2_history.users WHERE username=%s",
                             (username,)).fetchone()
    if row is None or not verify_password(password,row["password_hash"]):
        return None
    return {key:value for key,value in row.items() if key != "password_hash"}
