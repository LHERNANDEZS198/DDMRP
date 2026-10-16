from urllib.parse import quote_plus
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Postgres analitico ---
    postgres_db: str = "ddmrp"
    postgres_user: str = "ddmrp"
    postgres_password: str = ""
    postgres_host: str = "db"
    postgres_port: int = 5432

    # --- Siesa (MSSQL, solo lectura): una BD por compania ---
    siesa_host: str = ""
    siesa_port: int = 1433
    siesa_db: str = ""        # empresa '05' (Funat)
    siesa_db_s: str = ""      # empresa '21' (Store); vacio = no se consulta
    siesa_cia: int = 1        # f120_id_cia
    siesa_user: str = ""
    siesa_password: str = ""

    # --- MySQL de reloj (solo usuario y clave) ---
    auth_mysql_host: str = ""
    auth_mysql_port: int = 3306
    auth_mysql_db: str = "BDRELOJ"
    auth_mysql_user: str = ""
    auth_mysql_password: str = ""
    auth_user_query: str = ("SELECT CODIGO AS id, NOMBRE AS nombre, CLAVE AS password_hash "
                            "FROM USUARIOS WHERE CODIGO = :usuario")
    admin_bootstrap: str = ""  # CODIGOs (coma) que entran como admin de la app en el primer arranque

    # --- App ---
    jwt_secret: str = "dev"
    jwt_expire_minutes: int = 480
    core_bin: str = "/usr/local/bin/ddmrp_core"
    etl_cron_hour: int = 2

    # --- Archivo plano de Siesa (requisicion inter-bodega, ver docs/Abastecimiento dia 4_15102026.xlsx) ---
    plano_tipo_docto: str = "RIT"
    plano_solicitante: str = "S688"
    plano_bodega_salida: str = "PT001"
    plano_motivo: str = "01"
    plano_unidad_medida: str = "UND"
    plano_un_movto: int = 12
    plano_dias_entrega: int = 1
    plano_referencia: str = "DDMRP"

    @property
    def pg_url(self) -> str:
        return (f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    @property
    def pg_dsn(self) -> str:  # para el binario Rust (crate postgres)
        return (f"postgres://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    def siesa_odbc(self, db: str) -> str:
        return quote_plus(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={self.siesa_host},{self.siesa_port};"
                          f"DATABASE={db};UID={self.siesa_user};PWD={self.siesa_password};"
                          f"Encrypt=optional;TrustServerCertificate=yes;")

    @property
    def mysql_url(self) -> str:
        return (f"mysql+pymysql://{self.auth_mysql_user}:{quote_plus(self.auth_mysql_password)}"
                f"@{self.auth_mysql_host}:{self.auth_mysql_port}/{self.auth_mysql_db}")


settings = Settings()
