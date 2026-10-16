from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_db: str = "ddmrp"
    postgres_user: str = "ddmrp"
    postgres_password: str = ""
    postgres_host: str = "db"
    postgres_port: int = 5432

    siesa_host: str = ""
    siesa_port: int = 1433
    siesa_db: str = ""
    siesa_user: str = ""
    siesa_password: str = ""

    auth_mysql_host: str = ""
    auth_mysql_port: int = 3306
    auth_mysql_db: str = "reloj"
    auth_mysql_user: str = ""
    auth_mysql_password: str = ""
    auth_user_query: str = ""

    jwt_secret: str = "dev"
    jwt_expire_minutes: int = 480
    core_bin: str = "/usr/local/bin/ddmrp_core"
    etl_cron_hour: int = 2

    @property
    def pg_url(self) -> str:
        return (f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    @property
    def pg_dsn(self) -> str:  # para el binario Rust (crate postgres)
        return (f"postgres://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    @property
    def siesa_url(self) -> str:
        return (f"mssql+pyodbc://{self.siesa_user}:{self.siesa_password}@{self.siesa_host}:{self.siesa_port}/"
                f"{self.siesa_db}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes")

    @property
    def mysql_url(self) -> str:
        return (f"mysql+pymysql://{self.auth_mysql_user}:{self.auth_mysql_password}"
                f"@{self.auth_mysql_host}:{self.auth_mysql_port}/{self.auth_mysql_db}")


settings = Settings()
