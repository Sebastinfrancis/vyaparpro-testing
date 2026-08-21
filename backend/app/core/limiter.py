"""
Shared rate limiter instance. Lives in its own module (not app/main.py)
so endpoint files can import it without causing circular imports.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])