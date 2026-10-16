from sqlalchemy import create_engine
from .config import settings

pg = create_engine(settings.pg_url, pool_size=10, pool_pre_ping=True)
_siesa = _mysql = None


def siesa_engine():
    global _siesa
    if _siesa is None:
        _siesa = create_engine(settings.siesa_url, fast_executemany=True, pool_pre_ping=True)
    return _siesa


def mysql_engine():
    global _mysql
    if _mysql is None:
        _mysql = create_engine(settings.mysql_url, pool_pre_ping=True)
    return _mysql
