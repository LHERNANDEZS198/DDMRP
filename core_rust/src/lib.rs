//! Motor DDMRP – modelo de la hoja "Modelo" (Descripcion y Formulas DDMRP.xlsx, fila 6).
//!
//! Resumen del modelo (columnas del Excel entre parentesis):
//!  1. Bloque pronostico (BI..CB): con las ventas de 7 meses se calcula un ADU de referencia (BK).
//!     El "Pronostico" (valor estatico que cargan los analistas) se compara contra ese ADU
//!     y se ajusta a 30-60 dias de inventario (CA, CB) -> Forecast (Q).
//!  2. Bloque principal (R..AM): ADU (W) = promedio de los ultimos 4 meses + Q, mas su variabilidad.
//!     Zonas: ZA, ZRB, ZRS, ZV; topes TOR, TOY, TOG; ajuste por cotas/promocion -> TOY y TOG ajustados.
//!  3. Flujo neto = inventario + transito - demanda calificada; zona y cantidad sugerida
//!     (esta ultima parte NO esta en el Excel: es una propuesta, ver `decidir`).
use rayon::prelude::*;
use serde::Serialize;

// ---------- utilidades con semantica de Excel ----------

const EPS: f64 = 1e-9;

/// REDONDEAR.MAS / ROUNDUP (sobre positivos). EPS evita que 3.0000000000000004 suba a 4.
pub fn roundup(x: f64) -> f64 {
    (x - EPS).ceil() + 0.0
}

/// REDONDEAR / ROUND (mitades se alejan de cero, igual que Excel).
pub fn round_xl(x: f64) -> f64 {
    if x >= 0.0 { (x + EPS).round() } else { (x - EPS).round() }
}

pub fn promedio(xs: &[f64]) -> f64 {
    if xs.is_empty() { 0.0 } else { xs.iter().sum::<f64>() / xs.len() as f64 }
}

/// DESVEST.M (desviacion estandar muestral). Con menos de 2 datos Excel da error -> aqui 0.
pub fn desvest_m(xs: &[f64]) -> f64 {
    let n = xs.len();
    if n < 2 { return 0.0; }
    let m = promedio(xs);
    (xs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (n as f64 - 1.0)).sqrt()
}

fn div(a: f64, b: f64) -> f64 {
    if b == 0.0 { 0.0 } else { a / b } // SI.ERROR(a/b; 0)
}

// ---------- parametros y factores (tablas editables) ----------

#[derive(Debug, Clone)]
pub struct Tramo {
    pub factor: f64,
    pub desde: f64,
    pub hasta: Option<f64>,
}

#[derive(Debug, Clone)]
pub struct Factores {
    pub lt: Vec<Tramo>,
    pub var: Vec<Tramo>,
}

/// Replica los SI(Y(x>=desde; x<=hasta)...) del Excel: el primer tramo incluye `desde`,
/// los demas son (desde, hasta]; el ultimo puede ser abierto. Fuera de tramos -> 0.
pub fn factor(tramos: &[Tramo], x: f64) -> f64 {
    let mut ord: Vec<&Tramo> = tramos.iter().collect();
    ord.sort_by(|a, b| a.desde.partial_cmp(&b.desde).unwrap());
    for (i, t) in ord.iter().enumerate() {
        let sobre = if i == 0 { x >= t.desde } else { x > t.desde };
        if sobre && t.hasta.map_or(true, |h| x <= h) {
            return t.factor;
        }
    }
    0.0
}

#[derive(Debug, Clone)]
pub struct Parametros {
    pub mult_cota_max_promo: f64, // AZ = cota max x 1.2
    pub mult_cota_min_promo: f64, // BA = cota min x 1.1
    pub adu_bajo_min: f64,        // ADU entre min y max => ZRB = 0
    pub adu_bajo_max: f64,
    // --- reglas de pedido (editables en la pantalla "Reglas") ---
    pub regla_disparo: u8,        // 1 = NFP <= TOY aj, 2 = NFP <= TOR, 3 = NFP < TOG aj
    pub regla_objetivo: u8,       // 1 = TOG aj, 2 = TOY aj
    pub regla_redondeo: u8,       // 1 = arriba, 2 = cercano, 3 = abajo (al multiplo de despacho)
    pub sumar_vectorizacion: bool,
    pub incluir_transito: bool,
    pub restar_demanda_calificada: bool,
    pub cantidad_minima: f64,
    // --- ventana de historia ---
    pub meses_historia: usize, // meses de venta para BK/variabilidad (Excel: 7, incluye el mes en curso)
    pub meses_adu: usize,      // ultimos meses (+ forecast) que entran al ADU (Excel: 4)
}

impl Default for Parametros {
    fn default() -> Self {
        Parametros {
            mult_cota_max_promo: 1.2, mult_cota_min_promo: 1.1, adu_bajo_min: 1.0, adu_bajo_max: 4.0,
            regla_disparo: 1, regla_objetivo: 1, regla_redondeo: 1,
            sumar_vectorizacion: true, incluir_transito: true, restar_demanda_calificada: true, cantidad_minima: 0.0,
            meses_historia: 7, meses_adu: 4,
        }
    }
}

// ---------- entrada / salida ----------

#[derive(Debug, Clone)]
pub struct Entrada {
    pub empresa: String,
    pub bodega_id: String,
    pub producto_id: String,
    /// Ventas mensuales de los ultimos 7 meses: [mes-6, ..., mes-1, mes actual] (columnas J..P).
    pub ventas: Vec<f64>, // oldest -> mes en curso; el motor usa los ultimos `meses_historia`
    pub pronostico: f64,
    pub lead_time: f64,       // AA (dias)
    pub frecuencia: f64,      // AC
    pub unidad_despacho: f64, // AD
    pub cota_max: f64,        // AX
    pub cota_min: f64,        // AY
    pub promo: i16,           // indicativo de promocion (AN): 0, 1, 2
    pub vectorizacion: f64,   // derrame
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
pub struct Zonas {
    pub zrb: f64,
    pub zrs: f64,
    pub za: f64,
    pub zv: f64,
    pub tor: f64,
    pub toy: f64,
    pub tog: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct Resultado {
    pub empresa: String,
    pub bodega_id: String,
    pub producto_id: String,
    pub adu: f64,      // W
    pub iv: f64,       // Y
    pub forecast: f64, // Q
    pub lead_time: f64,
    pub frecuencia: f64,
    pub unidad_despacho: f64,
    pub zonas: Zonas,
    pub toy_aj: f64, // AL
    pub tog_aj: f64, // AM
    pub inventario: f64,
    pub en_transito: f64,
    pub demanda_calificada: f64,
    pub flujo_neto: f64,
    pub pct_buffer: f64,
    pub zona: Zona,
    pub vectorizacion: f64,
    pub cantidad_sugerida: f64,
}

// ---------- calculo ----------

/// ZA, ZRB, ZRS, ZV y topes para un ADU (unidades/mes) y su indice de variabilidad.
pub fn zonas(adu: f64, iv: f64, lt: f64, frec: f64, ud: f64, f: &Factores, p: &Parametros) -> Zonas {
    let za = roundup(lt * (adu / 30.0)); // AG
    let zrb = if adu >= p.adu_bajo_min && adu <= p.adu_bajo_max {
        0.0
    } else {
        round_xl(za * factor(&f.lt, lt)) // AE
    };
    let zrs = round_xl(zrb * factor(&f.var, iv)); // AF
    let tor = zrb + zrs; // AI
    let toy = tor + za; // AJ
    let zv = if adu == 0.0 || toy == 0.0 {
        0.0
    } else {
        roundup(frec * (adu / 30.0)).max(ud).max(zrb) // AH
    };
    Zonas { zrb, zrs, za, zv, tor, toy, tog: toy + zv }
}

/// Forecast ajustado (Q = CB) a partir del pronostico estatico y el ADU de referencia (BK).
pub fn forecast_ajustado(pronostico: f64, bk: f64) -> f64 {
    let ca = div(pronostico, bk) * 30.0; // dias de inventario del pronostico
    if ca == 0.0 {
        return 0.0; // IFERROR: division por cero
    }
    if ca < 30.0 {
        pronostico / ca * 30.0
    } else if ca > 60.0 {
        pronostico / ca * 60.0
    } else {
        pronostico
    }
}

/// ADU de referencia del bloque de pronostico (BK) con las ventas de la ventana.
pub fn adu_referencia(ventas: &[f64]) -> f64 {
    let bi = promedio(ventas);
    let bm = div(desvest_m(ventas), bi);
    roundup(bi + bi * bm)
}

pub fn calcular(e: &Entrada, f: &Factores, p: &Parametros) -> Resultado {
    // Bloque pronostico -> Q
    let n = p.meses_historia.clamp(2, e.ventas.len().max(2)).min(e.ventas.len());
    let hist = &e.ventas[e.ventas.len() - n..];
    let bk = adu_referencia(hist);
    let q = forecast_ajustado(e.pronostico, bk);

    // Bloque principal: ultimos `meses_adu` meses (Excel: 4, M..P) + forecast
    let k = p.meses_adu.clamp(1, n);
    let mut v: Vec<f64> = hist[n - k..].to_vec();
    v.push(q);
    let u = promedio(&v);
    let y = div(desvest_m(&v), u);
    let w = roundup(u + u * y); // ADU (W)

    let z = zonas(w, y, e.lead_time, e.frecuencia, e.unidad_despacho, f, p);

    // Promocion: no aplica a bodegas TC / DM
    let pref = e.bodega_id.get(..2).unwrap_or("");
    let promo = if e.promo != 0 && (pref == "TC" || pref == "DM") { 0 } else { e.promo };
    let adu_bajo = w >= p.adu_bajo_min && w <= p.adu_bajo_max;

    let az = e.cota_max * p.mult_cota_max_promo;
    let ba = e.cota_min * p.mult_cota_min_promo;
    let toy_aj = if adu_bajo && promo == 0 {
        z.toy
    } else if promo == 1 {
        roundup(z.tog * az + z.tor + z.za)
    } else {
        roundup(z.tog * e.cota_max + z.tor + z.za)
    };
    let usa_ba = promo == 1 || (promo == 2 && pref == "GN");
    let tog_aj = if adu_bajo && promo == 0 {
        z.tog
    } else if usa_ba {
        roundup(toy_aj + z.zv + z.tog * ba)
    } else {
        roundup(toy_aj + z.zv + z.tog * e.cota_min)
    };

    decidir(e, &z, w, y, q, toy_aj, tog_aj, p)
}

/// Redondea `x` al multiplo de `ud` segun la regla (1 arriba, 2 cercano, 3 abajo).
pub fn a_multiplo(x: f64, ud: f64, regla: u8) -> f64 {
    let ud = if ud > 1.0 { ud } else { 1.0 };
    let k = x / ud;
    let k = match regla { 2 => round_xl(k), 3 => (k + 1e-9).floor(), _ => roundup(k) };
    k * ud
}

/// Flujo neto, zona y cantidad sugerida. PROPUESTA (el Excel termina en los topes ajustados), parametrizada:
///  - flujo neto = inventario + transito - demanda calificada (cada termino activable)
///  - zona segun TOR / TOY ajustado / TOG ajustado
///  - se pide segun `regla_disparo`; se repone hasta `regla_objetivo`, al multiplo de despacho (`regla_redondeo`)
///  - se suma la vectorizacion (derrame) si `sumar_vectorizacion`
fn decidir(e: &Entrada, z: &Zonas, w: f64, y: f64, q: f64, toy_aj: f64, tog_aj: f64, p: &Parametros) -> Resultado {
    let transito = if p.incluir_transito { e.en_transito } else { 0.0 };
    let dem = if p.restar_demanda_calificada { e.demanda_calificada } else { 0.0 };
    let nfp = e.inventario + transito - dem;
    let zona = if tog_aj <= 0.0 {
        if nfp > 0.0 { Zona::Exceso } else { Zona::Verde } // sin buffer definido: sin alerta
    } else if nfp <= z.tor {
        Zona::Roja
    } else if nfp <= toy_aj {
        Zona::Amarilla
    } else if nfp <= tog_aj {
        Zona::Verde
    } else {
        Zona::Exceso
    };
    let pide = tog_aj > 0.0
        && match p.regla_disparo {
            2 => nfp <= z.tor,
            3 => nfp < tog_aj,
            _ => nfp <= toy_aj,
        };
    let base = if pide {
        let objetivo = if p.regla_objetivo == 2 { toy_aj } else { tog_aj };
        let falta = objetivo - nfp;
        if falta > 0.0 { a_multiplo(falta, e.unidad_despacho, p.regla_redondeo) } else { 0.0 }
    } else {
        0.0
    };
    let base = if base > 0.0 && base < p.cantidad_minima { 0.0 } else { base };
    let vect = if p.sumar_vectorizacion { e.vectorizacion } else { 0.0 };
    Resultado {
        empresa: e.empresa.clone(),
        bodega_id: e.bodega_id.clone(),
        producto_id: e.producto_id.clone(),
        adu: w,
        iv: y,
        forecast: q,
        lead_time: e.lead_time,
        frecuencia: e.frecuencia,
        unidad_despacho: e.unidad_despacho,
        zonas: *z,
        toy_aj,
        tog_aj,
        inventario: e.inventario,
        en_transito: e.en_transito,
        demanda_calificada: e.demanda_calificada,
        flujo_neto: nfp,
        pct_buffer: if tog_aj > 0.0 { nfp / tog_aj * 100.0 } else { 0.0 },
        zona,
        vectorizacion: e.vectorizacion,
        cantidad_sugerida: base + vect,
    }
}

/// Procesa todo el lote en paralelo (rayon). Sin estado compartido mutable -> sin locks.
pub fn calcular_lote(items: &[Entrada], f: &Factores, p: &Parametros) -> Vec<Resultado> {
    items.par_iter().map(|e| calcular(e, f, p)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn factores() -> Factores {
        Factores {
            lt: vec![
                Tramo { factor: 0.61, desde: 0.0, hasta: Some(3.0) },
                Tramo { factor: 0.41, desde: 3.0, hasta: Some(5.0) },
                Tramo { factor: 0.21, desde: 5.0, hasta: Some(50.0) },
            ],
            var: vec![
                Tramo { factor: 0.21, desde: 0.0, hasta: Some(0.5) },
                Tramo { factor: 0.41, desde: 0.5, hasta: Some(0.8) },
                Tramo { factor: 0.61, desde: 0.8, hasta: None },
            ],
        }
    }

    fn base() -> Entrada {
        Entrada {
            empresa: "05".into(),
            bodega_id: "GN442".into(),
            producto_id: "019901".into(),
            ventas: vec![10.0; 7],
            pronostico: 0.0,
            lead_time: 3.0,
            frecuencia: 2.0,
            unidad_despacho: 1.0,
            cota_max: 0.0,
            cota_min: 0.0,
            promo: 0,
            vectorizacion: 0.0,
            inventario: 0.0,
            en_transito: 0.0,
            demanda_calificada: 0.0,
        }
    }

    #[test]
    fn factores_por_tramo() {
        let f = factores();
        assert_eq!(factor(&f.lt, 0.0), 0.61); // el primer tramo incluye el limite inferior
        assert_eq!(factor(&f.lt, 3.0), 0.61); // limite superior incluido
        assert_eq!(factor(&f.lt, 3.01), 0.41);
        assert_eq!(factor(&f.lt, 5.0), 0.41);
        assert_eq!(factor(&f.lt, 50.0), 0.21);
        assert_eq!(factor(&f.lt, 51.0), 0.0); // fuera de rango (FALSO en Excel)
        assert_eq!(factor(&f.var, 0.5), 0.21);
        assert_eq!(factor(&f.var, 0.51), 0.41);
        assert_eq!(factor(&f.var, 5.0), 0.61);
    }

    #[test]
    fn roundup_ignora_ruido_flotante() {
        assert_eq!(roundup(3.0000000000000004), 3.0);
        assert_eq!(roundup(1.3), 2.0);
        assert_eq!(roundup(0.0), 0.0);
        assert_eq!(round_xl(2.5), 3.0);
    }

    #[test]
    fn forecast_ajusta_a_30_60_dias() {
        // pronostico 0 -> 0
        assert_eq!(forecast_ajustado(0.0, 10.0), 0.0);
        // CA = 3/10*30 = 9 (<30) -> se lleva al ADU de referencia (10)
        assert!((forecast_ajustado(3.0, 10.0) - 10.0).abs() < 1e-9);
        // CA = 40/10*30 = 120 (>60) -> pronostico/CA*60 = 20
        assert!((forecast_ajustado(40.0, 10.0) - 20.0).abs() < 1e-9);
        // CA = 15/10*30 = 45 (entre 30 y 60) -> queda el pronostico
        assert_eq!(forecast_ajustado(15.0, 10.0), 15.0);
        // sin historial no hay ADU de referencia -> 0
        assert_eq!(forecast_ajustado(15.0, 0.0), 0.0);
    }

    #[test]
    fn ejemplo_a_mano() {
        // Ventas 10/mes, LT 3, frecuencia 2, sin cotas. Calculo a mano:
        // valores [10,10,10,10,0] -> U=8, DesvEst=4.4721, Y=0.559, W=ceil(12.47)=13
        // ZA=ceil(3*13/30)=2 ; ZRB=round(2*0.61)=1 ; ZRS=round(1*0.41)=0 ; ZV=max(ceil(2*13/30)=1,1,1)=1
        let f = factores();
        let r = calcular(&base(), &f, &Parametros::default());
        assert_eq!(r.adu, 13.0);
        assert_eq!(r.zonas.za, 2.0);
        assert_eq!(r.zonas.zrb, 1.0);
        assert_eq!(r.zonas.zrs, 0.0);
        assert_eq!(r.zonas.zv, 1.0);
        assert_eq!((r.zonas.tor, r.zonas.toy, r.zonas.tog), (1.0, 3.0, 4.0));
        assert_eq!((r.toy_aj, r.tog_aj), (3.0 + 0.0, 4.0)); // sin cotas: ajustados = topes
        assert_eq!(r.zona, Zona::Roja);
        assert_eq!(r.cantidad_sugerida, 4.0);
    }

    #[test]
    fn cotas_ajustan_topes() {
        // AL = ceil(TOG*cotaMax + TOR + ZA) = ceil(4*0.35+1+2)=5 ; AM = ceil(AL+ZV+TOG*cotaMin)=ceil(5+1+0.6)=7
        let mut e = base();
        e.cota_max = 0.35;
        e.cota_min = 0.15;
        let r = calcular(&e, &factores(), &Parametros::default());
        assert_eq!((r.toy_aj, r.tog_aj), (5.0, 7.0));
    }

    #[test]
    fn promocion_usa_cotas_aumentadas_salvo_tc_dm() {
        let mut e = base();
        e.cota_max = 0.35;
        e.cota_min = 0.15;
        e.promo = 1;
        let r = calcular(&e, &factores(), &Parametros::default());
        // AL = ceil(4*0.42+1+2)=ceil(4.68)=5 ; AM = ceil(5+1+4*0.165)=ceil(6.66)=7
        assert_eq!((r.toy_aj, r.tog_aj), (5.0, 7.0));
        let mut e2 = e.clone();
        e2.bodega_id = "TC001".into(); // en TC/DM la promocion no aplica
        let r2 = calcular(&e2, &factores(), &Parametros::default());
        assert_eq!((r2.toy_aj, r2.tog_aj), (5.0, 7.0)); // igual a la ruta sin promo con cotas normales
    }

    #[test]
    fn adu_bajo_sin_promo_no_usa_cotas() {
        // ventas muy bajas: ADU entre 1 y 4 -> ZRB=0 y los topes ajustados son los topes
        let mut e = base();
        e.ventas = vec![1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0];
        e.cota_max = 0.5;
        e.cota_min = 0.5;
        let r = calcular(&e, &factores(), &Parametros::default());
        assert!(r.adu >= 1.0 && r.adu <= 4.0);
        assert_eq!(r.zonas.zrb, 0.0);
        assert_eq!(r.toy_aj, r.zonas.toy);
        assert_eq!(r.tog_aj, r.zonas.tog);
    }

    #[test]
    fn multiplo_de_despacho_y_vectorizacion() {
        let mut e = base();
        e.unidad_despacho = 12.0;
        e.vectorizacion = 6.0;
        let r = calcular(&e, &factores(), &Parametros::default());
        // ZV = max(1, 12, 1) = 12 -> TOG = 3+12 = 15 ; falta 15 -> 24 (2 cajas) + 6 de derrame
        assert_eq!(r.zonas.zv, 12.0);
        assert_eq!(r.cantidad_sugerida, 24.0 + 6.0);
    }

    #[test]
    fn exceso_no_sugiere_y_sin_buffer_no_alerta() {
        let mut e = base();
        e.inventario = 500.0;
        let r = calcular(&e, &factores(), &Parametros::default());
        assert_eq!(r.zona, Zona::Exceso);
        assert_eq!(r.cantidad_sugerida, 0.0);

        let mut vacio = base();
        vacio.ventas = vec![0.0; 7];
        let r = calcular(&vacio, &factores(), &Parametros::default());
        assert_eq!(r.zonas.tog, 0.0);
        assert_eq!(r.zona, Zona::Verde); // sin buffer y sin stock: no es alerta
        assert_eq!(r.cantidad_sugerida, 0.0);
    }

    #[test]
    fn reglas_configurables() {
        let f = factores();
        // base(): TOR 1, TOY 3, TOG 4. Inventario 3 => amarilla (NFP <= TOY)
        let mut e = base(); e.inventario = 3.0;
        let p = Parametros::default();
        assert_eq!(calcular(&e, &f, &p).cantidad_sugerida, 1.0); // TOG 4 - 3
        let mut p2 = Parametros::default(); p2.regla_disparo = 2; // solo si roja
        assert_eq!(calcular(&e, &f, &p2).cantidad_sugerida, 0.0);
        let mut p3 = Parametros::default(); p3.regla_objetivo = 2; // hasta TOY: falta 0
        assert_eq!(calcular(&e, &f, &p3).cantidad_sugerida, 0.0);
        // transito: con inventario 0 y transito 4 => NFP 4 (verde), sin contar transito => pide 4
        let mut e2 = base(); e2.inventario = 0.0; e2.en_transito = 4.0;
        assert_eq!(calcular(&e2, &f, &p).cantidad_sugerida, 0.0);
        let mut p4 = Parametros::default(); p4.incluir_transito = false;
        assert_eq!(calcular(&e2, &f, &p4).cantidad_sugerida, 4.0);
        // vectorizacion y minimo
        let mut e3 = base(); e3.vectorizacion = 5.0;
        let mut p5 = Parametros::default(); p5.sumar_vectorizacion = false;
        assert_eq!(calcular(&e3, &f, &p5).cantidad_sugerida, 4.0);
        let mut p6 = Parametros::default(); p6.cantidad_minima = 10.0;
        assert_eq!(calcular(&base(), &f, &p6).cantidad_sugerida, 0.0);
        // redondeo a multiplo de 10: falta 4 => arriba 10, cercano 0, abajo 0
        assert_eq!(a_multiplo(4.0, 10.0, 1), 10.0);
        assert_eq!(a_multiplo(4.0, 10.0, 2), 0.0);
        assert_eq!(a_multiplo(6.0, 10.0, 2), 10.0);
        assert_eq!(a_multiplo(14.0, 10.0, 3), 10.0);
    }

    #[test]
    fn ventana_configurable() {
        let f = factores();
        let mut e = base();
        // 12 meses: los 5 mas viejos en 100, los 7 ultimos en 10
        e.ventas = [vec![100.0; 5], vec![10.0; 7]].concat();
        // por defecto solo cuenta la ventana de 7 meses (igual al caso base)
        assert_eq!(calcular(&e, &f, &Parametros::default()).adu, 13.0);
        // ventana de 12 meses: el ADU de referencia (BK) sube
        assert!(adu_referencia(&e.ventas) > adu_referencia(&e.ventas[5..]));
        // ADU con 1 mes + forecast en vez de 4: cambia el resultado
        e.ventas[11] = 40.0;
        let a4 = calcular(&e, &f, &Parametros::default()).adu;
        let mut p = Parametros::default(); p.meses_adu = 1;
        assert_ne!(calcular(&e, &f, &p).adu, a4);
        // parametros absurdos se acotan (no revientan)
        let mut p = Parametros::default(); p.meses_historia = 99; p.meses_adu = 0;
        let _ = calcular(&e, &f, &p);
    }

    #[test]
    fn lote_paralelo() {
        let items = vec![base(); 50_000];
        assert_eq!(calcular_lote(&items, &factores(), &Parametros::default()).len(), 50_000);
    }
}
