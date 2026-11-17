"""Conexiones de DDMRP con otros sistemas: el BPM y el web service de Siesa (envio directo de OC, contingencia). Se editan en Reglas de compras
(tabla ddmrp.conexion); si un dato esta vacio o la tabla no existe, cae al .env. Lo de la UI manda. Los secretos nunca se devuelven a la pantalla.
Si el web service no esta configurado en ninguno de los dos lados, el envio directo simplemente no hace nada (no es un error)."""
from sqlalchemy import text
from .config import settings
from .db import pg

WS_CAMPOS = ("url", "usuario", "clave", "conexion", "cia")


def _db(clave: str) -> str:
    try:
        with pg.connect() as c:
            return (c.execute(text("SELECT valor FROM ddmrp.conexion WHERE clave = :k"), {"k": clave}).scalar() or "").strip()
    except Exception:    # noqa: BLE001   (tabla aun no creada: se usa el .env)
        return ""


def _db_todo() -> dict:
    try:
        with pg.connect() as c:
            return {k: (v or "").strip() for k, v in c.execute(text("SELECT clave, valor FROM ddmrp.conexion")).all()}
    except Exception:    # noqa: BLE001
        return {}


def bpm_url() -> str:
    return (_db("bpm_url") or settings.bpm_url or "").strip()


def bpm_secret() -> str:
    return (_db("bpm_secret") or settings.bpm_secret or "").strip()


def _env_ws(empresa: str, campo: str) -> str:
    s = settings; st = empresa == "21"
    return str({"url": s.siesa_ws_url_s if st else s.siesa_ws_url,
                "usuario": s.siesa_ws_user_s if st else s.siesa_ws_user, "clave": s.siesa_ws_password_s if st else s.siesa_ws_password,
                "conexion": s.siesa_ws_conexion_s if st else s.siesa_ws_conexion, "cia": s.siesa_ws_cia_s if st else s.siesa_ws_cia}[campo] or "").strip()


def _ws_propio(datos: dict, empresa: str, campo: str) -> tuple[str, str]:
    """(valor, origen) de la empresa: lo de la UI y, si esta vacio, lo de su .env."""
    v = datos.get(f"siesa_ws_{campo}_{empresa}", "")
    if v:
        return v, "ui"
    v = _env_ws(empresa, campo)
    return (v, ".env") if v else ("", "sin configurar")


def ws_valores(empresa: str, datos: dict | None = None) -> dict:
    """URL, usuario, clave, conexion y cia del web service para la empresa. Stores (21) usa los de Funat (05) en url, usuario, clave y cia si no tiene los suyos;
    el nombre de la conexion es siempre propio. Puede devolver campos vacios."""
    datos = _db_todo() if datos is None else datos
    out = {}
    for campo in WS_CAMPOS:
        v, _ = _ws_propio(datos, empresa, campo)
        if not v and empresa == "21" and campo != "conexion":
            v, _ = _ws_propio(datos, "05", campo)
        out[campo] = v
    return out


def ws_listo(empresa: str) -> bool:
    return all(ws_valores(empresa).values())


def ws_cia(empresa: str) -> str:
    return ws_valores(empresa)["cia"]


def estado() -> dict:
    """Para la pantalla: de donde sale cada dato, sin mostrar secretos."""
    d = _db_todo()
    u, s = d.get("bpm_url", ""), d.get("bpm_secret", "")
    out = {"bpm_url": u or settings.bpm_url or "", "bpm_url_origen": "ui" if u else (".env" if settings.bpm_url else "sin configurar"),
           "bpm_secret_configurado": bool(s or settings.bpm_secret), "bpm_secret_origen": "ui" if s else (".env" if settings.bpm_secret else "sin configurar"),
           "bpm_url_vigente": bpm_url(), "ws": {}}
    for emp in ("05", "21"):
        f = {}
        for campo in WS_CAMPOS:
            v, o = _ws_propio(d, emp, campo)
            f[campo] = "" if campo == "clave" else v
            f[campo + "_origen"] = o
        f["clave_configurada"] = f["clave_origen"] != "sin configurar"
        f["listo"] = all(ws_valores(emp, d).values())
        out["ws"][emp] = f
    return out
