"""Reuse real hashes for repeated synthetic seed accounts, never app passwords."""
from functools import lru_cache
from werkzeug.security import generate_password_hash as _hash

@lru_cache(maxsize=32)
def generate_password_hash(password):
    return _hash(password)
