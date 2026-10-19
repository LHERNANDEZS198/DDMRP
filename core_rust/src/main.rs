//! Binario: lee Postgres, calcula DDMRP en paralelo y escribe sugerencias_envio.
//! Uso: ddmrp_core --ejecucion-id <id> [--fecha YYYY-MM-DD]
//! Entorno: DATABASE_URL=postgres://user:pass@host:5432/db
use anyhow::{bail, Context, Result};
use ddmrp_core::{calcular_lote, Entrada, Factores, Parametros, Tramo};
use postgres::{Client, NoTls, Row};
use std::io::Write;

/// $1 = fecha de calculo (texto YYYY-MM-DD). Se leen 12 meses calendario terminando en el mes de $1; el motor usa los ultimos `meses_historia`.
/// Universo: bodega/producto con ventas en la ventana, vectorizacion, pronostico, inventario o cotas.
/// Items REC (ddmrp.v_item_rec): su venta, inventario y transitos se suman al item ORIGINAL y el REC no se calcula aparte.
/// Items inactivos o bloqueados en Siesa (ddmrp.item_estado) no entran, salvo que la regla solo_items_activos este en 0.
/// Solo entran items del maestro (ddmrp.maestro_item = los que pasan el filtro de criterios SIESA_CRITERIOS_ITEMS): lo que este en
/// inventario/ventas pero fuera de la seleccion (ej. materia prima) no se calcula. Con el maestro vacio (antes del primer ETL) no se filtra.
const SQL_ENTRADA: &str = r#"
WITH meses AS (
  SELECT n, to_char(date_trunc('month', $1::text::date) - make_interval(months => 11 - n), 'YYYYMM') AS mes
  FROM generate_series(0, 11) AS n
),
rec AS (SELECT empresa, rec_id, original_id FROM ddmrp.v_item_rec),
v AS (
  SELECT a.empresa, a.bodega_id, COALESCE(r.original_id, a.producto_id) AS producto_id,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 0), 0)::float8 AS m0,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 1), 0)::float8 AS m1,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 2), 0)::float8 AS m2,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 3), 0)::float8 AS m3,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 4), 0)::float8 AS m4,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 5), 0)::float8 AS m5,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 6), 0)::float8 AS m6,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 7), 0)::float8 AS m7,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 8), 0)::float8 AS m8,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 9), 0)::float8 AS m9,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 10), 0)::float8 AS m10,
    COALESCE(SUM(a.cantidad) FILTER (WHERE m.n = 11), 0)::float8 AS m11
  FROM ddmrp.ventas_mensual a JOIN meses m ON m.mes = a.mes
  LEFT JOIN rec r ON r.empresa = a.empresa AND r.rec_id = a.producto_id
  GROUP BY a.empresa, a.bodega_id, COALESCE(r.original_id, a.producto_id)
),
inv AS (
  SELECT ia.empresa, ia.bodega_id, COALESCE(r.original_id, ia.producto_id) AS producto_id, SUM(ia.disponible) AS disponible
  FROM ddmrp.inventario_actual ia
  LEFT JOIN rec r ON r.empresa = ia.empresa AND r.rec_id = ia.producto_id
  GROUP BY 1, 2, 3
),
tr AS (
  SELECT tt.empresa, tt.bodega_id, COALESCE(r.original_id, tt.producto_id) AS producto_id, SUM(tt.cantidad) AS cant
  FROM ddmrp.transitos tt
  LEFT JOIN rec r ON r.empresa = tt.empresa AND r.rec_id = tt.producto_id
  GROUP BY 1, 2, 3
),
llaves AS (
  SELECT empresa, bodega_id, producto_id FROM v
  UNION SELECT empresa, bodega_id, producto_id FROM ddmrp.abast_vectorizacion WHERE vectorizacion <> 0
  UNION SELECT empresa, bodega_id, producto_id FROM ddmrp.pronostico WHERE pronostico <> 0
  UNION SELECT empresa, bodega_id, producto_id FROM inv WHERE disponible <> 0
  UNION SELECT empresa, bodega_id, producto_id FROM ddmrp.abast_control_referencias
)
SELECT b.empresa, k.bodega_id, k.producto_id,
  COALESCE(v.m0, 0) AS m0, COALESCE(v.m1, 0) AS m1, COALESCE(v.m2, 0) AS m2, COALESCE(v.m3, 0) AS m3, COALESCE(v.m4, 0) AS m4, COALESCE(v.m5, 0) AS m5, COALESCE(v.m6, 0) AS m6, COALESCE(v.m7, 0) AS m7, COALESCE(v.m8, 0) AS m8, COALESCE(v.m9, 0) AS m9, COALESCE(v.m10, 0) AS m10, COALESCE(v.m11, 0) AS m11,
  COALESCE(p.pronostico, 0)::float8        AS pronostico,
  COALESCE(b.leadtime, 0)::float8          AS lead_time,
  COALESCE(b.frecuencia, 1)::float8        AS frecuencia,
  COALESCE(ud.unidad_despacho, 1)::float8  AS unidad_despacho,
  COALESCE(c.cota_maxima, 0)::float8       AS cota_max,
  COALESCE(c.cota_minima, 0)::float8       AS cota_min,
  COALESCE(pr.indicativo, 0)::int2         AS promo,
  COALESCE(ve.vectorizacion, 0)::float8    AS vectorizacion,
  (EXISTS (SELECT 1 FROM ddmrp.item_condenado cd WHERE cd.empresa = k.empresa AND cd.producto_id = k.producto_id AND cd.bodega_id IN (k.bodega_id, '*')))::int::int2 AS condenado,
  COALESCE(i.disponible, 0)::float8        AS inventario,
  COALESCE(t.cant, 0)::float8              AS en_transito,
  COALESCE(d.cantidad, 0)::float8          AS demanda_calificada,
  COALESCE(oi.regla, ol.regla, 0)::int2    AS regla_objetivo
FROM llaves k
JOIN ddmrp.abast_bitacora b ON b.empresa = k.empresa AND b.bodega_id = k.bodega_id
LEFT JOIN v ON v.empresa = k.empresa AND v.bodega_id = k.bodega_id AND v.producto_id = k.producto_id
LEFT JOIN ddmrp.pronostico p ON p.empresa = b.empresa AND p.bodega_id = k.bodega_id AND p.producto_id = k.producto_id
LEFT JOIN ddmrp.abast_unidad_despacho ud ON ud.empresa = b.empresa AND ud.producto_id = k.producto_id
LEFT JOIN ddmrp.abast_control_referencias c ON c.empresa = b.empresa AND c.bodega_id = k.bodega_id AND c.producto_id = k.producto_id
LEFT JOIN ddmrp.promocion pr ON pr.empresa = b.empresa AND pr.producto_id = k.producto_id
LEFT JOIN ddmrp.abast_vectorizacion ve ON ve.empresa = b.empresa AND ve.bodega_id = k.bodega_id AND ve.producto_id = k.producto_id
LEFT JOIN inv i ON i.empresa = k.empresa AND i.bodega_id = k.bodega_id AND i.producto_id = k.producto_id
LEFT JOIN tr t ON t.empresa = k.empresa AND t.bodega_id = k.bodega_id AND t.producto_id = k.producto_id
LEFT JOIN ddmrp.demanda_calificada d ON d.empresa = k.empresa AND d.bodega_id = k.bodega_id AND d.producto_id = k.producto_id
LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = k.producto_id
LEFT JOIN ddmrp.reposicion_item oi ON oi.producto_id = k.producto_id
LEFT JOIN ddmrp.reposicion_laboratorio ol ON ol.laboratorio = mi.categoria
WHERE NOT EXISTS (SELECT 1 FROM rec r2 WHERE r2.empresa = b.empresa AND r2.rec_id = k.producto_id)
  AND (mi.producto_id IS NOT NULL OR NOT EXISTS (SELECT 1 FROM ddmrp.maestro_item))
  AND (b.leadtime IS NOT NULL OR b.frecuencia IS NOT NULL)   -- bodega en la bitacora sin lead time ni frecuencia = no configurada: no se calcula
  AND ((SELECT COALESCE(max(valor), 1) FROM ddmrp.parametro WHERE clave = 'solo_items_activos') = 0
       OR NOT EXISTS (SELECT 1 FROM ddmrp.item_estado ie WHERE ie.empresa = b.empresa AND ie.producto_id = k.producto_id AND ie.estado <> 1))
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
            "regla_disparo" => p.regla_disparo = v as u8,
            "regla_objetivo" => p.regla_objetivo = v as u8,
            "regla_redondeo" => p.regla_redondeo = v as u8,
            "sumar_vectorizacion" => p.sumar_vectorizacion = v != 0.0,
            "incluir_transito" => p.incluir_transito = v != 0.0,
            "restar_demanda_calificada" => p.restar_demanda_calificada = v != 0.0,
            "cantidad_minima" => p.cantidad_minima = v,
            "meses_historia" => p.meses_historia = (v as usize).clamp(2, 12),
            "meses_adu" => p.meses_adu = (v as usize).clamp(1, 12),
            "pron_meses_minimos" => p.pron_meses_minimos = (v as usize).min(12),
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

    let rows = client.query(SQL_ENTRADA, &[&fecha])?;
    let items: Vec<Entrada> = rows
        .iter()
        .map(|r| Entrada {
            empresa: r.get("empresa"),
            bodega_id: r.get("bodega_id"),
            producto_id: r.get("producto_id"),
            // m0 = mes-6 (el mas antiguo) ... m6 = mes actual
            ventas: (0..12).map(|i| f(r, &format!("m{i}"))).collect(),
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
            regla_objetivo: r.get::<_, i16>("regla_objetivo") as u8,
        })
        .collect();
    if items.is_empty() {
        bail!("no hay combinaciones bodega/producto para calcular (ventas_mensual / abast_bitacora vacias?)");
    }

    let condenado: Vec<bool> = rows.iter().map(|r| r.get::<_, i16>("condenado") != 0).collect();
    let mut res = calcular_lote(&items, &factores, &params);
    // NxP (condenado): se calcula el buffer pero no se despacha nada
    for (r, c) in res.iter_mut().zip(&condenado) {
        if *c { r.cantidad_sugerida = 0.0; }
    }

    // Escritura masiva via COPY (CSV); los ids son texto sin comas, se entrecomillan por seguridad.
    let q = |s: &str| format!("\"{}\"", s.replace('"', "\"\""));
    let mut w = client.copy_in(
        "COPY ddmrp.sugerencias_envio (ejecucion_id, fecha_calculo, empresa, bodega_id, producto_id, adu, iv, forecast, \
         lead_time, frecuencia, unidad_despacho, zrb, zrs, za, zv, tor, toy, tog, toy_aj, tog_aj, inventario, en_transito, \
         demanda_calificada, flujo_neto, pct_buffer, zona, vectorizacion, cantidad_sugerida, condenado, regla_objetivo) FROM STDIN WITH (FORMAT csv)",
    )?;
    for (i, r) in res.iter().enumerate() {
        let z = &r.zonas;
        writeln!(
            w,
            "{},{},{},{},{},{:.2},{:.4},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.2},{:.3},{:.3},{:.3},{:.3},{:.2},{},{:.2},{:.3},{},{}",
            ejecucion_id, fecha, q(&r.empresa), q(&r.bodega_id), q(&r.producto_id),
            num(r.adu), num(r.iv), num(r.forecast), r.lead_time, r.frecuencia, r.unidad_despacho,
            z.zrb, z.zrs, z.za, z.zv, z.tor, z.toy, z.tog, r.toy_aj, r.tog_aj,
            r.inventario, r.en_transito, r.demanda_calificada, r.flujo_neto, num(r.pct_buffer),
            r.zona.as_db(), r.vectorizacion, r.cantidad_sugerida, condenado[i], items[i].regla_objetivo
        )?;
    }
    w.finish()?;
    println!("{{\"ok\":true,\"filas\":{}}}", res.len());
    Ok(())
}
