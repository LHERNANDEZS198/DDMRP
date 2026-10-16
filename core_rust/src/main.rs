//! Binario: lee Postgres, calcula DDMRP en paralelo y escribe sugerencias_envio.
//! Uso: ddmrp_core --ejecucion-id <id> [--fecha YYYY-MM-DD]
//! Entorno: DATABASE_URL=postgres://user:pass@host:5432/db
use anyhow::{bail, Context, Result};
use ddmrp_core::{calcular_lote, Entrada, Factores, Parametros, Tramo};
use postgres::{Client, NoTls, Row};
use std::io::Write;

/// $1 = fecha de calculo (texto YYYY-MM-DD). Ventana: 7 meses calendario terminando en el mes de $1.
/// Universo: bodega/producto con ventas en la ventana, vectorizacion, pronostico, inventario o cotas.
const SQL_ENTRADA: &str = r#"
WITH meses AS (
  SELECT n, to_char(date_trunc('month', $1::text::date) - make_interval(months => 6 - n), 'YYYYMM') AS mes
  FROM generate_series(0, 6) AS n
),
v AS (
  SELECT a.bodega_id, a.producto_id,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 0), 0)::float8 AS m0,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 1), 0)::float8 AS m1,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 2), 0)::float8 AS m2,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 3), 0)::float8 AS m3,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 4), 0)::float8 AS m4,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 5), 0)::float8 AS m5,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 6), 0)::float8 AS m6
  FROM ddmrp.abast_ventas a JOIN meses m ON m.mes = a.mes
  GROUP BY a.bodega_id, a.producto_id
),
llaves AS (
  SELECT bodega_id, producto_id FROM v
  UNION SELECT bodega_id, producto_id FROM ddmrp.abast_vectorizacion WHERE vectorizacion <> 0
  UNION SELECT bodega_id, producto_id FROM ddmrp.pronostico WHERE pronostico <> 0
  UNION SELECT bodega_id, producto_id FROM ddmrp.inventario_actual WHERE disponible <> 0
  UNION SELECT bodega_id, producto_id FROM ddmrp.abast_control_referencias
)
SELECT b.empresa, k.bodega_id, k.producto_id,
  COALESCE(v.m0, 0) AS m0, COALESCE(v.m1, 0) AS m1, COALESCE(v.m2, 0) AS m2, COALESCE(v.m3, 0) AS m3,
  COALESCE(v.m4, 0) AS m4, COALESCE(v.m5, 0) AS m5, COALESCE(v.m6, 0) AS m6,
  COALESCE(p.pronostico, 0)::float8        AS pronostico,
  COALESCE(b.leadtime, 0)::float8          AS lead_time,
  COALESCE(b.frecuencia, 1)::float8        AS frecuencia,
  COALESCE(ud.unidad_despacho, 1)::float8  AS unidad_despacho,
  COALESCE(c.cota_maxima, 0)::float8       AS cota_max,
  COALESCE(c.cota_minima, 0)::float8       AS cota_min,
  COALESCE(pr.indicativo, 0)::int2         AS promo,
  COALESCE(ve.vectorizacion, 0)::float8    AS vectorizacion,
  COALESCE(i.disponible, 0)::float8        AS inventario,
  COALESCE(t.cant, 0)::float8              AS en_transito,
  COALESCE(d.cantidad, 0)::float8          AS demanda_calificada
FROM llaves k
JOIN ddmrp.abast_bitacora b ON b.bodega_id = k.bodega_id
LEFT JOIN v ON v.bodega_id = k.bodega_id AND v.producto_id = k.producto_id
LEFT JOIN ddmrp.pronostico p ON p.empresa = b.empresa AND p.bodega_id = k.bodega_id AND p.producto_id = k.producto_id
LEFT JOIN ddmrp.abast_unidad_despacho ud ON ud.empresa = b.empresa AND ud.producto_id = k.producto_id
LEFT JOIN ddmrp.abast_control_referencias c ON c.empresa = b.empresa AND c.bodega_id = k.bodega_id AND c.producto_id = k.producto_id
LEFT JOIN ddmrp.promocion pr ON pr.empresa = b.empresa AND pr.producto_id = k.producto_id
LEFT JOIN ddmrp.abast_vectorizacion ve ON ve.empresa = b.empresa AND ve.bodega_id = k.bodega_id AND ve.producto_id = k.producto_id
LEFT JOIN ddmrp.inventario_actual i ON i.bodega_id = k.bodega_id AND i.producto_id = k.producto_id
LEFT JOIN (SELECT producto_id, bodega_id, SUM(cantidad) AS cant FROM ddmrp.transitos GROUP BY 1, 2) t
       ON t.bodega_id = k.bodega_id AND t.producto_id = k.producto_id
LEFT JOIN ddmrp.demanda_calificada d ON d.bodega_id = k.bodega_id AND d.producto_id = k.producto_id
"#;

fn arg(name: &str) -> Option<String> {
    let a: Vec<String> = std::env::args().collect();
    a.iter().position(|x| x == name).and_then(|p| a.get(p + 1).cloned())
}

fn f(r: &Row, col: &str) -> f64 {
    r.get::<_, f64>(col)
}

fn leer_factores(client: &mut Client) -> Result<Factores> {
    let mut lt = vec![];
    let mut var = vec![];
    for r in client.query(
        "SELECT tipo, factor::float8, desde::float8, hasta::float8 FROM ddmrp.factor_tramo",
        &[],
    )? {
        let t = Tramo { factor: r.get(1), desde: r.get(2), hasta: r.get(3) };
        match r.get::<_, String>(0).as_str() {
            "LT" => lt.push(t),
            _ => var.push(t),
        }
    }
    if lt.is_empty() || var.is_empty() {
        bail!("ddmrp.factor_tramo sin tramos LT/VAR");
    }
    Ok(Factores { lt, var })
}

fn leer_parametros(client: &mut Client) -> Result<Parametros> {
    let mut p = Parametros::default();
    for r in client.query("SELECT clave, valor::float8 FROM ddmrp.parametro", &[])? {
        let v: f64 = r.get(1);
        match r.get::<_, String>(0).as_str() {
            "mult_cota_max_promo" => p.mult_cota_max_promo = v,
            "mult_cota_min_promo" => p.mult_cota_min_promo = v,
            "adu_bajo_min" => p.adu_bajo_min = v,
            "adu_bajo_max" => p.adu_bajo_max = v,
            _ => {}
        }
    }
    Ok(p)
}

fn num(x: f64) -> f64 {
    if x.is_finite() { x } else { 0.0 }
}

fn main() -> Result<()> {
    let url = std::env::var("DATABASE_URL").context("falta DATABASE_URL")?;
    let ejecucion_id: i64 = arg("--ejecucion-id").context("falta --ejecucion-id")?.parse()?;
    let fecha_arg = arg("--fecha");

    let mut client = Client::connect(&url, NoTls)?;
    let fecha: String = match fecha_arg {
        Some(f) => client.query_one("SELECT $1::text::date::text", &[&f])?.get(0),
        None => client.query_one("SELECT CURRENT_DATE::text", &[])?.get(0),
    };

    let factores = leer_factores(&mut client)?;
    let params = leer_parametros(&mut client)?;

    let items: Vec<Entrada> = client
        .query(SQL_ENTRADA, &[&fecha])?
        .iter()
        .map(|r| Entrada {
            empresa: r.get("empresa"),
            bodega_id: r.get("bodega_id"),
            producto_id: r.get("producto_id"),
            // m0 = mes-6 (el mas antiguo) ... m6 = mes actual
            ventas: [f(r, "m0"), f(r, "m1"), f(r, "m2"), f(r, "m3"), f(r, "m4"), f(r, "m5"), f(r, "m6")],
            pronostico: f(r, "pronostico"),
            lead_time: f(r, "lead_time"),
            frecuencia: f(r, "frecuencia"),
            unidad_despacho: f(r, "unidad_despacho"),
            cota_max: f(r, "cota_max"),
            cota_min: f(r, "cota_min"),
            promo: r.get("promo"),
            vectorizacion: f(r, "vectorizacion"),
            inventario: f(r, "inventario"),
            en_transito: f(r, "en_transito"),
            demanda_calificada: f(r, "demanda_calificada"),
        })
        .collect();
    if items.is_empty() {
        bail!("no hay combinaciones bodega/producto para calcular (abast_ventas / abast_bitacora vacias?)");
    }

    let res = calcular_lote(&items, &factores, &params);

    // Escritura masiva via COPY (CSV); los ids son texto sin comas, se entrecomillan por seguridad.
    let q = |s: &str| format!("\"{}\"", s.replace('"', "\"\""));
    let mut w = client.copy_in(
        "COPY ddmrp.sugerencias_envio (ejecucion_id, fecha_calculo, empresa, bodega_id, producto_id, adu, iv, forecast, \
         lead_time, frecuencia, unidad_despacho, zrb, zrs, za, zv, tor, toy, tog, toy_aj, tog_aj, inventario, en_transito, \
         demanda_calificada, flujo_neto, pct_buffer, zona, vectorizacion, cantidad_sugerida) FROM STDIN WITH (FORMAT csv)",
    )?;
    for r in &res {
        let z = &r.zonas;
        writeln!(
            w,
            "{},{},{},{},{},{:.2},{:.4},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.3},{:.3},{:.3},{:.3},{:.2},{},{:.2},{:.3}",
            ejecucion_id, fecha, q(&r.empresa), q(&r.bodega_id), q(&r.producto_id),
            num(r.adu), num(r.iv), num(r.forecast), r.lead_time, r.frecuencia, r.unidad_despacho,
            z.zrb, z.zrs, z.za, z.zv, z.tor, z.toy, z.tog, r.toy_aj, r.tog_aj,
            r.inventario, r.en_transito, r.demanda_calificada, r.flujo_neto, num(r.pct_buffer),
            r.zona.as_db(), r.vectorizacion, r.cantidad_sugerida
        )?;
    }
    w.finish()?;
    println!("{{\"ok\":true,\"filas\":{}}}", res.len());
    Ok(())
}
