from urllib.parse import quote, quote_plus
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
    siesa_cedi_bodega_s: str = "PT001"   # bodega del CEDI en la base Stores (empresa 21)
    siesa_cedi_bodega: str = "PT001"   # bodega del CEDI (de donde sale lo que se despacha a las tiendas), empresa 05
    siesa_cia: int = 1        # f120_id_cia
    siesa_grupo_bodegas_tienda: str = "025"   # grupo de bodegas (t152) que son tiendas
    # Items que se importan: los que tengan alguno de estos criterios ("plan:criterio", coma). 001 = CATEGORIA: 0001 productos Funat,
    # 0002 de terceros, 0003 maquila Funat. De cada item se traen TODOS sus criterios. Vacio = todos los items.
    siesa_criterios_items: str = "001:0001,001:0002,001:0003"
    siesa_plan_laboratorio: str = "006"   # plan de criterios de items que define el laboratorio
    # Estado del item en Siesa: columna de la EXTENSION del item (t121_mc_items_extensiones.f121_ind_estado). 1 activo; 0 inactivo y 2 bloqueado
    # segun el diccionario de Siesa (confirmalo con docs/sql/estado_items.sql). Si la columna no se puede leer, el ETL avisa y sigue SIN filtrar.
    siesa_item_estado_col: str = "f121_ind_estado"
    siesa_item_estado_activo: int = 1
    siesa_item_estado_bloqueado: int = 2
    # Costo promedio unitario por INSTALACION (reporte "Existencia a la fecha por bodega": "Costo prom. unit. (ins)"). Se lee de esta
    # tabla unida por item y por la instalacion de la bodega (t400.f400_id_instalacion, p.ej. F01). Las claves se deducen del prefijo
    # de la columna: <pref>_id_cia, <pref>_rowid_item_ext, <pref>_id_instalacion. Si no existen, el ETL avisa y sigue sin costos
    # (Reglas > Revisar un inventario ayuda a ubicar la tabla). Con SIESA_COSTO_TABLA vacia se lee de t400 (costo de la bodega).
    siesa_costo_tabla: str = "t132_mc_items_instalacion"
    siesa_costo_columna: str = "f132_costo_prom_uni"
    # Proveedor del item (pantalla Items de Siesa, pestaña Generales: «Proveedor» + «Sucursal»): columnas de t120_mc_items. El item tiene UN solo proveedor.
    # Los nombres son los habituales del diccionario de Siesa pero NO estan confirmados: corre docs/sql/proveedor_item.sql y, si son otros, cambialos aqui
    # (SIESA_ITEM_PROVEEDOR_COL / SIESA_ITEM_PROVEEDOR_SUC_COL). Si no se pueden leer, el ETL avisa y sigue sin proveedores.
    siesa_item_proveedor_col: str = "f120_rowid_tercero_prov"     # rowid del tercero (t200.f200_rowid)
    siesa_item_proveedor_suc_col: str = "f120_id_sucursal_prov"   # sucursal del proveedor (ej. 001)
    # Cotizaciones (t212) y IVA: moneda de compra y clase de impuesto del IVA (la del parametro @p_id_clase_imp de sp_cotizacion_consulta_compra)
    siesa_moneda_compra: str = "COP"
    siesa_um_compra: str = "UND"   # unidad de medida de la cotizacion que sirve para el costo por unidad (otra UM, p.ej. caja, cambia el precio por un factor); vacio = cualquiera
    siesa_clase_impuesto_iva: int = 1
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
    auth_buscar_query: str = ("SELECT CODIGO AS id, NOMBRE AS nombre FROM USUARIOS "
                              "WHERE CODIGO LIKE :q OR NOMBRE LIKE :q ORDER BY NOMBRE LIMIT 20")
    # Consulta opcional que dice si el usuario SIGUE activo en reloj (devuelve una fila si si). Vacia = solo se verifica que su CODIGO siga existiendo en USUARIOS.
    auth_activo_query: str = "SELECT 1 FROM USUARIOS WHERE CODIGO = :usuario AND COALESCE(activo, 1) = 1"
    auth_revalidar_minutos: int = 15   # cada cuantos minutos se vuelve a preguntar a reloj por un usuario con sesion abierta (0 = nunca)
    admin_bootstrap: str = ""  # CODIGOs (coma) que entran como admin de la app en el primer arranque

    # --- App ---
    jwt_secret: str = "dev"
    jwt_expire_minutes: int = 480     # 8 horas (JWT_EXPIRE_MINUTES en el .env)
    # Freno a la fuerza bruta del login (por usuario): tras N fallos en la ventana, ese usuario espera X minutos
    login_max_fallos: int = 5
    login_ventana_min: int = 15
    login_bloqueo_min: int = 15
    habilitar_docs: bool = False      # /docs y /openapi.json del backend (solo para desarrollo: HABILITAR_DOCS=true)
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
        return (f"postgresql+psycopg://{quote(self.postgres_user, safe='')}:{quote(self.postgres_password, safe='')}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    @property
    def pg_dsn(self) -> str:  # para el binario Rust (crate postgres)
        return (f"postgres://{quote(self.postgres_user, safe='')}:{quote(self.postgres_password, safe='')}"
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
