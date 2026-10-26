import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { AppBar, Avatar, Box, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem,
  Toolbar, Tooltip, Typography, useMediaQuery, useTheme, Button, Select, FormControlLabel, Switch } from '@mui/material'
import ExpandMore from '@mui/icons-material/ExpandMore'
import MenuIcon from '@mui/icons-material/Menu'
import LogoutIcon from '@mui/icons-material/Logout'
import Calculate from '@mui/icons-material/Calculate'
import LocalShipping from '@mui/icons-material/LocalShipping'
import Rule from '@mui/icons-material/Rule'
import Insights from '@mui/icons-material/Insights'
import Storage from '@mui/icons-material/Storage'
import ManageAccounts from '@mui/icons-material/ManageAccounts'
import History from '@mui/icons-material/History'
import MonitorHeart from '@mui/icons-material/MonitorHeart'
import FactCheck from '@mui/icons-material/FactCheck'
import ShoppingCart from '@mui/icons-material/ShoppingCart'
import { useYo } from './Yo'
import { NOMBRE_EMPRESA, useEmpresa } from './Empresa'
import { BannerSalud } from './Salud'
import Errores from './Errores'
import { enPrueba, getUser, logout, volverDePrueba, soloCediOn, setSoloCedi } from './api'

/** Menú «Informes»: todo lo que se consulta (no se opera). Agrupado en el desplegable. */
export const VISTAS = [
  { grupo: 'Control DDMRP', to: '/control', label: 'Foto actual', ayuda: 'Estado del buffer hoy', req: ['ver_control'] },
  { grupo: 'Control DDMRP', to: '/control/cambios', label: 'Cambios en un periodo', ayuda: 'Cómo se movió el semáforo entre dos fechas', req: ['ver_control'] },
  { grupo: 'Control DDMRP', to: '/control/tendencia', label: 'Tendencia en el tiempo', ayuda: 'Curva del buffer, inventario y flujo neto', req: ['ver_control'] },
  { grupo: 'Control DDMRP', to: '/control/mapa', label: 'Mapa de calor', ayuda: 'Item × tienda × fecha con el color de la zona, como el Excel', req: ['ver_control'] },
  { grupo: 'Análisis', to: '/dashboard', label: 'Alertas', ayuda: 'Zona roja y lo que hay que atender', req: ['ver_alertas'] },
  { grupo: 'Análisis', to: '/salud-inventario', label: 'Salud del inventario', ayuda: 'Zona de hoy × importancia del item: qué atender primero', req: ['ver_control'] },
  { grupo: 'Análisis', to: '/clasificacion', label: 'Clasificación ABC', ayuda: 'ABC por margen × XYZ por variabilidad, con filtros', req: ['ver_control'] },
  { grupo: 'Análisis', to: '/lanzamientos', label: 'Lanzamientos', ayuda: 'Items nuevos y reingresos al CEDI', req: ['ver_control'] },
  // Compras: las mismas pantallas, abiertas en «Ver solo CEDI». Solo para perfiles con ver_compras; aquí irán los informes propios de compras (necesidades, OC)
  { grupo: 'Compras', to: '/salud-inventario', label: 'Sobrestock y salud del CEDI', ayuda: 'Qué sobra, qué falta y dónde hay capital dormido en el CEDI', req: ['ver_control'], compras: true, cedi: true },
  { grupo: 'Compras', to: '/clasificacion', label: 'Clasificación ABC del CEDI', ayuda: 'ABC × XYZ del CEDI (su rotación suma lo que sale a las tiendas)', req: ['ver_control'], compras: true, cedi: true },
  { grupo: 'Compras', to: '/dashboard', label: 'Alertas del CEDI', ayuda: 'Zona roja y lo que hay que atender en el CEDI', req: ['ver_alertas'], compras: true, cedi: true },
] as { grupo: string; to: string; label: string; ayuda: string; req: string[]; compras?: boolean; cedi?: boolean }[]
export const NAV = [
  { to: '/control', label: 'Informes', icon: <Insights />, vistas: true, req: ['ver_control', 'ver_alertas'] },
  { to: '/despacho', label: 'Matriz de despacho', icon: <LocalShipping />, req: ['ver_despacho'] },
  { to: '/auditoria', label: 'Auditoría', icon: <FactCheck />, req: ['ver_auditoria'] },
  { to: '/motor', label: 'Motor DDMRP', icon: <Calculate />, req: ['correr_motor'] },
  { to: '/reglas', label: 'Reglas de pedido', icon: <Rule />, req: ['editar_reglas', 'correr_motor'] },
  { to: '/config', label: 'Maestros', icon: <Storage />, req: ['ver_maestros', 'cargar_maestros', 'sincronizar_siesa'] },
  { to: '/compras/maestros', label: 'Maestros compras', icon: <ShoppingCart />, req: ['ver_compras', 'cargar_maestros_compras'] },
  { to: '/usuarios', label: 'Usuarios', icon: <ManageAccounts />, req: ['admin_usuarios'] },
  { to: '/log', label: 'Log', icon: <History />, req: ['ver_log'] },
  { to: '/diagnostico', label: 'Diagnóstico', icon: <MonitorHeart />, req: ['ver_diagnostico'] },
]

export default function Shell() {
  const { yo, puede } = useYo(); const { empresa, setEmpresa, opciones } = useEmpresa()
  const NAV_OK = NAV.filter(n => puede(...n.req))
  const VISTAS_OK = VISTAS.filter(v => puede(...v.req) && (!v.compras || puede('ver_compras')))
  // quien ve los dos grupos de maestros tiene UN solo botón «Maestros» con un desplegable (DDMRP / compras); quien ve uno, el botón directo
  const ambosMaestros = puede('ver_maestros', 'cargar_maestros', 'sincronizar_siesa') && puede('ver_compras', 'cargar_maestros_compras')
  const [anclaM, setAnclaM] = useState<HTMLElement | null>(null)
  const theme = useTheme(); const movil = useMediaQuery(theme.breakpoints.down('md'))
  const [abierto, setAbierto] = useState(false); const [ancla, setAncla] = useState<HTMLElement | null>(null)
  const loc = useLocation(); const user = getUser(); const nav = useNavigate()
  const [anclaV, setAnclaV] = useState<HTMLElement | null>(null)
  const [menuEmp, setMenuEmp] = useState(false) // con el menú abierto el tooltip se apaga: tapaba la primera opción
  const enInformes = VISTAS.some(v => v.to === '/control' ? loc.pathname === '/control' : loc.pathname.startsWith(v.to))
  const titulo = VISTAS.find(v => loc.pathname === v.to)?.label ?? NAV.find(n => !(n as any).vistas && loc.pathname.startsWith(n.to))?.label ?? ''
  const activo = (n: any) => n.vistas ? enInformes : n.to === '/config' && ambosMaestros ? (loc.pathname.startsWith('/config') || loc.pathname.startsWith('/compras/maestros')) : loc.pathname.startsWith(n.to)
  // las entradas «del CEDI» de Compras activan «Ver solo CEDI» (y recargan si hacía falta); las demás respetan el modo actual
  const irA = (v: { to: string; cedi?: boolean }) => { setAnclaV(null); if (v.cedi && !soloCediOn()) { setSoloCedi(true); location.href = v.to } else nav(v.to) }
  return (
    <Box sx={{ height: '100dvh', width: '100%', maxWidth: '100vw', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <AppBar position="static" color="primary">
        <Toolbar variant="dense" sx={{ gap: { xs: .5, md: 1 }, minWidth: 0, px: { xs: 1, md: 2 } }}>
          {movil && <IconButton color="inherit" edge="start" onClick={() => setAbierto(true)}><MenuIcon /></IconButton>}
          <Box component="img" src="/logo-sersa.jpeg" alt="" sx={{ height: 28, borderRadius: 1, bgcolor: 'white', p: .3, flexShrink: 0, display: { xs: 'none', sm: 'block' } }} />
          <Typography sx={{ fontWeight: 700, mr: { xs: 0, md: 2 }, display: { xs: 'none', sm: 'block' } }}>DDMRP</Typography>
          {!movil ? NAV_OK.filter(n => !(ambosMaestros && n.to === '/compras/maestros')).map(n => (n as any).vistas ? (
            <Box key={n.to}>
              <Button color="inherit" startIcon={n.icon} endIcon={<ExpandMore />} onClick={e => setAnclaV(e.currentTarget)}
                sx={{ opacity: activo(n) ? 1 : .75, borderBottom: activo(n) ? '2px solid #fff' : '2px solid transparent', borderRadius: 0 }}>{n.label}</Button>
              <Menu anchorEl={anclaV} open={!!anclaV} onClose={() => setAnclaV(null)}>
                {[...new Set(VISTAS_OK.map(v => v.grupo))].flatMap(g => [
                  <ListSubheader key={'g' + g} sx={{ lineHeight: '30px', fontWeight: 700, color: 'primary.main' }}>{g}</ListSubheader>,
                  ...VISTAS_OK.filter(v => v.grupo === g).map(v => <MenuItem key={v.to + (v.cedi ? '#cedi' : '')} selected={loc.pathname === v.to && (!v.cedi || soloCediOn())} onClick={() => irA(v)}>
                    <Box><Box sx={{ fontWeight: 600 }}>{v.label}</Box><Box sx={{ fontSize: 12, color: 'text.secondary' }}>{v.ayuda}</Box></Box></MenuItem>)])}
              </Menu>
            </Box>) : n.to === '/config' && ambosMaestros ? (
            <Box key={n.to}>
              <Button color="inherit" startIcon={n.icon} endIcon={<ExpandMore />} onClick={e => setAnclaM(e.currentTarget)}
                sx={{ opacity: activo(n) ? 1 : .75, borderBottom: activo(n) ? '2px solid #fff' : '2px solid transparent', borderRadius: 0 }}>Maestros</Button>
              <Menu anchorEl={anclaM} open={!!anclaM} onClose={() => setAnclaM(null)}>
                <MenuItem selected={loc.pathname.startsWith('/config')} onClick={() => { setAnclaM(null); nav('/config') }}>
                  <Box><Box sx={{ fontWeight: 600 }}>Maestros DDMRP</Box><Box sx={{ fontSize: 12, color: 'text.secondary' }}>Tiendas, lead times, cotas, reglas…</Box></Box></MenuItem>
                <MenuItem selected={loc.pathname.startsWith('/compras/maestros')} onClick={() => { setAnclaM(null); nav('/compras/maestros') }}>
                  <Box><Box sx={{ fontWeight: 600 }}>Maestros de compras</Box><Box sx={{ fontSize: 12, color: 'text.secondary' }}>Lead time del CEDI, proveedores…</Box></Box></MenuItem>
              </Menu>
            </Box>) : (
            <Button key={n.to} component={NavLink} to={n.to} color="inherit" startIcon={n.icon}
              sx={{ opacity: activo(n) ? 1 : .75, borderBottom: activo(n) ? '2px solid #fff' : '2px solid transparent', borderRadius: 0 }}>
              {n.label}</Button>))
            
            : <Typography noWrap sx={{ flex: 1, minWidth: 0, fontSize: { xs: 15, sm: 16 } }}>{titulo}</Typography>}
          <Box sx={{ flex: 1 }} />
          {enInformes && (
            <Tooltip disableInteractive title="Solo el CEDI: sus necesidades, sobrestock y clasificación. La rotación suma lo que sale a las tiendas. Oculta las tiendas en Informes.">
              <FormControlLabel sx={{ color: '#fff', mr: 1, ml: 0, '.MuiFormControlLabel-label': { fontSize: 14, fontWeight: 600 } }}
                control={<Switch size="small" color="default" checked={soloCediOn()}
                  onChange={e => { setSoloCedi(e.target.checked); location.reload() }} />}
                label={movil ? 'CEDI' : 'Ver solo CEDI'} />
            </Tooltip>)}
          <Tooltip disableInteractive title={menuEmp ? '' : 'Empresa con la que trabajas en todas las pantallas. Se conserva hasta que la cambies.'}>
            {opciones.length > 1 ? (
              <Select size="small" value={empresa} open={menuEmp} onOpen={() => setMenuEmp(true)} onClose={() => setMenuEmp(false)} onChange={e => setEmpresa(e.target.value)} variant="outlined" renderValue={(v: string) => movil ? (v === '*' ? 'Ambas' : (NOMBRE_EMPRESA[v] ?? v)) : (v === '*' ? 'Ambas empresas' : `${NOMBRE_EMPRESA[v] ?? v} (${v})`)}
                sx={{ color: '#fff', height: 32, fontSize: 14, fontWeight: 600, '.MuiSelect-icon': { color: '#fff' }, '.MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,.6)' }, '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: '#fff' } }}>
                {opciones.map(o => <MenuItem key={o} value={o}>{o === '*' ? 'Ambas empresas' : `${NOMBRE_EMPRESA[o] ?? o} (${o})`}</MenuItem>)}
              </Select>) : (
              <Box sx={{ border: '1px solid rgba(255,255,255,.6)', borderRadius: 1, px: 1, py: .25, fontSize: 14, fontWeight: 600 }}>{NOMBRE_EMPRESA[empresa] ?? empresa} ({empresa})</Box>)}
          </Tooltip>
          <IconButton onClick={e => setAncla(e.currentTarget)} size="small">
            <Avatar sx={{ width: 32, height: 32, bgcolor: '#fff', color: 'primary.main', fontSize: 14, fontWeight: 700 }}>{(((yo?.nombre || '').trim() || user)[0] || '?').toUpperCase()}</Avatar>
          </IconButton>
          <Menu anchorEl={ancla} open={!!ancla} onClose={() => setAncla(null)}>
            <Box sx={{ px: 2, py: 1, maxWidth: 300 }}>
              <Typography sx={{ fontWeight: 700, fontSize: 14, lineHeight: 1.3, textTransform: 'capitalize' }}>{(yo?.nombre || user || 'Usuario').toLowerCase()}</Typography>
              {yo?.nombre && user && yo.nombre !== user && <Typography variant="caption" color="text.secondary">Usuario {user}</Typography>}
            </Box><Divider />
            <MenuItem onClick={logout}><ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>Cerrar sesión</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Drawer open={abierto} onClose={() => setAbierto(false)}>
        <List sx={{ width: 250 }}>
          {NAV_OK.flatMap(n => (n as any).vistas ? VISTAS_OK.map(v => ({ to: v.to, label: 'Informes · ' + v.label, icon: n.icon })) : [n]).map(n => (
            <ListItemButton key={n.to} component={NavLink} to={n.to} onClick={() => setAbierto(false)} selected={loc.pathname === n.to}>
              <ListItemIcon>{n.icon}</ListItemIcon><ListItemText primary={n.label} /></ListItemButton>))}
        </List>
      </Drawer>
      {enPrueba() && (
        <Box sx={{ bgcolor: '#b45309', color: '#fff', px: 2, py: .5, display: 'flex', alignItems: 'center', gap: 2, fontSize: 14 }}>
          <Box sx={{ flex: 1 }}>Modo prueba: ves la aplicación como <b>{user}</b>, sin reloj. Lo que hagas queda registrado con ese nombre.</Box>
          <Button size="small" variant="outlined" color="inherit" onClick={volverDePrueba}>Volver a mi usuario</Button>
        </Box>)}
      <Box component="main" sx={{ flex: 1, minHeight: 0, minWidth: 0, p: { xs: 1, md: 2 }, overflow: 'auto' }}><BannerSalud /><Errores clave={loc.pathname}><Outlet /></Errores></Box>
    </Box>)
}
