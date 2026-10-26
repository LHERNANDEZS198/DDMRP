"""Orden de compra directo al web service de Siesa (WSUNOEE.ImportarXML, plano de ancho fijo). Mismo canal que usa ChaTest (crear_tercero.py) para crear terceros.
Layout: docs/Imp-UnoEE «Solicitudes O.C. y contratos» -> Documentos v5 (registro 0420, 761 car.) y Movimientos v5 (registro 0421, 2.792 car.).
NO se manda el registro 0422 (descuentos) ni el 0423 (impuestos): F_LIQUIDA_IMPUESTO=1 hace que Siesa liquide el IVA con sus parametros.

Reglas de seguridad (aprendidas de ChaTest):
  * un plano por OC, para que un error no tumbe las demas;
  * antes de enviar se consulta a Siesa si ya existe una OC con esa referencia (f420_num_docto_referencia, 15 car.): si existe NO se reenvia;
  * un timeout NO es un rechazo: no se sabe si Siesa la guardo. Queda 'incierta' y se reconsulta por la referencia; nunca se reenvia a ciegas;
  * jamas se registra el sobre ni la respuesta cruda (llevan usuario y clave)."""
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import date, timedelta
from sqlalchemy import text
from .config import settings
from .db import siesa_engine

A, N = "A", "N"      # alfanumerico (a la izquierda, con espacios) / numerico (ceros a la izquierda); ("D", enteros, decimales) = decimal con punto

# (nombre, tamano, tipo). El inicio de cada campo sale de acumular los tamanos y se valida contra el total del layout.
DOC_V5 = [
    ("F_NUMERO_REG", 7, N), ("F_TIPO_REG", 4, N), ("F_SUBTIPO_REG", 2, N), ("F_VERSION_REG", 2, N), ("F_CIA", 3, N), ("F_LIQUIDA_IMPUESTO", 1, N), ("F_CONSEC_AUTO_REG", 1, N),
    ("f420_id_co", 3, A), ("f420_id_tipo_docto", 3, A), ("f420_consec_docto", 8, N), ("f420_fecha", 8, A), ("f420_id_concepto", 3, N), ("f420_id_grupo_clase_docto", 3, N),
    ("f420_id_clase_docto", 3, N), ("f420_ind_estado", 1, N), ("f420_ind_impresion", 1, N), ("f420_id_tercero_sol_comp", 15, A), ("f420_id_tercero_prov", 15, A),
    ("f420_id_sucursal_prov", 3, A), ("f420_id_cond_pago", 3, A), ("f420_ind_tasa", 1, N), ("f420_id_moneda_docto", 3, A), ("f420_id_moneda_conv", 3, A),
    ("f420_tasa_conv", 13, ("D", 8, 4)), ("f420_id_moneda_local", 3, A), ("f420_tasa_local", 13, ("D", 8, 4)), ("f420_tasa_dscto_global1", 8, ("D", 3, 4)),
    ("f420_tasa_dscto_global2", 8, ("D", 3, 4)), ("f420_notas", 255, A), ("F_IND_CONTACTO", 1, N), ("f419_contacto", 50, A), ("f419_direccion1", 40, A),
    ("f419_direccion2", 40, A), ("f419_direccion3", 40, A), ("f419_id_pais", 3, A), ("f419_id_depto", 2, A), ("f419_id_ciudad", 3, A), ("f419_id_barrio", 40, A),
    ("f419_telefono", 20, A), ("f419_fax", 20, A), ("f419_cod_postal", 10, A), ("f419_email", 50, A), ("f420_num_docto_referencia", 15, A), ("f420_id_mandato", 15, A),
    ("f420_ind_consignacion", 1, N), ("f420_id_tercero_solicit", 15, A),
]
MOV_V5 = [
    ("F_NUMERO_REG", 7, N), ("F_TIPO_REG", 4, N), ("F_SUBTIPO_REG", 2, N), ("F_VERSION_REG", 2, N), ("F_CIA", 3, N), ("f421_id_co", 3, A), ("f421_id_tipo_docto", 3, A),
    ("f421_consec_docto", 8, N), ("f421_nro_registro", 10, N), ("F_CAMPO_1", 55, A), ("f421_id_bodega", 5, A), ("f421_id_concepto", 3, N), ("f421_id_motivo", 2, A),
    ("f421_ind_obsequio", 1, N), ("f421_id_co_movto", 3, A), ("F_CAMPO_2", 2, A), ("f421_id_ccosto_movto", 15, A), ("f421_id_proyecto", 15, A), ("f421_id_unidad_medida", 4, A),
    ("f421_cant_pedida_base", 20, ("D", 15, 4)), ("f421_fecha_entrega", 8, A), ("f421_cod_item_prov", 15, A), ("f421_precio_unitario", 20, ("D", 15, 4)), ("f421_notas", 255, A),
    ("f421_detalle", 2000, A), ("F_DESC_ITEM", 40, A), ("F_ID_UM_INVENTARIO", 4, A), ("f421_id_item", 7, N), ("f421_referencia_item", 50, A), ("f421_codigo_barras", 20, A),
    ("f421_id_ext1_detalle", 20, A), ("f421_id_ext2_detalle", 20, A), ("f421_id_un_movto", 20, A), ("f421_tasa_dscto_condicionado", 8, ("D", 3, 4)),
    ("f850_id_tipo_docto_op", 3, A), ("f850_consec_docto_op", 8, N), ("f865_id_item_op", 7, N), ("f865_referencia_item_op", 50, A), ("f865_codigo_barras_item_op", 20, A),
    ("f851_id_ext1_detalle_item_op", 20, A), ("f851_id_ext2_detalle_item_op", 20, A), ("f865_numero_operacion", 10, N),
]
LARGO_DOC, LARGO_MOV = 761, 2792
assert sum(c[1] for c in DOC_V5) == LARGO_DOC and sum(c[1] for c in MOV_V5) == LARGO_MOV, "el layout de OC no suma lo que dice el xls de Siesa"


def _ascii(t) -> str:
    """Sin tildes ni caracteres raros (el plano es de ancho fijo por bytes)."""
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[\r\n\t]+", " ", t).strip()


def _campo(nombre: str, tam: int, tipo, valor) -> str:
    if isinstance(tipo, tuple):
        _, ent, dec = tipo
        v = float(valor or 0)
        s = f"{v:0{ent + dec + 1}.{dec}f}"
        if len(s) > tam:
            raise ValueError(f"{nombre}: {v} no cabe en {ent} enteros y {dec} decimales")
        return s
    if tipo == N:
        s = "0" if valor in (None, "") else str(valor).strip()
        if not s.isdigit() or len(s) > tam:
            raise ValueError(f"{nombre}: '{valor}' no es un número de máximo {tam} dígitos")
        return s.zfill(tam)
    s = _ascii(valor)
    if len(s) > tam:
        if nombre in ("f420_notas", "f421_notas", "f421_detalle"):
            return s[:tam]
        raise ValueError(f"{nombre}: '{s}' pasa de {tam} caracteres")
    return s.ljust(tam)


def _registro(spec: list, valores: dict) -> str:
    out = "".join(_campo(n, t, tp, valores.get(n)) for n, t, tp in spec)
    return out


def referencia(oc_id: int) -> str:
    r = f"{settings.oc_referencia_prefijo}{int(oc_id):08d}"
    if len(r) > 15:
        raise ValueError(f"La referencia '{r}' pasa de 15 caracteres (límite de f420_num_docto_referencia)")
    return r


def cia_ws(empresa: str) -> str:
    return (settings.siesa_ws_cia_s or settings.siesa_ws_cia) if empresa == "21" else settings.siesa_ws_cia


def bodega_oc(empresa: str) -> str:
    return settings.oc_bodega or (settings.siesa_cedi_bodega_s if empresa == "21" else settings.siesa_cedi_bodega)


def armar_plano(oc: dict, lineas: list[dict]) -> str:
    """oc: empresa, id, comprador, proveedor_id, sucursal, cond_pago, fecha(date). lineas: producto_id, cantidad, costo, fecha_entrega(date), descripcion.
    Devuelve el plano completo (control 0000, 0420, N x 0421, control 9999) separado por CRLF."""
    if not lineas:
        raise ValueError("La OC no tiene líneas")
    cia = int(cia_ws(oc["empresa"]) or 0)
    ymd = lambda d: d.strftime("%Y%m%d")
    comprador = str(oc["comprador"] or "").strip()
    if not comprador:
        raise ValueError("Falta el comprador (cédula): se toma del usuario que envía")
    doc = {
        "F_NUMERO_REG": 2, "F_TIPO_REG": 420, "F_SUBTIPO_REG": 0, "F_VERSION_REG": 5, "F_CIA": cia, "F_LIQUIDA_IMPUESTO": 1, "F_CONSEC_AUTO_REG": 1,
        "f420_id_co": settings.oc_co, "f420_id_tipo_docto": settings.oc_tipo_docto, "f420_consec_docto": 0, "f420_fecha": ymd(oc["fecha"]),
        "f420_id_concepto": 401, "f420_id_grupo_clase_docto": 402, "f420_id_clase_docto": 404, "f420_ind_estado": settings.oc_estado, "f420_ind_impresion": 0,
        "f420_id_tercero_sol_comp": comprador, "f420_id_tercero_prov": oc["proveedor_id"], "f420_id_sucursal_prov": oc["sucursal"], "f420_id_cond_pago": oc["cond_pago"],
        "f420_ind_tasa": 1, "f420_id_moneda_docto": "COP", "f420_id_moneda_conv": "COP", "f420_tasa_conv": 1, "f420_id_moneda_local": "COP", "f420_tasa_local": 1,
        "f420_notas": f"{settings.oc_notas} (OC {oc['id']})", "F_IND_CONTACTO": 1, "f420_num_docto_referencia": referencia(oc["id"]), "f420_ind_consignacion": 0,
        "f420_id_tercero_solicit": comprador,
    }
    reg = [_registro(DOC_V5, doc)]
    for n, l in enumerate(lineas, start=1):
        mov = {
            "F_NUMERO_REG": n + 2, "F_TIPO_REG": 421, "F_SUBTIPO_REG": 0, "F_VERSION_REG": 5, "F_CIA": cia, "f421_id_co": settings.oc_co,
            "f421_id_tipo_docto": settings.oc_tipo_docto, "f421_consec_docto": 0, "f421_nro_registro": n, "f421_id_bodega": bodega_oc(oc["empresa"]),
            "f421_id_concepto": 401, "f421_id_motivo": settings.oc_motivo, "f421_ind_obsequio": 0, "f421_id_co_movto": settings.oc_co, "f421_id_unidad_medida": settings.oc_um,
            "f421_cant_pedida_base": l["cantidad"], "f421_fecha_entrega": ymd(l["fecha_entrega"]), "f421_precio_unitario": l["costo"],
            "f421_notas": (l.get("descripcion") or "")[:60], "f421_referencia_item": l["producto_id"], "f421_id_un_movto": settings.oc_un_movto,
        }
        if not (l["costo"] and l["costo"] > 0):
            raise ValueError(f"{l['producto_id']}: sin costo (Siesa exige precio mayor a 0)")
        if not (l["cantidad"] and l["cantidad"] > 0):
            raise ValueError(f"{l['producto_id']}: cantidad 0")
        reg.append(_registro(MOV_V5, mov))
    # numeros de registro del archivo: control = 1, documento = 2, movimientos 3..n+2 (arriba), cierre = total de lineas
    cab = f"{1:07d}0000" + "00" + "01" + f"{cia:03d}"
    cierre = f"{len(reg) + 2:07d}9999" + "00" + "01" + f"{cia:03d}"
    return "\r\n".join([cab] + reg + [cierre]) + "\r\n"


# ---------------- web service ----------------
class SiesaNoDisponible(Exception):
    """Timeout o conexion caida: NO se sabe si Siesa alcanzo a importar."""


def ws_config(empresa: str) -> dict:
    s = settings
    st = empresa == "21"
    c = {"URL": (s.siesa_ws_url_s if st else "") or s.siesa_ws_url, "USUARIO": (s.siesa_ws_user_s if st else "") or s.siesa_ws_user,
         "CLAVE": (s.siesa_ws_password_s if st else "") or s.siesa_ws_password, "NOMBRE_CONEXION": s.siesa_ws_conexion_s if st else s.siesa_ws_conexion, "CIA": cia_ws(empresa)}
    falta = [k for k in ("URL", "USUARIO", "CLAVE", "NOMBRE_CONEXION", "CIA") if not str(c[k]).strip()]
    if falta:
        raise ValueError(f"Falta configurar el web service de Siesa para la empresa {empresa} (.env SIESA_WS_*): {', '.join(falta)}")
    return c


def _escape(v) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _soap(url: str, operacion: str, interior: str, timeout: int) -> tuple[int, str]:
    sobre = (f'<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
             f'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><{operacion} xmlns="http://tempuri.org/">{interior}</{operacion}></soap:Body></soap:Envelope>')
    req = urllib.request.Request(url, data=sobre.encode("utf-8"), method="POST",
                                 headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"http://tempuri.org/{operacion}"'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        raise SiesaNoDisponible(f"El web service de Siesa no respondió en {timeout}s ({type(e).__name__}): no se sabe si la OC quedó creada. Se reconsulta por la referencia antes de reintentar.") from e


def _entre(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S | re.I)
    return m.group(1).strip() if m else ""


def importar(plano: str, empresa: str) -> tuple[str, str]:
    """Manda el plano. Devuelve ('ok'|'error'|'incierto', mensaje)."""
    ws = ws_config(empresa)
    lineas = [l for l in plano.rstrip("\r\n").split("\r\n") if l.strip()]
    datos = "".join(f"<Linea>{_escape(l)}</Linea>" for l in lineas)
    cuerpo = (f"<Importar><NombreConexion>{_escape(ws['NOMBRE_CONEXION'])}</NombreConexion><IdCia>{_escape(ws['CIA'])}</IdCia><Usuario>{_escape(ws['USUARIO'])}</Usuario>"
              f"<Clave>{_escape(ws['CLAVE'])}</Clave><Datos>{datos}</Datos></Importar>")
    try:
        status, body = _soap(ws["URL"], "ImportarXML", f"<pvstrDatos>{_escape(cuerpo)}</pvstrDatos><printTipoError>0</printTipoError>", settings.siesa_ws_timeout)
    except SiesaNoDisponible as e:
        return "incierto", str(e)
    body = body.replace(ws["CLAVE"], "***").replace(ws["USUARIO"], "***")
    tipo = _entre(body, "printTipoError")
    if status == 200 and tipo == "0":
        return "ok", "Importación exitosa"
    filas = re.findall(r"<Table[^>]*>.*?<f_nro_linea>(?P<l>\d*)</f_nro_linea>.*?<f_tipo_reg>(?P<t>[^<]*)</f_tipo_reg>.*?<f_detalle>(?P<d>.*?)</f_detalle>.*?</Table>", body, re.S)
    if filas:
        msgs = []
        for linea, tr, det in filas:
            det = det.strip()
            m = re.search(r"Posici[oó]n inicial:\s*(\d+)", det)
            campo = ""
            if m:
                spec = DOC_V5 if tr.strip().lstrip("0") == "420" else MOV_V5 if tr.strip().lstrip("0") == "421" else None
                if spec:
                    pos, ini = int(m.group(1)), 1
                    for n, t, _ in spec:
                        if ini <= pos < ini + t:
                            campo = f" {n}"; break
                        ini += t
            msgs.append(f"L{linea}{campo}: {det}")
        return "error", " | ".join(msgs)[:1500]
    return "error", f"HTTP {status}, printTipoError={tipo or '?'} -- " + re.sub(r">\s+<", "><", body).strip()[:1200]


def buscar_en_siesa(empresa: str, ref: str) -> dict | None:
    """OC no anulada con esa referencia (la llave anti-duplicados). None = no existe. Lanza si no se pudo consultar: ante la duda NO se envia."""
    db = settings.siesa_db_s if empresa == "21" else settings.siesa_db
    if not db:
        raise RuntimeError(f"No hay base de Siesa configurada para la empresa {empresa}")
    with siesa_engine(db).connect() as c:
        r = c.execute(text("SELECT TOP 1 RTRIM(f420_id_tipo_docto) AS tipo, f420_consec_docto AS consec, f420_ind_estado AS estado FROM t420_cm_oc_docto "
                           "WHERE f420_id_cia = :cia AND RTRIM(f420_num_docto_referencia) = :ref AND f420_ind_estado <> 9 ORDER BY f420_rowid DESC"),
                      {"cia": settings.siesa_cia, "ref": ref}).mappings().first()
    return dict(r) if r else None


def fecha_entrega(hoy: date, lead_time) -> date:
    return hoy + timedelta(days=int(round(float(lead_time or 0))))
