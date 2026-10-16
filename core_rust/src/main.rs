//! Binario: lee Postgres, calcula DDMRP en paralelo y escribe sugerencias_envio.
//! Uso: ddmrp_core --ejecucion-id <id> [--fecha YYYY-MM-DD]
//! Entorno: DATABASE_URL=postgres://user:pass@host:5432/db
use anyhow::{bail, Context, Result};
use ddmrp_core::{calcular_lote, ItemBodega};
use postgres::{Client, NoTls};
use std::io::Write;

const SQL_ENTRADA: &str = r#"
SELECT c.producto_id, c.bodega_id,
       COALESCE(v.total, 0)::float8 / c.ventana_adu_dias AS adu,
       c.lead_time_dias::float8, c.factor_lead_time::float8, c.factor_variabilidad::float8,
       c.factor_zona_roja::float8, c.factor_zona_amarilla::float8, c.factor_zona_verde::float8,
       c.ciclo_pedido_dias::float8, c.cantidad_minima::float8, c.multiplo_empaque::float8,
       COALESCE(i.disponible, 0)::float8,
       COALESCE(t.cant, 0)::float8,
       COALESCE(d.cantidad, 0)::float8
FROM ddmrp.maestro_item_bodega_config c
LEFT JOIN LATERAL (
    SELECT SUM(h.cantidad) AS total FROM ddmrp.historico_ventas h
    WHERE h.producto_id = c.producto_id AND h.bodega_id = c.bodega_id
      AND h.fecha >= $1::date - c.ventana_adu_dias AND h.fecha < $1::date
) v ON TRUE
LEFT JOIN ddmrp.inventario_actual i USING (producto_id, bodega_id)
LEFT JOIN (SELECT producto_id, bodega_id, SUM(cantidad) cant FROM ddmrp.transitos GROUP BY 1,2) t
       USING (producto_id, bodega_id)
LEFT JOIN ddmrp.demanda_calificada d USING (producto_id, bodega_id)
WHERE c.activo
"#;

fn arg(name: &str) -> Option<String> {
    let a: Vec<String> = std::env::args().collect();
    a.iter().position(|x| x == name).and_then(|p| a.get(p + 1).cloned())
}

fn main() -> Result<()> {
    let url = std::env::var("DATABASE_URL").context("falta DATABASE_URL")?;
    let ejecucion_id: i64 = arg("--ejecucion-id").context("falta --ejecucion-id")?.parse()?;
    let fecha = arg("--fecha").unwrap_or_else(|| "now".into());

    let mut client = Client::connect(&url, NoTls)?;
    let fecha_sql: String = client
        .query_one("SELECT (CASE WHEN $1 = 'now' THEN CURRENT_DATE ELSE $1::date END)::text", &[&fecha])?
        .get(0);

    let rows = client.query(SQL_ENTRADA, &[&fecha_sql])?;
    let items: Vec<ItemBodega> = rows
        .iter()
        .map(|r| ItemBodega {
            producto_id: r.get(0),
            bodega_id: r.get(1),
            adu: r.get(2),
            lead_time_dias: r.get(3),
            factor_lead_time: r.get(4),
            factor_variabilidad: r.get(5),
            factor_zona_roja: r.get(6),
            factor_zona_amarilla: r.get(7),
            factor_zona_verde: r.get(8),
            ciclo_pedido_dias: r.get(9),
            cantidad_minima: r.get(10),
            multiplo_empaque: r.get(11),
            inventario: r.get(12),
            en_transito: r.get(13),
            demanda_calificada: r.get(14),
        })
        .collect();
    if items.is_empty() {
        bail!("sin filas en maestro_item_bodega_config (activo)");
    }

    let res = calcular_lote(&items);

    // Escritura masiva via COPY (CSV)
    let mut w = client.copy_in(
        "COPY ddmrp.sugerencias_envio (ejecucion_id, fecha_calculo, producto_id, bodega_id, adu, tor, toy, tog, \
         inventario, en_transito, demanda_calificada, flujo_neto, pct_buffer, zona, cantidad_sugerida) \
         FROM STDIN WITH (FORMAT csv)",
    )?;
    for (r, it) in res.iter().zip(items.iter()) {
        writeln!(
            w,
            "{},{},\"{}\",\"{}\",{:.4},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:.2},{},{:.3}",
            ejecucion_id, fecha_sql, r.producto_id.replace('"', "\"\""), r.bodega_id.replace('"', "\"\""),
            r.adu, r.buffer.tor, r.buffer.toy, r.buffer.tog,
            it.inventario, it.en_transito, it.demanda_calificada,
            r.flujo_neto, r.pct_buffer, r.zona.as_db(), r.cantidad_sugerida
        )?;
    }
    w.finish()?;
    println!("{{\"ok\":true,\"filas\":{}}}", res.len());
    Ok(())
}
