from sqlalchemy import create_engine
from .config import settings

pg = create_engine(settings.pg_url, pool_size=10, pool_pre_ping=True)
_siesa = _mysql = _lab = None


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


def lab_engine():
    """Segunda fuente MSSQL (FUNATLAB). Solo lectura."""
    global _lab
    if _lab is None:
        _lab = create_engine(f"mssql+pyodbc:///?odbc_connect={settings.lab_odbc}", pool_pre_ping=True)
    return _lab
