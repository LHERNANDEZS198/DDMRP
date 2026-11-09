import { ReactNode, useEffect, useState } from 'react'
import { Alert, Box, Button, Chip, CircularProgress, Paper, Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography } from '@mui/material'
import Refresh from '@mui/icons-material/Refresh'
import { api } from '../api'
import { useEmpresa } from '../Empresa'

// el tablero tarda en cargar: los detalles se abren en otra pestaña para no perder el tablero ni recargarlo al volver
const abrir = (ruta: string) => window.open(ruta, '_blank', 'noopener')
// fecha y hora de Colombia (UTC-5, sin horario de verano) de un instante ISO: «lun 9 nov, 2:05 p. m.»
const fechaCol = (iso: string) => new Date(new Date(iso).getTime() - 5 * 36e5).toLocaleString('es-CO', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'UTC' })
const ent = (v: any) => v == null ? '' : Math.round(Number(v)).toLocaleString('es-CO')
const MM = (v: any) => { const n = Number(v || 0); return '$' + (Math.abs(n) >= 1e6 ? (n / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M' : Math.round(n).toLocaleString('es-CO')) }
const d1 = (v: any) => v == null ? '' : Number(v).toLocaleString('es-CO', { maximumFractionDigits: 1 })
const SEM: Record<string, string> = { ok: '#2e7d32', aviso: '#b45309', mal: '#c62828', info: '#546e7a' }

function Kpi({ titulo, valor, sub, color = 'info', ayuda, to }: { titulo: string; valor: ReactNode; sub?: ReactNode; color?: string; ayuda?: string; to?: string }) {
  return (
    <Tooltip title={(ayuda ? ayuda + '. ' : '') + (to ? 'Clic para ver el detalle completo (se abre en otra pestaña)' : '')} placement="top" arrow>
      <Paper variant="outlined" onClick={to ? () => abrir(to) : undefined} sx={{ p: 1.5, minWidth: 170, flex: '1 1 170px', borderLeft: `4px solid ${SEM[color]}`, cursor: to ? 'pointer' : 'default', '&:hover': to ? { bgcolor: 'action.hover' } : undefined }}>
        <Typography variant="caption" color="text.secondary">{titulo}</Typography>
        <Typography variant="h5" sx={{ fontWeight: 700, color: SEM[color] }}>{valor}</Typography>
        {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
      </Paper>
    </Tooltip>)
}

function Bloque({ n, titulo, ayuda, children }: { n: number; titulo: string; ayuda: string; children: ReactNode }) {
  return (
    <Box sx={{ mt: 3 }}>
      <Typography variant="h6" sx={{ fontWeight: 700 }}>{n}. {titulo}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{ayuda}</Typography>
      {children}
    </Box>)
}

function Lista({ cols, filas, vacio, onFila }: { cols: { t: string; f: (r: any) => ReactNode; right?: boolean }[]; filas: any[]; vacio: string; onFila?: (r: any) => void }) {
  if (!filas?.length) return <Alert severity="success" icon={false} sx={{ py: 0 }}>{vacio}</Alert>
  return (
    <Paper variant="outlined" sx={{ overflowX: 'auto', maxHeight: 340 }}>
      <Table size="small" stickyHeader>
        <TableHead><TableRow>{cols.map(c => <TableCell key={c.t} align={c.right ? 'right' : 'left'} sx={{ fontWeight: 700 }}>{c.t}</TableCell>)}</TableRow></TableHead>
        <TableBody>
          {filas.map((r, i) => (
            <TableRow key={i} hover sx={onFila ? { cursor: 'pointer' } : undefined} onClick={onFila ? () => onFila(r) : undefined}>
              {cols.map(c => <TableCell key={c.t} align={c.right ? 'right' : 'left'}>{c.f(r)}</TableCell>)}
            </TableRow>))}
        </TableBody>
      </Table>
    </Paper>)
}

export default function Tablero() {
  const [d, setD] = useState<any>(null)
  const [err, setErr] = useState('')
  const [cargando, setCargando] = useState(false)
  const { lista: empresa } = useEmpresa()      // selector de empresa de la barra
  const cargar = (fresco = false) => {
    setCargando(true); setErr('')
    api(`/compras/tablero?${new URLSearchParams({ ...(fresco ? { fresco: '1' } : {}), ...(empresa.length ? { empresa: empresa.join(',') } : {}) })}`).then(setD).catch(e => setErr(String(e?.message || e))).finally(() => setCargando(false))
  }
  useEffect(() => cargar(), [empresa.join(',')])

  if (!d) return (
    <Box sx={{ display: 'grid', placeItems: 'center', height: '60vh' }}>
      {err ? <Alert severity="error" action={<Button color="inherit" size="small" onClick={() => cargar()}>Reintentar</Button>}>{err}</Alert>
        : <Box sx={{ display: 'grid', justifyItems: 'center', gap: 1.5, textAlign: 'center' }}>
            <CircularProgress />
            <Typography variant="h6" sx={{ fontWeight: 700 }}>Cargando Control de Compras</Typography>
            <Typography variant="body2" color="text.secondary">Calculando necesidades, OC y tránsitos; puede tardar unos segundos…</Typography>
          </Box>}
    </Box>)
  const p = d.pedir, v = d.vuelo, nr = d.no_recibido, rs = d.riesgo, ex = d.exceso, cu = d.cumplimiento
  const roja = p.zonas.find((z: any) => z.zona === 'ROJA')
  const nEst = (e: string) => v.estados.find((x: any) => x.estado === e)?.ocs || 0
  const pctDesv = cu.lineas.lineas ? (100 * cu.lineas.desv_cant / cu.lineas.lineas) : 0
  const irNecesidades = () => abrir('/compras/necesidades')

  return (
    <Box sx={{ pb: 4 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>Tablero de compras</Typography>
        <Typography variant="body2" color="text.secondary">
          <Tooltip title={p.ejecucion ? `Sale del buffer de la corrida #${p.ejecucion.id} del motor` : ''} arrow>
            <span>{d.calculado ? `Necesidades calculadas el ${fechaCol(d.calculado)}` : 'Sin cálculo'}{p.ejecucion ? '' : ' · sin corrida del motor'}</span>
          </Tooltip>
        </Typography>
        <Button size="small" startIcon={cargando ? <CircularProgress size={14} /> : <Refresh />} onClick={() => cargar(true)} disabled={cargando}>Actualizar</Button>
      </Box>
      {cargando && <Alert severity="info" icon={<CircularProgress size={16} />} sx={{ my: 1, py: 0 }}>Cargando Control de Compras…</Alert>}
      {err && <Alert severity="error" sx={{ my: 1 }}>{err}</Alert>}
      {p.aviso && <Alert severity="warning" sx={{ my: 1 }}>{p.aviso}</Alert>}

      <Bloque n={1} titulo="Qué pedir hoy" ayuda="Items con algo que pedir, agrupados por proveedor.">
        <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 1.5 }}>
          <Kpi titulo="Ítems por pedir" valor={ent(p.totales.items)} sub={`${ent(p.totales.proveedores)} proveedores`} />
          <Kpi titulo="Valor a pedir" valor={MM(p.totales.total)} sub="con IVA" />
          <Kpi titulo="En zona roja" valor={ent(roja?.items || 0)} sub={MM(roja?.valor || 0)} color={roja?.items ? 'mal' : 'ok'} ayuda="Ítems por pedir que están en zona roja del buffer del CEDI" />
          <Kpi titulo="Proveedores con problema" valor={ent(p.con_problema)} sub="mínimo, cotización, cond. pago" color={p.con_problema ? 'aviso' : 'ok'} />
          <Kpi titulo="Ítems sin cotización" valor={ent(p.totales.sin_costo)} color={p.totales.sin_costo ? 'aviso' : 'ok'} />
          <Kpi titulo="Sin proveedor" valor={ent(p.sin_proveedor)} color={p.sin_proveedor ? 'aviso' : 'ok'} ayuda="Ítems con necesidad pero sin proveedor asignado en Maestros de compras" />
          <Kpi titulo="Consignación" valor={ent(p.consignacion.items)} sub={MM(p.consignacion.valor)} color="info" ayuda="Ítems en consignación (van en OC aparte)" />
        </Box>
        <Lista onFila={irNecesidades} vacio="Nada por pedir con los filtros de tu perfil."
          cols={[{ t: 'Proveedor', f: r => `${r.proveedor_nombre} (${r.empresa})` }, { t: 'Ítems', f: r => ent(r.items), right: true }, { t: 'Unidades', f: r => ent(r.unidades), right: true },
                 { t: 'Total', f: r => MM(r.total), right: true },
                 { t: 'Estado', f: r => <Chip size="small" label={r.estado} color={r.estado === 'OK' ? 'success' : 'warning'} variant="outlined" /> }]}
          filas={p.proveedores} />
      </Bloque>

      <Bloque n={2} titulo="Resumen OC" ayuda="Dónde están las OC montadas en los últimos 90 días.">
        <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 1.5 }}>
          <Kpi to="/compras/tablero/oc_vuelo" titulo="En el BPM" valor={ent(nEst('en_bpm') + nEst('en_revision'))} sub={MM(v.estados.filter((x: any) => ['en_bpm', 'en_revision'].includes(x.estado)).reduce((a: number, x: any) => a + x.total, 0))} />
          <Kpi to="/compras/tablero/oc_vuelo" titulo="Con error / inciertas" valor={ent(nEst('error') + nEst('incierta'))} color={nEst('error') + nEst('incierta') ? 'mal' : 'ok'} />
          <Kpi to="/compras/tablero/oc_vuelo" titulo="Creadas en Siesa" valor={ent(nEst('creada'))} sub={MM(v.estados.find((x: any) => x.estado === 'creada')?.total || 0)} color="ok" />
          <Kpi to="/compras/tablero/trabadas" titulo="Bloqueadas" valor={ent(v.n_trabadas)} sub={`más de ${d.config.tablero_dias_trabada} días sin cerrar`} color={v.n_trabadas ? 'aviso' : 'ok'} />
        </Box>
        <Lista vacio="No hay OC bloqueadas."
          cols={[{ t: 'Referencia', f: r => r.referencia }, { t: 'Proveedor', f: r => r.proveedor_nombre }, { t: 'Estado', f: r => <Chip size="small" label={r.estado} color={r.estado === 'error' ? 'error' : 'warning'} variant="outlined" /> },
                 { t: 'Días', f: r => d1(r.dias), right: true }, { t: 'Total', f: r => MM(r.total), right: true }, { t: 'Consig.', f: r => r.consignacion ? 'SÍ' : '' }, { t: 'Mensaje', f: r => r.mensaje }]}
          filas={v.trabadas} />
      </Bloque>

      <Bloque n={3} titulo="Pedido y no recibido" ayuda="OC creadas en Siesa que ya pasaron el lead time del proveedor sin cumplirse, y requisiciones RIT comprometidas que llevan mucho tiempo abiertas.">
        <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 1.5 }}>
          <Kpi to="/compras/tablero/oc_abiertas" titulo="OC abiertas en Siesa" valor={ent(nr.oc_en_transito.documentos)} sub={`${ent(nr.oc_en_transito.unidades)} unidades en tránsito al CEDI`} />
          <Kpi to="/compras/tablero/oc_vencidas" titulo="OC vencidas" valor={ent(nr.n_vencidas)} sub="pasaron el lead time" color={nr.n_vencidas ? 'mal' : 'ok'} />
          <Kpi to="/compras/tablero/rit_viejas" titulo="RIT viejas" valor={ent(nr.rit_total)} sub="comprometidas con alerta" color={nr.rit_total ? 'aviso' : 'ok'} />
        </Box>
        <Lista vacio="No hay OC vencidas."
          cols={[{ t: 'OC', f: r => r.siesa_consecutivo || r.referencia }, { t: 'Proveedor', f: r => r.proveedor_nombre }, { t: 'Días', f: r => ent(r.dias), right: true }, { t: 'Lead time', f: r => ent(r.leadtime), right: true },
                 { t: 'Estado Siesa', f: r => r.estado_siesa || '' }, { t: 'Total', f: r => MM(r.total), right: true }, { t: 'Consig.', f: r => r.consignacion ? 'SÍ' : '' }]}
          filas={nr.vencidas} />
        {nr.rit.length > 0 && <Box sx={{ mt: 1.5 }}><Lista vacio=""
          cols={[{ t: 'RIT', f: r => r.documento }, { t: 'Ítem', f: r => `${r.producto_id} ${r.descripcion || ''}` }, { t: 'Bodega', f: r => r.bodega_id }, { t: 'Saldo', f: r => ent(r.saldo), right: true }, { t: 'Días', f: r => ent(r.dias), right: true }]}
          filas={nr.rit} /></Box>}
      </Bloque>

      <Bloque n={4} titulo="Riesgo de desabastecimiento" ayuda="Ítems en zona roja sin nada en tránsito, de mayor a menor rotación (ADU): lo que más duele si falta va primero. Aquí van los primeros; el detalle trae todos.">
        <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 1.5 }}>
          <Kpi to="/compras/tablero/riesgo" titulo="Roja sin tránsito" valor={ent(rs.total)} color={rs.total ? 'mal' : 'ok'} />
          <Kpi to="/compras/tablero/agotados" titulo="Agotados con venta" valor={ent(rs.agotados)} sub="inventario 0 y rotación > 0" color={rs.agotados ? 'mal' : 'ok'} />
        </Box>
        <Lista vacio="Nada en riesgo."
          cols={[{ t: 'Ítem', f: r => `${r.producto_id} ${r.descripcion || ''}` }, { t: 'Inventario', f: r => ent(r.inventario), right: true }, { t: 'Cobertura (días)', f: r => d1(r.cobertura_dias), right: true },
                 { t: 'Lead time', f: r => ent(r.lead_time), right: true }, { t: 'Rotación mensual', f: r => ent(r.adu), right: true }, { t: 'Consig.', f: r => r.consignacion ? 'SÍ' : '' }]}
          filas={rs.filas} />
      </Bloque>

      <Bloque n={5} titulo="Exceso de inventario" ayuda="Lo que sobra sobre el tope verde del CEDI, valorado al costo de compra.">
        <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 1.5 }}>
          <Kpi to="/compras/tablero/exceso" titulo="Ítems en exceso" valor={ent(ex.total.items)} color="info" />
          <Kpi to="/compras/tablero/exceso" titulo="Valor que sobra" valor={MM(ex.total.valor)} color={ex.total.valor ? 'aviso' : 'ok'} />
        </Box>
        <Lista vacio="Sin exceso."
          cols={[{ t: 'Ítem', f: r => `${r.producto_id} ${r.descripcion || ''}` }, { t: 'Inventario', f: r => ent(r.inventario), right: true }, { t: 'Sobran', f: r => ent(r.sobran), right: true },
                 { t: 'Valor', f: r => MM(r.valor), right: true }, { t: 'Cobertura (días)', f: r => d1(r.cobertura_dias), right: true }]}
          filas={ex.filas} />
      </Bloque>

      <Bloque n={6} titulo={`Cumplimiento del proceso (últimos ${cu.dias} días)`} ayuda="Cuánto se aparta compras de lo que sugiere el motor y cuánto tarda una OC en llegar a Siesa.">
        <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 1.5 }}>
          <Kpi titulo="OC creadas" valor={ent(cu.oc.ocs)} sub={MM(cu.oc.total)} color="info" />
          <Kpi titulo="Pasaron por revisión" valor={ent(cu.oc.con_revision)} sub={cu.oc.ocs ? `${d1(100 * cu.oc.con_revision / cu.oc.ocs)} %` : ''} />
          <Kpi titulo="Líneas con desvío de cantidad" valor={`${d1(pctDesv)} %`} sub={`${ent(cu.lineas.desv_cant)} de ${ent(cu.lineas.lineas)} líneas`} color={pctDesv > 20 ? 'aviso' : 'ok'} />
          <Kpi titulo="Líneas con costo subido" valor={ent(cu.lineas.desv_costo)} color={cu.lineas.desv_costo ? 'aviso' : 'ok'} />
          <Kpi titulo="Envío → Siesa (horas)" valor={d1(cu.oc.horas_envio_a_siesa)} sub="promedio, incluye la aprobación" />
          <Kpi titulo="En consignación" valor={ent(cu.oc.consignacion)} />
        </Box>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
          <Box sx={{ flex: '1 1 320px' }}><Lista vacio="Sin OC en el período."
            cols={[{ t: 'Proveedor', f: r => r.proveedor_nombre }, { t: 'OC', f: r => ent(r.ocs), right: true }, { t: 'Total', f: r => MM(r.total), right: true }]} filas={cu.por_proveedor} /></Box>
          <Box sx={{ flex: '1 1 320px' }}><Lista vacio="Sin OC en el período."
            cols={[{ t: 'Laboratorio', f: r => r.laboratorio }, { t: 'Valor comprado', f: r => MM(r.valor), right: true }]} filas={cu.por_laboratorio} /></Box>
        </Box>
      </Bloque>
      {/* {d.tiempos_ms && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 3 }}>
          Tiempo de carga por bloque (ms): {Object.entries(d.tiempos_ms).map(([k, v]) => `${k.replace(/_/g, ' ')} ${Number(v).toLocaleString('es-CO')}`).join(' · ')} {d.cache_seg > 0 ? ` (Qué pedir hoy estaba guardado de hace ${d.cache_seg >= 3600 ? Math.round(d.cache_seg / 3600) + ' h' : Math.max(1, Math.round(d.cache_seg / 60)) + ' min'}; Actualizar lo recalcula)` : ''} · total {Object.values(d.tiempos_ms).reduce((a: number, b: any) => a + Number(b), 0).toLocaleString('es-CO')}
        </Typography>)}
        */}
    </Box>)
}
