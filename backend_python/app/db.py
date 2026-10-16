from sqlalchemy import create_engine
from .config import settings

pg = create_engine(settings.pg_url, pool_size=10, pool_pre_ping=True)
_siesa: dict[str, object] = {}
_mysql = None


def siesa_engine(db: str):
    """Engine hacia una BD de Siesa (una por compania). Solo lectura."""
    if db not in _siesa:
        _siesa[db] = create_engine(f"mssql+pyodbc:///?odbc_connect={settings.siesa_odbc(db)}", pool_pre_ping=True)
    return _siesa[db]


def mysql_engine():
    global _mysql
    if _mysql is None:
        _mysql = create_engine(settings.mysql_url, pool_pre_ping=True)
    return _mysql
