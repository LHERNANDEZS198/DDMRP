import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { AppBar, Avatar, Box, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem,
  Toolbar, Tooltip, Typography, useMediaQuery, useTheme, Button, Select } from '@mui/material'
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
import FactCheck from '@mui/icons-material/FactCheck'
import { useYo } from './Yo'
import { NOMBRE_EMPRESA, useEmpresa } from './Empresa'
import { BannerSalud } from './Salud'
import Errores from './Errores'
import { enPrueba, getUser, logout, volverDePrueba } from './api'

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
]
export const NAV = [
  { to: '/control', label: 'Informes', icon: <Insights />, vistas: true, req: ['ver_control', 'ver_alertas'] },
  { to: '/despacho', label: 'Matriz de despacho', icon: <LocalShipping />, req: ['ver_despacho'] },
  { to: '/auditoria', label: 'Auditoría', icon: <FactCheck />, req: ['ver_auditoria'] },
  { to: '/motor', label: 'Motor DDMRP', icon: <Calculate />, req: ['correr_motor'] },
  { to: '/reglas', label: 'Reglas de pedido', icon: <Rule />, req: ['editar_reglas', 'correr_motor'] },
  { to: '/config', label: 'Maestros', icon: <Storage />, req: ['ver_maestros', 'cargar_maestros', 'sincronizar_siesa'] },
  { to: '/usuarios', label: 'Usuarios', icon: <ManageAccounts />, req: ['admin_usuarios'] },
  { to: '/log', label: 'Log', icon: <History />, req: ['ver_log'] },
]

export default function Shell() {
  const { yo, puede } = useYo(); const { empresa, setEmpresa, opciones } = useEmpresa()
  const NAV_OK = NAV.filter(n => puede(...n.req))
  const VISTAS_OK = VISTAS.filter(v => puede(...v.req))
  const theme = useTheme(); const movil = useMediaQuery(theme.breakpoints.down('md'))
  const [abierto, setAbierto] = useState(false); const [ancla, setAncla] = useState<HTMLElement | null>(null)
  const loc = useLocation(); const user = getUser(); const nav = useNavigate()
  const [anclaV, setAnclaV] = useState<HTMLElement | null>(null)
  const enInformes = VISTAS.some(v => v.to === '/control' ? loc.pathname === '/control' : loc.pathname.startsWith(v.to))
  const titulo = VISTAS.find(v => loc.pathname === v.to)?.label ?? NAV.find(n => !(n as any).vistas && loc.pathname.startsWith(n.to))?.label ?? ''
  const activo = (n: any) => n.vistas ? enInformes : loc.pathname.startsWith(n.to)
  return (
    <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppBar position="static" color="primary">
        <Toolbar variant="dense" sx={{ gap: 1 }}>
          {movil && <IconButton color="inherit" edge="start" onClick={() => setAbierto(true)}><MenuIcon /></IconButton>}
          <Box component="img" src="/logo-sersa.jpeg" alt="" sx={{ height: 30, borderRadius: 1, bgcolor: 'white', p: .3 }} />
          <Typography sx={{ fontWeight: 700, mr: 2 }}>DDMRP</Typography>
          {!movil ? NAV_OK.map(n => (n as any).vistas ? (
            <Box key={n.to}>
              <Button color="inherit" startIcon={n.icon} endIcon={<ExpandMore />} onClick={e => setAnclaV(e.currentTarget)}
                sx={{ opacity: activo(n) ? 1 : .75, borderBottom: activo(n) ? '2px solid #fff' : '2px solid transparent', borderRadius: 0 }}>{n.label}</Button>
              <Menu anchorEl={anclaV} open={!!anclaV} onClose={() => setAnclaV(null)}>
                {[...new Set(VISTAS_OK.map(v => v.grupo))].flatMap(g => [
                  <ListSubheader key={'g' + g} sx={{ lineHeight: '30px', fontWeight: 700, color: 'primary.main' }}>{g}</ListSubheader>,
                  ...VISTAS_OK.filter(v => v.grupo === g).map(v => <MenuItem key={v.to} selected={loc.pathname === v.to} onClick={() => { setAnclaV(null); nav(v.to) }}>
                    <Box><Box sx={{ fontWeight: 600 }}>{v.label}</Box><Box sx={{ fontSize: 12, color: 'text.secondary' }}>{v.ayuda}</Box></Box></MenuItem>)])}
              </Menu>
            </Box>) : (
            <Button key={n.to} component={NavLink} to={n.to} color="inherit" startIcon={n.icon}
              sx={{ opacity: activo(n) ? 1 : .75, borderBottom: activo(n) ? '2px solid #fff' : '2px solid transparent', borderRadius: 0 }}>
              {n.label}</Button>))
            : <Typography sx={{ flex: 1 }}>{titulo}</Typography>}
          <Box sx={{ flex: 1 }} />
          <Tooltip title="Empresa con la que trabajas en todas las pantallas. Se conserva hasta que la cambies.">
            {opciones.length > 1 ? (
              <Select size="small" value={empresa} onChange={e => setEmpresa(e.target.value)} variant="outlined"
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
      <Box component="main" sx={{ flex: 1, minHeight: 0, p: { xs: 1, md: 2 }, overflow: 'auto' }}><BannerSalud /><Errores clave={loc.pathname}><Outlet /></Errores></Box>
    </Box>)
}
