import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Snackbar, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material'
import NotificationsIcon from '@mui/icons-material/Notifications'
import { api } from './api'
import { useYo } from './Yo'
import { NOMBRE_EMPRESA } from './Empresa'

/** Campana del menú: solicitudes por aprobar (si apruebas) y respuestas nuevas a lo que pediste (si solicitas). Clic = abre la vista de solicitudes. */
export function CampanaSolicitudes() {
  const { puede } = useYo(); const ir = useNavigate()
  const activo = puede('solicitar_cambios', 'aprobar_cambios', 'aprobar_compras')
  const [c, setC] = useState<{ pendientes: number; resueltas_sin_ver: number; total: number } | null>(null)
  useEffect(() => {
    if (!activo) return
    let vivo = true
    const cargar = () => api('/solicitudes/contadores').then((r: any) => { if (vivo) setC(r) }).catch(() => { /* sin red: se reintenta */ })
    cargar(); const t = setInterval(cargar, 60000); window.addEventListener('solicitudes-cambio', cargar)
    return () => { vivo = false; clearInterval(t); window.removeEventListener('solicitudes-cambio', cargar) }
  }, [activo])
  if (!activo) return null
  const tip = c ? `${c.pendientes} por aprobar · ${c.resueltas_sin_ver} respuestas nuevas a tus solicitudes` : 'Solicitudes'
  return (
    <Tooltip disableInteractive title={tip}>
      <IconButton size="small" sx={{ color: '#fff', mr: .5 }} onClick={() => ir('/solicitudes')}>
        <Badge color="error" badgeContent={c?.total ?? 0} max={99}><NotificationsIcon /></Badge>
      </IconButton>
    </Tooltip>)
}

type Objetivo = { empresa: string; laboratorio?: string; producto_id?: string; bodega_id?: string; texto: string; nombre?: string; nombre2?: string }

/** Botón «Solicitar cambio» de los informes: pide agregar o quitar NxP / compras de lo que está marcado en la tabla (o del laboratorio filtrado). */
export function BotonSolicitar({ filas, empresas, labsFiltro = [], labNombres = {}, nivelInicial, exigirTienda = false, tiendasFiltradas = 0, hayFiltroTienda = false }: { filas: any[]; empresas: string[]; labsFiltro?: string[]; labNombres?: Record<string, string>; nivelInicial?: 'laboratorio' | 'item' | 'tienda_item'; exigirTienda?: boolean; tiendasFiltradas?: number; hayFiltroTienda?: boolean }) {
  const { puede } = useYo()
  const [abierto, setAbierto] = useState(false)
  const [tipo, setTipo] = useState<'nxp' | 'compras'>('nxp')
  const [accion, setAccion] = useState<'agregar' | 'quitar'>('agregar')
  const [nivel, setNivel] = useState<'laboratorio' | 'item' | 'tienda_item'>('item')
  const [motivo, setMotivo] = useState(''); const [enviando, setEnviando] = useState(false)
  const [paso, setPaso] = useState<'armar' | 'confirmar'>('armar')
  const [msg, setMsg] = useState(''); const [err, setErr] = useState('')
  const emp = (r: any) => String(r.empresa ?? '') || empresas.join(',')
  const objetivos = useMemo<Objetivo[]>(() => {
    const m = new Map<string, Objetivo>()
    if (nivel === 'laboratorio') {
      filas.forEach(r => { const l = r.laboratorio; if (l && l !== '(sin laboratorio)') m.set(emp(r) + '|' + l, { empresa: emp(r), laboratorio: l, texto: `Lab. ${l}`, nombre: labNombres[l] }) })
      if (!m.size) labsFiltro.forEach(l => l !== '(sin laboratorio)' && m.set(l, { empresa: empresas.join(','), laboratorio: l, texto: `Lab. ${l}`, nombre: labNombres[l] }))
    } else if (nivel === 'item') {
      filas.forEach(r => { if (r.producto_id) m.set(emp(r) + '|' + r.producto_id, { empresa: emp(r), producto_id: r.producto_id, texto: String(r.producto_id), nombre: r.descripcion, nombre2: r.laboratorio ? `Lab. ${r.laboratorio}${labNombres[r.laboratorio] ? ' · ' + labNombres[r.laboratorio] : ''}` : undefined }) })
    } else {
      filas.forEach(r => { if (r.producto_id && r.bodega_id) m.set(emp(r) + '|' + r.bodega_id + '|' + r.producto_id, { empresa: emp(r), producto_id: r.producto_id, bodega_id: r.bodega_id, texto: `${r.bodega_id} · ${r.producto_id}`, nombre: r.descripcion, nombre2: r.bodega_nombre ? `${r.bodega_id} · ${r.bodega_nombre}` : String(r.bodega_id) }) })
    }
    return [...m.values()]
  }, [filas, nivel, labsFiltro.join(), empresas.join(), JSON.stringify(labNombres).length])   // eslint-disable-line react-hooks/exhaustive-deps
  if (!puede('solicitar_cambios')) return null
  const enviar = async () => {
    setEnviando(true); setErr('')
    try {
      const r: any = await api('/solicitudes', { method: 'POST', body: JSON.stringify({
        motivo, items: objetivos.map(o => ({ tipo, accion, nivel, laboratorio: o.laboratorio, producto_id: o.producto_id, bodega_id: o.bodega_id, empresa: o.empresa })) }) })
      setMsg(`Solicitud enviada: ${r.creadas} nuevas${r.ya_pendientes ? `, ${r.ya_pendientes} ya estaban pendientes` : ''}${r.ya_en_nxp ? `, ${r.ya_en_nxp} omitidas porque ya están en NxP (para esas solicita quitar)` : ''}`)
      window.dispatchEvent(new Event('solicitudes-cambio')); setAbierto(false); setPaso('armar'); setMotivo('')
    } catch (e: any) { setErr(e.message || 'No se pudo enviar') } finally { setEnviando(false) }
  }
  const tiendaEnMotivo = nivel !== 'tienda_item' && tipo === 'nxp' ? (motivo.toUpperCase().match(/\b[A-Z]{2,3}\d{3}\b/) ?? [])[0] : undefined
  // Desde la vista Tienda × Item, agregar a NxP solo se permite por tienda-item y con una o más tiendas filtradas: evita pedir por error un NxP general (todas las tiendas)
  // Con tiendas filtradas en la pantalla, un NxP por Item o Laboratorio igual aplica a TODAS las tiendas: se obliga a pedirlo por tienda-item
  const bloqueo = hayFiltroTienda && tipo === 'nxp' && accion === 'agregar' && nivel !== 'tienda_item'
    ? 'Tienes tiendas filtradas, pero a nivel Item o Laboratorio el NxP aplica a TODAS las tiendas. Para pedirlo solo en las tiendas filtradas cambia a «Por tienda × item» en el selector del filtro "Clasificar".'
    : exigirTienda && tipo === 'nxp' && accion === 'agregar'
    ? (tiendasFiltradas === 0 ? 'Para agregar a NxP desde esta vista filtra primero una o más tiendas (filtro «Tienda»), así queda claro dónde aplica.'
      : nivel !== 'tienda_item' ? 'Desde esta vista, agregar a NxP se pide por «Tienda-item». Para pedirlo en todas las tiendas usa los niveles Item o Laboratorio de Foto actual.' : '')
    : ''
  const nombreAccion = `${accion === 'agregar' ? 'Agregar a' : 'Quitar de'} ${tipo === 'nxp' ? 'NxP' : 'compras'}`
  return (<>
    <Tooltip title={filas.length ? 'Pide agregar o quitar NxP / compras de lo marcado en la tabla (casilla de la izquierda), por laboratorio, item o tienda-item. Otro grupo la aprueba.'
      : 'Marca una o más filas en la tabla (casilla de la izquierda) para solicitar un cambio.'}>
      <span>
        <Button size="small" variant="outlined" disabled={!filas.length} onClick={() => { setNivel(nivelInicial ?? (filas.some(r => r.bodega_id) ? 'tienda_item' : 'item')); setPaso('armar'); setAbierto(true) }}>
          Solicitar cambio{filas.length ? ` (${filas.length})` : ''}</Button>
      </span>
    </Tooltip>
    <Dialog open={abierto} onClose={() => setAbierto(false)} maxWidth="md" fullWidth>
      <DialogTitle>{paso === 'armar' ? 'Solicitar cambio' : 'Confirma lo que vas a enviar a aprobación'}</DialogTitle>
      {paso === 'confirmar' ? <>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Typography variant="body2"><b>Qué:</b> {nombreAccion} · por {nivel === 'laboratorio' ? 'laboratorio' : nivel === 'item' ? 'item' : 'tienda-item'}</Typography>
          <Typography variant="body2"><b>Cuántos:</b> {objetivos.length.toLocaleString('es-CO')} · empresa(s): {[...new Set(objetivos.flatMap(o => o.empresa.split(',')))].map(e => NOMBRE_EMPRESA[e] ?? e).join(', ')}</Typography>
          <Typography variant="body2"><b>Lo aprueba:</b> {tipo === 'nxp' ? 'el grupo que aprueba NxP' : 'el grupo de compras'} (al aprobarse se aplica solo)</Typography>
          <Typography variant="body2"><b>Motivo:</b> {motivo.trim() || '—'}</Typography>
          {nivel === 'item' && tipo === 'nxp' && <Typography variant="body2" color="warning.main"><b>Ojo:</b> a nivel Item aplica a TODAS las tiendas{tiendaEnMotivo ? ` (en el motivo mencionas ${tiendaEnMotivo}: si es solo esa tienda, vuelve y elige «Tienda-item»)` : ''}.</Typography>}
          <Box sx={{ maxHeight: '50vh', overflow: 'auto', border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
            <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, '& td, & th': { px: 1, py: .5, textAlign: 'left', borderBottom: '1px solid', borderColor: 'divider' }, '& th': { position: 'sticky', top: 0, bgcolor: 'background.paper', fontWeight: 700 } }}>
              <thead><tr>
                <th>{nivel === 'laboratorio' ? 'Código' : nivel === 'item' ? 'Item' : 'Tienda · Item'}</th>
                <th>{nivel === 'laboratorio' ? 'Laboratorio' : 'Descripción'}</th>
                {nivel !== 'laboratorio' && <th>{nivel === 'item' ? 'Laboratorio' : 'Nombre tienda'}</th>}
                {empresas.length > 1 && <th>Empresa</th>}
              </tr></thead>
              <tbody>{objetivos.slice(0, 500).map(o => <tr key={o.texto + o.empresa}>
                <td style={{ whiteSpace: 'nowrap' }}>{nivel === 'laboratorio' ? o.laboratorio : o.texto}</td>
                <td>{o.nombre ?? '—'}</td>
                {nivel !== 'laboratorio' && <td>{o.nombre2 ?? '—'}</td>}
                {empresas.length > 1 && <td>{o.empresa.split(',').map(e => NOMBRE_EMPRESA[e] ?? e).join(', ')}</td>}
              </tr>)}</tbody>
            </Box>
          </Box>
          {objetivos.length > 500 && <Typography variant="caption" color="text.secondary">Se muestran los primeros 500 de {objetivos.length.toLocaleString('es-CO')}; se envían todos.</Typography>}
          {err && <Typography color="error" variant="body2">{err}</Typography>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPaso('armar')} disabled={enviando}>Volver</Button>
          <Button variant="contained" disabled={enviando} onClick={enviar}>{enviando ? 'Enviando…' : 'Confirmar y enviar'}</Button>
        </DialogActions>
      </> : <>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '8px !important' }}>
        <ToggleButtonGroup size="small" exclusive value={tipo} onChange={(_, v) => { if (v) { setTipo(v); if (v === 'compras' && nivel === 'tienda_item') setNivel('item') } }}>
          <ToggleButton value="nxp">NxP</ToggleButton><ToggleButton value="compras">Compras</ToggleButton>
        </ToggleButtonGroup>
        <ToggleButtonGroup size="small" exclusive value={accion} onChange={(_, v) => v && setAccion(v)}>
          <ToggleButton value="agregar">Agregar</ToggleButton><ToggleButton value="quitar">Quitar</ToggleButton>
        </ToggleButtonGroup>
        <ToggleButtonGroup size="small" exclusive value={nivel} onChange={(_, v) => v && setNivel(v)}>
          <ToggleButton value="laboratorio">Laboratorio</ToggleButton><ToggleButton value="item">Item</ToggleButton>
          <ToggleButton value="tienda_item" disabled={tipo === 'compras'}>Tienda-item</ToggleButton>
        </ToggleButtonGroup>
        <Typography variant="body2" color="text.secondary">
          {tipo === 'nxp' ? 'NxP = el item (o laboratorio) no se despacha. ' : 'Compras = el item (o los items del laboratorio) sale o vuelve a entrar a las necesidades de compra. '}
          Por tienda-item solo aplica para NxP.
        </Typography>
        <Box>
          <Typography variant="subtitle2" sx={{ mb: .5 }}>{nombreAccion} · {objetivos.length} {nivel === 'laboratorio' ? 'laboratorio(s)' : nivel === 'item' ? 'item(s)' : 'tienda-item'}</Typography>
          {objetivos.length ? <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: .5, maxHeight: 130, overflow: 'auto' }}>
            {objetivos.slice(0, 40).map(o => <Chip key={o.texto + o.empresa} size="small" label={o.nombre ? `${o.texto} · ${o.nombre}` : o.texto} />)}
            {objetivos.length > 40 && <Chip size="small" variant="outlined" label={`+${objetivos.length - 40} más`} />}
          </Box> : <Typography variant="body2" color="error">No hay nada marcado para este nivel: marca filas en la tabla (casilla de la izquierda){nivel === 'tienda_item' ? ' que tengan tienda e item' : ''}.</Typography>}
        </Box>
        {tiendaEnMotivo && <Typography variant="body2" color="warning.main">Mencionas la tienda {tiendaEnMotivo} en el motivo, pero el nivel «{nivel === 'item' ? 'Item' : 'Laboratorio'}» aplica a TODAS las tiendas. Si es solo esa tienda usa «Tienda-item» (marca filas que tengan tienda).</Typography>}
        <TextField size="small" label="Motivo (opcional)" value={motivo} onChange={e => setMotivo(e.target.value)} multiline minRows={2} />
        {bloqueo && <Typography color="error" variant="body2"><b>No se puede enviar:</b> {bloqueo}</Typography>}
        {err && <Typography color="error" variant="body2">{err}</Typography>}
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setAbierto(false)}>Cancelar</Button>
        <Button variant="contained" disabled={!objetivos.length || enviando || !!bloqueo} onClick={() => setPaso('confirmar')}>Revisar y enviar</Button>
      </DialogActions></>}
    </Dialog>
    <Snackbar open={!!msg} autoHideDuration={5000} onClose={() => setMsg('')} message={msg} />
  </>)
}
