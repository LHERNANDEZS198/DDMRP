import { ReactNode, useState } from 'react'
import { Alert, Box, Button, Card, CardContent, CardHeader, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Divider, Typography } from '@mui/material'
import Calculate from '@mui/icons-material/Calculate'
import PlayCircle from '@mui/icons-material/PlayCircle'
import { Link as RouterLink } from 'react-router-dom'
import { api, conProgreso, seguirTarea } from '../api'
import { useYo } from '../Yo'
import { useSalud } from '../Salud'
import { RepartoDias } from './Reglas'

const Lista = ({ children }: { children: ReactNode }) => <Box component="ul" sx={{ m: 0, pl: 3, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: .5, '& li': { fontSize: 14 } }}>{children}</Box>
const Seccion = ({ titulo, children }: { titulo: string; children: ReactNode }) => (
  <Card variant="outlined">
    <CardHeader title={titulo} slotProps={{ title: { variant: 'subtitle1', fontWeight: 700 } }} sx={{ bgcolor: '#eef2e3', py: 1 }} />
    <CardContent sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5 }}>{children}</CardContent>
  </Card>)
const fechaHora = (s?: string) => s ? new Date(s).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''

export default function Motor() {
  const { puede } = useYo(); const operar = puede('correr_motor'); const editar = puede('editar_reglas')
  const { salud, enCurso, refrescar } = useSalud()
  const [msg, setMsg] = useState('')
  // Antes de correr, si ya corrió hoy, avisa qué se pierde de vista y pide confirmar
  const [aviso, setAviso] = useState<{ que: 'motor' | 'pipeline'; d: any } | null>(null)
  const preguntar = async (que: 'motor' | 'pipeline') => {
    try { const d = await api('/admin/motor-hoy'); setAviso({ que, d }); return } catch { /* si falla la consulta, no bloquea */ }
    que === 'motor' ? recalcular() : pipeline()
  }
  const recalcular = async () => {
    setMsg('Recalculando con el motor Rust…'); setTimeout(refrescar, 800)
    try { const x = await conProgreso(setMsg, () => api('/admin/correr-motor', { method: 'POST' })); setMsg(`Listo: ${x.filas} combinaciones calculadas`) } catch (e: any) { setMsg('Error: ' + e.message) } finally { refrescar() }
  }
  const pipeline = async () => {
    setMsg('Lanzando ETL + motor…')
    try {
      const previo = (await api('/admin/progreso')).inicio ?? null
      await api('/admin/correr-pipeline', { method: 'POST' }); setTimeout(refrescar, 800)
      const fin = await seguirTarea(setMsg, previo)
      setMsg(fin.estado === 'error' ? fin.mensaje : `Listo: ${fin.mensaje}. Revisa Informes y la Matriz de despacho.`)
    } catch (e: any) { setMsg('Error: ' + e.message) } finally { refrescar() }
  }
  const ult = salud?.ultimo_motor_ok

  return (
    <Box sx={{ maxWidth: 980, mx: 'auto', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 2 }}>
      <Dialog open={!!aviso} onClose={() => setAviso(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{aviso?.d.corrio_hoy ? 'El motor ya corrió hoy' : (aviso?.que === 'pipeline' ? 'Correr ETL + motor' : 'Recalcular con el motor')}</DialogTitle>
        <DialogContent sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5 }}>
          <Alert severity="info" sx={{ '& .MuiAlert-message': { width: '100%' } }}>
            <RepartoDias editar={editar} compacto onCambio={m => { if (m.startsWith('Error')) setMsg(m) }}
              onElegidos={e => setAviso(p => p ? { ...p, d: { ...p.d, dias_reparto: e } } : p)} />
            <Typography variant="body2" sx={{ mt: 1 }}>
              {aviso?.d.dias_reparto?.length
                ? <>Solo compiten por la escasez las tiendas de los <b>DIAs {aviso.d.dias_reparto.join(' + ')}</b>; las demás quedan con lo que pide su buffer.</>
                : <>Si el CEDI no alcanza, se reparte entre <b>todas las tiendas</b>.</>}
              {!editar && ' (No tienes permiso para cambiarlo.)'}
            </Typography>
          </Alert>
          {aviso?.d.corrio_hoy && <Typography>
            Ya hay {aviso?.d.corridas} corrida(s) de hoy (la última a las {aviso?.d.ultima ? new Date(aviso.d.ultima).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' }) : ''}).
            Si corres de nuevo:
          </Typography>}
          <Box component="ul" sx={{ m: 0, pl: 3, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 0.5 }}>
            {aviso?.d.corrio_hoy && <li>La matriz de despacho y el plano pasan a usar <b>solo la corrida nueva</b>.</li>}
            {aviso?.d.corrio_hoy && <li>Lo <b>Enviado</b> se conserva; lo aprobado sin enviar y las cantidades editadas a mano vuelven a <b>Pendiente</b>.</li>}
            {aviso?.d.corrio_hoy && <li>Las cantidades pueden cambiar porque el CEDI se reparte con el stock fresco de PT001.</li>}
            {aviso?.que === 'pipeline' && <li>También se vuelve a leer todo Siesa (inventario, tránsitos, items): tarda varios minutos.</li>}
          </Box>
          {(aviso?.d.aprobadas > 0 || aviso?.d.enviadas > 0) && (
            <Alert severity="warning">
              En la corrida actual hay <b>{aviso?.d.aprobadas}</b> fila(s) aprobada(s) y <b>{aviso?.d.enviadas}</b> enviada(s). Si aún no generaste el plano, genéralo antes de recalcular.
              {aviso?.d.enviadas > 0 && <> Si vas a trabajar <b>otro DÍA</b> (ej. el DÍA 2 en la tarde), elige arriba solo ese DÍA: si no, las tiendas que ya enviaste vuelven a competir por el stock del CEDI y le quitan a las de ahora. Además, el plano que cargaste en Siesa debe estar ya registrado, o el motor sigue viendo ese stock como libre.</>}
            </Alert>)}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAviso(null)} autoFocus>Cancelar</Button>
          <Button color={aviso?.d.corrio_hoy ? 'warning' : 'primary'} variant="contained" onClick={() => { const q = aviso!.que; setAviso(null); q === 'motor' ? recalcular() : pipeline() }}>{aviso?.d.corrio_hoy ? 'Correr de todos modos' : 'Correr'}</Button>
        </DialogActions>
      </Dialog>

      <Box>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>Motor DDMRP</Typography>
        <Typography variant="body2" color="text.secondary">
          Aquí se corre el cálculo que alimenta todo lo demás: Informes, Matriz de despacho y planos de Siesa. {ult
            ? <>Última corrida buena: <b>{fechaHora(ult.fin)}</b>.</> : <>Todavía no hay ninguna corrida buena.</>} El sistema también corre solo, cada noche, el flujo completo.
        </Typography>
      </Box>
      {msg && <Alert severity={msg.startsWith('Error') ? 'error' : msg.startsWith('Listo') ? 'success' : 'info'}>{msg}</Alert>}

      {/* Las dos acciones */}
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 2 }}>
        <Card variant="outlined" sx={{ display: 'flex', flexDirection: 'column' }}>
          <CardContent sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.25, flex: 1, alignContent: 'start' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}><Calculate color="primary" /><Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Recalcular ahora (solo motor)</Typography></Box>
            <Typography variant="body2">Vuelve a calcular los buffers y las cantidades sugeridas <b>con los datos de Siesa que ya están guardados</b>. No consulta Siesa, salvo el inventario del CEDI, que sí se lee fresco.</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700 }}>Úsalo cuando cambiaste…</Typography>
            <Lista>
              <li>una <b>regla de pedido</b> (cuándo se pide, hasta dónde se repone, redondeo, qué suma el flujo neto);</li>
              <li>un <b>maestro</b>: lead time, frecuencia, cotas, unidad de despacho, vectorización, pronóstico, promociones, condenados, reserva del CEDI o items REC;</li>
              <li>los <b>DIAs</b> que compiten por el stock del CEDI.</li>
            </Lista>
            <Typography variant="caption" color="text.secondary">Tarda unos minutos con todas las tiendas.</Typography>
          </CardContent>
          <Box sx={{ p: 2, pt: 0 }}>
            <Button fullWidth variant="outlined" startIcon={<Calculate />} disabled={!operar || enCurso} onClick={() => preguntar('motor')}>Recalcular ahora</Button>
          </Box>
        </Card>
        <Card variant="outlined" sx={{ display: 'flex', flexDirection: 'column' }}>
          <CardContent sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.25, flex: 1, alignContent: 'start' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}><PlayCircle color="primary" /><Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Correr ETL + motor completo</Typography></Box>
            <Typography variant="body2">Primero <b>lee Siesa de nuevo</b> (ETL) y después calcula con el motor. Es lo mismo que corre solo cada noche.</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700 }}>Úsalo cuando…</Typography>
            <Lista>
              <li>cambió algo en <b>Siesa</b>: inventario, traslados en tránsito, costos, items nuevos, estado activo/inactivo o items REC;</li>
              <li>un aviso rojo dice que <b>una corrida no terminó bien</b>;</li>
              <li>necesitas datos del día antes de lo que reporta la corrida nocturna.</li>
            </Lista>
            <Typography variant="caption" color="text.secondary">Tarda más que el motor solo; si la regla «El ETL trae las ventas por mes» está en Sí, lee también el historial de ventas (varios minutos más).</Typography>
          </CardContent>
          <Box sx={{ p: 2, pt: 0 }}>
            <Button fullWidth variant="contained" startIcon={<PlayCircle />} disabled={!operar || enCurso} onClick={() => preguntar('pipeline')}>Correr ETL + motor</Button>
          </Box>
        </Card>
      </Box>
      {!operar && <Typography variant="caption" color="text.secondary">Tu perfil no tiene permiso para correr el motor; puedes leer cómo funciona abajo.</Typography>}
      {operar && enCurso && <Typography variant="caption" color="text.secondary">Hay una corrida en curso (mira el aviso azul arriba): solo se corre una cosa a la vez.</Typography>}

      <Divider textAlign="left"><Chip size="small" label="Cómo funciona" /></Divider>

      <Seccion titulo="El flujo completo, paso a paso">
        <Box component="ol" sx={{ m: 0, pl: 3, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1, '& li': { fontSize: 14 } }}>
          <li><b>ETL (Siesa → base de datos).</b> Trae las tiendas, el inventario de cada tienda (disponible = existencia − comprometido, según las reglas de «Datos de Siesa»), los costos promedio, los traslados en tránsito, los items con sus criterios, laboratorio y <b>estado</b>, y el inventario físico del CEDI. Con la regla «Solo items activos» en Sí, los items inactivos o bloqueados en Siesa no entran. Los items <b>REC</b> se suman a su original. Si la regla lo indica, también trae las <b>ventas por mes</b> (unidades y valor en pesos sin IVA).</li>
          <li><b>Motor (cálculo del buffer).</b> Para cada tienda × item calcula la venta diaria (ADU) y su variabilidad (IV), las zonas del buffer —<span style={{ color: '#c62828', fontWeight: 700 }}>roja</span>, <span style={{ color: '#b28704', fontWeight: 700 }}>amarilla</span> y <span style={{ color: '#2e7d32', fontWeight: 700 }}>verde</span>— con sus topes (TOR, TOY, TOG), y el <b>flujo neto</b> (inventario + tránsito − demanda calificada). Con eso y las reglas de pedido decide si pide, cuánto, y lo lleva a la unidad de despacho.</li>
          <li><b>Reparto del CEDI.</b> Si el stock del CEDI no alcanza para todo lo que piden las tiendas, lo reparte según la regla de reparto, respetando la reserva del CEDI y, si lo configuraste, solo entre las tiendas de los DIAs elegidos.</li>
          <li><b>Foto diaria.</b> Guarda una foto liviana del buffer del día. De ahí salen <b>Cambios en un periodo, Tendencia y Mapa de calor</b>. El historial se conserva el número de días de la regla «Días de historial que se conservan»; el detalle completo de cada corrida solo unos 7 días.</li>
          <li><b>Lanzamientos.</b> En cada lectura del inventario del CEDI se compara contra la anterior: un item que aparece con existencia por primera vez es un lanzamiento y uno que vuelve tras días sin stock es un reingreso.</li>
        </Box>
      </Seccion>

      <Seccion titulo="Qué pasa con tu trabajo cuando se vuelve a correr">
        <Lista>
          <li>Cada corrida crea un <b>cálculo nuevo</b>. La Matriz de despacho, los Informes y el plano de Siesa usan siempre <b>solo el último</b>.</li>
          <li>Por eso, si corres de nuevo el mismo día, lo que habías <b>aprobado o editado a mano</b> en la matriz <b>vuelve a Pendiente</b>, pero lo que ya <b>marcaste como enviado</b> se conserva. El sistema te avisa antes de correr y te dice cuántas filas aprobadas o enviadas hay. <b>Genera el plano antes de recalcular.</b></li>
          <li>Las cantidades pueden cambiar entre una corrida y otra porque el CEDI se reparte con el stock fresco.</li>
          <li>Solo corre una cosa a la vez (ETL, motor o carga de ventas). Si algo está corriendo, los botones se bloquean y arriba ves el avance; puedes cambiar de pantalla o cerrar la ventana, sigue en el servidor.</li>
          <li>Si una corrida se interrumpe (por ejemplo, se reinició el servidor), un aviso lo dice y los Informes siguen mostrando la última corrida buena. Se arregla corriendo de nuevo el ETL + motor.</li>
        </Lista>
      </Seccion>

      <Seccion titulo="Si trabajas por DÍAs el mismo día (ej. DÍA 1 en la mañana y DÍA 2 en la tarde)">
        <Lista>
          <li><b>1 · Termina el DÍA 1 completo:</b> aprueba, genera el plano (marcando enviadas) y cárgalo en Siesa. Hasta que el traslado exista en Siesa, el motor sigue viendo esa mercancía como libre en el CEDI y se la volvería a ofrecer al DÍA 2.</li>
          <li><b>2 · Antes del DÍA 2, recalcula:</b> «Recalcular ahora» basta, porque lee de nuevo el inventario del CEDI; y en la ventana que se abre deja elegido <b>solo el DÍA 2</b> en el reparto del CEDI. Así las tiendas del DÍA 1 no compiten por lo que quedó. Usa «ETL + motor» solo si además necesitas inventario o tránsitos frescos de las tiendas.</li>
          <li><b>3 · En la Matriz de despacho</b> elige la corrida del DÍA 2. Las tiendas del DÍA 1 que marcaste como enviadas siguen en Enviadas; si no las marcaste, aparecerán otra vez en Pendientes: <b>no las vuelvas a aprobar</b>, ya salieron.</li>
          <li><b>Sin recalcular:</b> si en la corrida de la mañana el reparto del CEDI ya incluía los DÍAs 1 + 2, el DÍA 2 ya tiene su parte calculada y puedes seguir con esa misma corrida sin perder nada de lo aprobado. Recalcula solo si entró mercancía al CEDI o el DÍA 1 salió muy distinto de lo asignado.</li>
        </Lista>
      </Seccion>

      <Seccion titulo="¿Cuál botón uso?">
        <Box component="table" sx={{ borderCollapse: 'collapse', width: '100%', '& td, & th': { border: '1px solid #e0e0e0', px: 1.25, py: .75, fontSize: 13, textAlign: 'left', verticalAlign: 'top' } }}>
          <thead><tr><th>Lo que cambió</th><th>Qué correr</th></tr></thead>
          <tbody>
            <tr><td>Una regla de pedido o un maestro (lead time, cotas, unidad de despacho, pronóstico, promociones…)</td><td><b>Recalcular ahora</b></td></tr>
            <tr><td>Los DIAs que compiten por el stock del CEDI</td><td><b>Recalcular ahora</b></td></tr>
            <tr><td>Inventario, tránsitos, costos o items en Siesa</td><td><b>ETL + motor</b></td></tr>
            <tr><td>Se activó o desactivó «Solo items activos» o «REC se suman a su original»</td><td><b>ETL + motor</b> (la primera vez; el estado y los pares REC se leen de Siesa)</td></tr>
            <tr><td>Se cambió «El ETL trae las ventas por mes» o hay ventas nuevas que ver</td><td><b>ETL + motor</b> (o «Traer ventas por mes» en Maestros, y luego recalcular)</td></tr>
            <tr><td>Un aviso dice que la última corrida falló o se interrumpió</td><td><b>ETL + motor</b></td></tr>
          </tbody>
        </Box>
      </Seccion>

      <Seccion titulo="Dónde se configura lo que usa el motor">
        <Lista>
          <li><b>Reglas de pedido</b>: cuándo se pide, hasta dónde se repone, redondeo, qué suma el flujo neto, reparto del CEDI, items activos y REC, parámetros del modelo.</li>
          <li><b>Maestros</b>: lead time, cotas, unidad de despacho, vectorización, pronóstico, promociones, condenados, reserva del CEDI, items REC y ventas por mes.</li>
          <li><b>Corrida automática</b>: cada noche el sistema corre ETL + motor solo (la hora la fija la configuración del servidor).</li>
        </Lista>
        <Box><Button size="small" variant="outlined" component={RouterLink} to="/reglas">Ir a Reglas de pedido</Button></Box>
      </Seccion>
    </Box>)
}
