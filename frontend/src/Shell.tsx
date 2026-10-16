import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { AppBar, Avatar, Box, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Menu, MenuItem,
  Toolbar, Typography, useMediaQuery, useTheme, Button } from '@mui/material'
import MenuIcon from '@mui/icons-material/Menu'
import LogoutIcon from '@mui/icons-material/Logout'
import WarningAmber from '@mui/icons-material/WarningAmber'
import LocalShipping from '@mui/icons-material/LocalShipping'
import Rule from '@mui/icons-material/Rule'
import Storage from '@mui/icons-material/Storage'
import { getUser, logout } from './api'

export const NAV = [
  { to: '/dashboard', label: 'Alertas', icon: <WarningAmber /> },
  { to: '/despacho', label: 'Matriz de despacho', icon: <LocalShipping /> },
  { to: '/reglas', label: 'Reglas de pedido', icon: <Rule /> },
  { to: '/config', label: 'Maestros', icon: <Storage /> },
]

export default function Shell() {
  const theme = useTheme(); const movil = useMediaQuery(theme.breakpoints.down('md'))
  const [abierto, setAbierto] = useState(false); const [ancla, setAncla] = useState<HTMLElement | null>(null)
  const loc = useLocation(); const user = getUser()
  const titulo = NAV.find(n => loc.pathname.startsWith(n.to))?.label ?? ''
  return (
    <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppBar position="static" color="primary">
        <Toolbar variant="dense" sx={{ gap: 1 }}>
          {movil && <IconButton color="inherit" edge="start" onClick={() => setAbierto(true)}><MenuIcon /></IconButton>}
          <Box component="img" src="/logo-sersa.jpeg" alt="" sx={{ height: 30, borderRadius: 1, bgcolor: 'white', p: .3 }} />
          <Typography sx={{ fontWeight: 700, mr: 2 }}>DDMRP</Typography>
          {!movil ? NAV.map(n => (
            <Button key={n.to} component={NavLink} to={n.to} color="inherit" startIcon={n.icon}
              sx={{ opacity: loc.pathname.startsWith(n.to) ? 1 : .75, borderBottom: loc.pathname.startsWith(n.to) ? '2px solid #fff' : '2px solid transparent', borderRadius: 0 }}>
              {n.label}</Button>))
            : <Typography sx={{ flex: 1 }}>{titulo}</Typography>}
          <Box sx={{ flex: 1 }} />
          <IconButton onClick={e => setAncla(e.currentTarget)} size="small">
            <Avatar sx={{ width: 32, height: 32, bgcolor: '#fff', color: 'primary.main', fontSize: 14, fontWeight: 700 }}>{(user[0] || '?').toUpperCase()}</Avatar>
          </IconButton>
          <Menu anchorEl={ancla} open={!!ancla} onClose={() => setAncla(null)}>
            <MenuItem disabled>{user || 'Usuario'}</MenuItem><Divider />
            <MenuItem onClick={logout}><ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>Cerrar sesión</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Drawer open={abierto} onClose={() => setAbierto(false)}>
        <List sx={{ width: 250 }}>
          {NAV.map(n => (
            <ListItemButton key={n.to} component={NavLink} to={n.to} onClick={() => setAbierto(false)} selected={loc.pathname.startsWith(n.to)}>
              <ListItemIcon>{n.icon}</ListItemIcon><ListItemText primary={n.label} /></ListItemButton>))}
        </List>
      </Drawer>
      <Box component="main" sx={{ flex: 1, minHeight: 0, p: { xs: 1, md: 2 }, overflow: 'auto' }}><Outlet /></Box>
    </Box>)
}
