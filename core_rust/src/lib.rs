//! Motor DDMRP: calculo de buffers y flujo neto por item/bodega.
//! Las formulas son un punto de partida estandar; se ajustan con las del Excel de maestros.
use rayon::prelude::*;
use serde::Serialize;

/// Entrada ya agregada por (producto, bodega).
#[derive(Debug, Clone)]
pub struct ItemBodega {
    pub producto_id: String,
    pub bodega_id: String,
    /// ADU = unidades vendidas en la ventana / dias de la ventana
    pub adu: f64,
    pub lead_time_dias: f64,
    pub factor_lead_time: f64,
    pub factor_variabilidad: f64,
    pub factor_zona_roja: f64,
    pub factor_zona_amarilla: f64,
    pub factor_zona_verde: f64,
    pub ciclo_pedido_dias: f64,
    pub cantidad_minima: f64,
    pub multiplo_empaque: f64,
    pub inventario: f64,
    pub en_transito: f64,
    pub demanda_calificada: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Zona {
    Roja,
    Amarilla,
    Verde,
    Exceso,
}

impl Zona {
    pub fn as_db(&self) -> &'static str {
        match self {
            Zona::Roja => "ROJA",
            Zona::Amarilla => "AMARILLA",
            Zona::Verde => "VERDE",
            Zona::Exceso => "EXCESO",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize)]
pub struct Buffer {
    pub roja: f64,
    pub amarilla: f64,
    pub verde: f64,
    pub tor: f64,
    pub toy: f64,
    pub tog: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct Resultado {
    pub producto_id: String,
    pub bodega_id: String,
    pub adu: f64,
    pub buffer: Buffer,
    pub flujo_neto: f64,
    pub pct_buffer: f64,
    pub zona: Zona,
    pub cantidad_sugerida: f64,
}

pub fn calcular_buffer(i: &ItemBodega) -> Buffer {
    let dlt = i.lead_time_dias; // lead time desacoplado
    // Zona roja = base + seguridad
    let roja_base = i.adu * dlt * i.factor_lead_time;
    let roja_seg = roja_base * i.factor_variabilidad;
    let roja = (roja_base + roja_seg) * i.factor_zona_roja;
    // Zona amarilla = demanda durante el lead time
    let amarilla = i.adu * dlt * i.factor_zona_amarilla;
    // Zona verde = max(ADU*DLT*factor LT, ciclo de pedido*ADU, MOQ)
    let verde = (i.adu * dlt * i.factor_lead_time)
        .max(i.adu * i.ciclo_pedido_dias)
        .max(i.cantidad_minima)
        * i.factor_zona_verde;
    Buffer {
        roja,
        amarilla,
        verde,
        tor: roja,
        toy: roja + amarilla,
        tog: roja + amarilla + verde,
    }
}

fn redondear_a_multiplo(q: f64, multiplo: f64, minimo: f64) -> f64 {
    if q <= 0.0 {
        return 0.0;
    }
    let q = q.max(minimo);
    if multiplo > 1.0 {
        (q / multiplo).ceil() * multiplo
    } else {
        q.ceil()
    }
}

pub fn calcular(i: &ItemBodega) -> Resultado {
    let b = calcular_buffer(i);
    // Flujo neto = disponible + transito - demanda calificada
    let nfp = i.inventario + i.en_transito - i.demanda_calificada;
    let zona = if nfp <= b.tor {
        Zona::Roja
    } else if nfp <= b.toy {
        Zona::Amarilla
    } else if nfp <= b.tog {
        Zona::Verde
    } else {
        Zona::Exceso
    };
    let pct = if b.tog > 0.0 { nfp / b.tog * 100.0 } else { 0.0 };
    // Se pide cuando el flujo neto cae a la zona amarilla o por debajo: llevar hasta TOG
    let sugerido = if nfp <= b.toy {
        redondear_a_multiplo(b.tog - nfp, i.multiplo_empaque, i.cantidad_minima)
    } else {
        0.0
    };
    Resultado {
        producto_id: i.producto_id.clone(),
        bodega_id: i.bodega_id.clone(),
        adu: i.adu,
        buffer: b,
        flujo_neto: nfp,
        pct_buffer: pct,
        zona,
        cantidad_sugerida: sugerido,
    }
}

/// Procesa el lote completo en paralelo (rayon). Sin estado compartido mutable -> sin locks.
pub fn calcular_lote(items: &[ItemBodega]) -> Vec<Resultado> {
    items.par_iter().map(calcular).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base() -> ItemBodega {
        ItemBodega {
            producto_id: "P1".into(),
            bodega_id: "B1".into(),
            adu: 10.0,
            lead_time_dias: 5.0,
            factor_lead_time: 0.5,
            factor_variabilidad: 0.5,
            factor_zona_roja: 1.0,
            factor_zona_amarilla: 1.0,
            factor_zona_verde: 1.0,
            ciclo_pedido_dias: 1.0,
            cantidad_minima: 0.0,
            multiplo_empaque: 1.0,
            inventario: 0.0,
            en_transito: 0.0,
            demanda_calificada: 0.0,
        }
    }

    #[test]
    fn buffer_basico() {
        let b = calcular_buffer(&base());
        assert!((b.tor - 37.5).abs() < 1e-9); // 25 + 12.5
        assert!((b.toy - 87.5).abs() < 1e-9); // + 50
        assert!((b.tog - 112.5).abs() < 1e-9); // + 25
    }

    #[test]
    fn sin_stock_es_roja_y_sugiere() {
        let r = calcular(&base());
        assert_eq!(r.zona, Zona::Roja);
        assert_eq!(r.cantidad_sugerida, 113.0);
    }

    #[test]
    fn exceso_no_sugiere() {
        let mut i = base();
        i.inventario = 500.0;
        let r = calcular(&i);
        assert_eq!(r.zona, Zona::Exceso);
        assert_eq!(r.cantidad_sugerida, 0.0);
    }

    #[test]
    fn lote_paralelo() {
        let items = vec![base(); 1000];
        assert_eq!(calcular_lote(&items).len(), 1000);
    }
}
