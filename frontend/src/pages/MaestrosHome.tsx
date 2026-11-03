import { ReactElement, useEffect, useMemo, useState } from 'react'
import { Alert, Avatar, Box, Card, CardActionArea, InputAdornment, TextField, Typography } from '@mui/material'
import Search from '@mui/icons-material/Search'
import Storefront from '@mui/icons-material/Storefront'
import Store from '@mui/icons-material/Store'
import Warehouse from '@mui/icons-material/Warehouse'
import Event from '@mui/icons-material/Event'
import TrendingUp from '@mui/icons-material/TrendingUp'
import BarChart from '@mui/icons-material/BarChart'
import LocalOffer from '@mui/icons-material/LocalOffer'
import Assignment from '@mui/icons-material/Assignment'
import CallSplit from '@mui/icons-material/CallSplit'
import Height from '@mui/icons-material/Height'
import Tune from '@mui/icons-material/Tune'
import Functions from '@mui/icons-material/Functions'
import Science from '@mui/icons-material/Science'
import Inventory2 from '@mui/icons-material/Inventory2'
import Lock from '@mui/icons-material/Lock'
import Category from '@mui/icons-material/Category'
import Link from '@mui/icons-material/Link'
import FilterAlt from '@mui/icons-material/FilterAlt'
import Block from '@mui/icons-material/Block'
import ViewInAr from '@mui/icons-material/ViewInAr'
import TableChart from '@mui/icons-material/TableChart'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useYo } from '../Yo'

type Def = { clave: string; label: string; ayuda: string; grupo?: string }
type Tarjeta = { clave: string; titulo: string; desc: string; icono: ReactElement; seccion: string; ruta: string; color: string }

const SECCIONES = ['Tiendas y CEDI', 'Demanda y pronóstico', 'Buffer y reglas de reposición', 'Ítems y exclusiones', 'Otros']
const COL: Record<string, string> = { 'Tiendas y CEDI': '#1565c0', 'Demanda y pronóstico': '#2e7d32', 'Buffer y reglas de reposición': '#6a1b9a', 'Ítems y exclusiones': '#ef6c00', 'Otros': '#546e7a' }
const META: Record<string, [string, ReactElement]> = {   // clave -> [sección, logo]
  'bitacora': ['Tiendas y CEDI', <Store />], 'cedis': ['Tiendas y CEDI', <Warehouse />], 'dias-bodega': ['Tiendas y CEDI', <Event />],
  'pronostico': ['Demanda y pronóstico', <TrendingUp />], 'ventas-mensual': ['Demanda y pronóstico', <BarChart />], 'promocion': ['Demanda y pronóstico', <LocalOffer />],
  'demanda-calificada': ['Demanda y pronóstico', <Assignment />], 'vectorizacion': ['Demanda y pronóstico', <CallSplit />],
  'control-referencias': ['Buffer y reglas de reposición', <Height />], 'factores': ['Buffer y reglas de reposición', <Tune />], 'parametros': ['Buffer y reglas de reposición', <Functions />],
  'reposicion-laboratorio': ['Buffer y reglas de reposición', <Science />], 'reposicion-item': ['Buffer y reglas de reposición', <Inventory2 />],
  'reserva-cedi': ['Buffer y reglas de reposición', <Lock />], 'unidad-despacho': ['Buffer y reglas de reposición', <ViewInAr />],
  'items': ['Ítems y exclusiones', <Category />], 'items-rec': ['Ítems y exclusiones', <Link />], 'criterios-filtros': ['Ítems y exclusiones', <FilterAlt />],
  'condenados': ['Ítems y exclusiones', <Block />], 'laboratorio-sin-envio': ['Ítems y exclusiones', <Block />],
}
const sinTilde = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
const corto = (s: string, n: number) => { const t = s.replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n - 1).trimEnd() + '…' : t }

function aTarjeta(d: Def): Tarjeta {
  const m = META[d.clave]; const i = d.label.search(/:| \(/)
  const titulo = i > 0 ? d.label.slice(0, i) : d.label
  const resto = i > 0 ? d.label.slice(i).replace(/^:\s*/, '').replace(/^\(|\)$/g, '') : ''
  const sec = m?.[0] ?? 'Otros'
  return { clave: d.clave, titulo, desc: corto(resto || d.ayuda || '', 110), icono: m?.[1] ?? <TableChart />, seccion: sec, ruta: `/config?maestro=${d.clave}`, color: COL[sec] }
}

export default function MaestrosHome() {
  const nav = useNavigate(); const { puede } = useYo()
  const [defs, setDefs] = useState<Def[] | null>(null); const [err, setErr] = useState('')
  const [q, setQ] = useState('')
  useEffect(() => { api('/maestros').then((x: Def[]) => setDefs(x.filter(d => (d.grupo ?? 'ddmrp') === 'ddmrp'))).catch(e => setErr(e.message)) }, [])

  const tarjetas = useMemo<Tarjeta[]>(() => {
    const lista = (defs ?? []).map(aTarjeta)
    // pantallas propias que también son un «maestro» (no son una tabla de Excel)
    if (puede('ver_maestros', 'cargar_maestros'))
      lista.unshift({ clave: 'apertura-tienda', titulo: 'Apertura de tienda', desc: 'Abre una tienda nueva copiando a una espejo: pronóstico, cotas, NxP y cuántos meses dura el espejo.',
        icono: <Storefront />, seccion: 'Tiendas y CEDI', ruta: '/apertura-tienda', color: COL['Tiendas y CEDI'] })
    return lista
  }, [defs, puede])

  const t = sinTilde(q.trim())
  const visibles = tarjetas.filter(x => !t || sinTilde(`${x.titulo} ${x.desc} ${x.clave} ${x.seccion}`).includes(t) || (defs ?? []).some(d => d.clave === x.clave && sinTilde(d.ayuda).includes(t)))

  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 2, maxWidth: 1200, mx: 'auto', width: '100%' }}>
      <Box><Typography variant="h6" sx={{ fontWeight: 700 }}>Maestros</Typography>
        <Typography variant="body2" color="text.secondary">Elige el maestro que quieres ver o cargar.</Typography></Box>
      <TextField autoFocus size="small" placeholder="Buscar maestro… (ej. tiendas, pronóstico, cotas)" value={q} onChange={e => setQ(e.target.value)}
        slotProps={{ input: { startAdornment: <InputAdornment position="start"><Search /></InputAdornment> } }} sx={{ maxWidth: 520 }} />
      {err && <Alert severity="error">{err}</Alert>}
      {defs && !visibles.length && <Alert severity="info">Ningún maestro coincide con «{q}».</Alert>}
      {SECCIONES.map(sec => {
        const items = visibles.filter(x => x.seccion === sec)
        return items.length ? (
          <Box key={sec}>
            <Typography sx={{ fontWeight: 700, color: COL[sec], mb: 1 }}>{sec}</Typography>
            <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: 'minmax(0, 1fr)', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(3, minmax(0, 1fr))' } }}>
              {items.map(x => (
                <Card key={x.clave} variant="outlined" sx={{ '&:hover': { borderColor: x.color, boxShadow: 2 } }}>
                  <CardActionArea onClick={() => nav(x.ruta)} sx={{ p: 1.5, display: 'flex', gap: 1.5, alignItems: 'flex-start', justifyContent: 'flex-start', height: '100%' }}>
                    <Avatar sx={{ bgcolor: x.color, width: 44, height: 44 }}>{x.icono}</Avatar>
                    <Box sx={{ minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 700, lineHeight: 1.25 }}>{x.titulo}</Typography>
                      {x.desc && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: .25 }}>{x.desc}</Typography>}
                    </Box>
                  </CardActionArea>
                </Card>))}
            </Box>
          </Box>) : null
      })}
    </Box>)
}
