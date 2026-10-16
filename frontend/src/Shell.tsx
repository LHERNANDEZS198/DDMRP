import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { AppBar, Avatar, Box, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Menu, MenuItem,
  Toolbar, Typography, useMediaQuery, useTheme, Button } from '@mui/material'
import ExpandMore from '@mui/icons-material/ExpandMore'
import MenuIcon from '@mui/icons-material/Menu'
import LogoutIcon from '@mui/icons-material/Logout'
import WarningAmber from '@mui/icons-material/WarningAmber'
import LocalShipping from '@mui/icons-material/LocalShipping'
import Rule from '@mui/icons-material/Rule'
import Insights from '@mui/icons-material/Insights'
import Storage from '@mui/icons-material/Storage'
import ManageAccounts from '@mui/icons-material/ManageAccounts'
import History from '@mui/icons-material/History'
import FactCheck from '@mui/icons-material/FactCheck'
import { useYo } from './Yo'
import { BannerSalud } from './Salud'
import Errores from './Errores'
import { getUser, logout } from './api'

export const VISTAS = [
  { to: '/control', label: 'Foto actual', ayuda: 'Estado del buffer hoy' },
  { to: '/control/cambios', label: 'Cambios en un periodo', ayuda: 'Cómo se movió el semáforo entre dos fechas' },
  { to: '/control/tendencia', label: 'Tendencia en el tiempo', ayuda: 'Curva del buffer, inventario y flujo neto' },
]
export const NAV = [
  { to: '/control', label: 'Control DDMRP', icon: <Insights />, vistas: true, req: ['ver_control'] },
  { to: '/dashboard', label: 'Alertas', icon: <WarningAmber />, req: ['ver_alertas'] },
  { to: '/despacho', label: 'Matriz de despacho', icon: <LocalShipping />, req: ['ver_despacho'] },
  { to: '/auditoria', label: 'Auditoría', icon: <FactCheck />, req: ['ver_auditoria'] },
  { to: '/reglas', label: 'Reglas de pedido', icon: <Rule />, req: ['editar_reglas', 'correr_motor'] },
  { to: '/config', label: 'Maestros', icon: <Storage />, req: ['ver_maestros', 'cargar_maestros', 'sincronizar_siesa'] },
  { to: '/usuarios', label: 'Usuarios', icon: <ManageAccounts />, req: ['admin_usuarios'] },
  { to: '/log', label: 'Log', icon: <History />, req: ['ver_log'] },
]

export default function Shell() {
  const { yo, puede } = useYo()
  const NAV_OK = NAV.filter(n => puede(...n.req))
  const theme = useTheme(); const movil = useMediaQuery(theme.breakpoints.down('md'))
  const [abierto, setAbierto] = useState(false); const [ancla, setAncla] = useState<HTMLElement | null>(null)
  const loc = useLocation(); const user = getUser(); const nav = useNavigate()
  const [anclaV, setAnclaV] = useState<HTMLElement | null>(null)
  const titulo = NAV.find(n => loc.pathname.startsWith(n.to))?.label ?? ''
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
                sx={{ opacity: loc.pathname.startsWith(n.to) ? 1 : .75, borderBottom: loc.pathname.startsWith(n.to) ? '2px solid #fff' : '2px solid transparent', borderRadius: 0 }}>{n.label}</Button>
              <Menu anchorEl={anclaV} open={!!anclaV} onClose={() => setAnclaV(null)}>
                {VISTAS.map(v => <MenuItem key={v.to} selected={loc.pathname === v.to} onClick={() => { setAnclaV(null); nav(v.to) }}>
                  <Box><Box sx={{ fontWeight: 600 }}>{v.label}</Box><Box sx={{ fontSize: 12, color: 'text.secondary' }}>{v.ayuda}</Box></Box></MenuItem>)}
              </Menu>
            </Box>) : (
            <Button key={n.to} component={NavLink} to={n.to} color="inherit" startIcon={n.icon}
              sx={{ opacity: loc.pathname.startsWith(n.to) ? 1 : .75, borderBottom: loc.pathname.startsWith(n.to) ? '2px solid #fff' : '2px solid transparent', borderRadius: 0 }}>
              {n.label}</Button>))
            : <Typography sx={{ flex: 1 }}>{titulo}</Typography>}
          <Box sx={{ flex: 1 }} />
          <IconButton onClick={e => setAncla(e.currentTarget)} size="small">
            <Avatar sx={{ width: 32, height: 32, bgcolor: '#fff', color: 'primary.main', fontSize: 14, fontWeight: 700 }}>{(user[0] || '?').toUpperCase()}</Avatar>
          </IconButton>
          <Menu anchorEl={ancla} open={!!ancla} onClose={() => setAncla(null)}>
            <MenuItem disabled>{yo?.nombre || user || 'Usuario'} · {user}</MenuItem><Divider />
            <MenuItem onClick={logout}><ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>Cerrar sesión</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Drawer open={abierto} onClose={() => setAbierto(false)}>
        <List sx={{ width: 250 }}>
          {NAV_OK.flatMap(n => (n as any).vistas ? VISTAS.map(v => ({ to: v.to, label: 'Control · ' + v.label, icon: n.icon })) : [n]).map(n => (
            <ListItemButton key={n.to} component={NavLink} to={n.to} onClick={() => setAbierto(false)} selected={loc.pathname === n.to}>
              <ListItemIcon>{n.icon}</ListItemIcon><ListItemText primary={n.label} /></ListItemButton>))}
        </List>
      </Drawer>
      <Box component="main" sx={{ flex: 1, minHeight: 0, p: { xs: 1, md: 2 }, overflow: 'auto' }}><BannerSalud /><Errores clave={loc.pathname}><Outlet /></Errores></Box>
    </Box>)
}
