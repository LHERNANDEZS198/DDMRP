import { ReactElement, useEffect, useState } from 'react'
import { Route, Routes, Navigate } from 'react-router-dom'
import { Box, Button, CircularProgress, Typography } from '@mui/material'
import { api, hasToken, logout } from './api'
import Login from './Login'
import Shell from './Shell'
import Control from './pages/Control'
import Dashboard from './pages/Dashboard'
import Config from './pages/Config'
import Despacho from './pages/Despacho'
import Reglas from './pages/Reglas'
import Motor from './pages/Motor'
import Usuarios from './pages/Usuarios'
import Log from './pages/Log'
import Auditoria from './pages/Auditoria'
import Lanzamientos from './pages/Lanzamientos'
import Clasificacion from './pages/Clasificacion'
import SaludInventario from './pages/Salud'
import { SaludProvider } from './Salud'
import { Yo, YoCtx, useYo } from './Yo'

/** Pantallas y la función que las habilita (basta una). Se usa también en el menú. */
export const PANTALLAS = [
  { to: '/control', req: ['ver_control'] },
  { to: '/lanzamientos', req: ['ver_control'] },
  { to: '/salud-inventario', req: ['ver_control'] },
  { to: '/clasificacion', req: ['ver_control'] },
  { to: '/dashboard', req: ['ver_alertas'] },
  { to: '/despacho', req: ['ver_despacho'] },
  { to: '/auditoria', req: ['ver_auditoria'] },
  { to: '/motor', req: ['correr_motor'] },
  { to: '/reglas', req: ['editar_reglas', 'correr_motor'] },
  { to: '/config', req: ['ver_maestros', 'cargar_maestros', 'sincronizar_siesa'] },
  { to: '/usuarios', req: ['admin_usuarios'] },
  { to: '/log', req: ['ver_log'] },
]

function Req({ to, children }: { to: string; children: ReactElement }) {
  const { puede } = useYo()
  const p = PANTALLAS.find(x => to.startsWith(x.to))
  return !p || puede(...p.req) ? children : <Navigate to="/" replace />
}

function Inicio() {
  const { puede, yo } = useYo()
  const p = PANTALLAS.find(x => puede(...x.req))
  if (p) return <Navigate to={p.to} replace />
  return (
    <Box sx={{ maxWidth: 520, mx: 'auto', mt: 8, textAlign: 'center', display: 'grid', gap: 1.5 }}>
      <Typography variant="h6" sx={{ fontWeight: 700 }}>Tu usuario aún no tiene un perfil</Typography>
      <Typography color="text.secondary">Entraste como {yo?.nombre}, pero nadie te ha dado acceso a esta aplicación. Pídele al administrador que te asigne un perfil.</Typography>
      <Box><Button onClick={logout}>Cerrar sesión</Button></Box>
    </Box>)
}

export default function App() {
  const [ok, setOk] = useState(hasToken())
  const [yo, setYo] = useState<Yo | null>(null)
  useEffect(() => { if (ok) api('/auth/me').then(setYo).catch(() => {}) }, [ok])
  if (!ok) return <Login onOk={() => setOk(true)} />
  if (!yo) return <Box sx={{ display: 'grid', placeItems: 'center', height: '100vh' }}><CircularProgress /></Box>
  return (
    <YoCtx.Provider value={yo}>
      <Routes>
        <Route element={<SaludProvider><Shell /></SaludProvider>}>
          <Route path="/control" element={<Req to="/control"><Control /></Req>} />
          <Route path="/control/cambios" element={<Req to="/control"><Control /></Req>} />
          <Route path="/control/tendencia" element={<Req to="/control"><Control /></Req>} />
          <Route path="/control/mapa" element={<Req to="/control"><Control /></Req>} />
          <Route path="/salud-inventario" element={<Req to="/salud-inventario"><SaludInventario /></Req>} />
          <Route path="/clasificacion" element={<Req to="/clasificacion"><Clasificacion /></Req>} />
          <Route path="/lanzamientos" element={<Req to="/lanzamientos"><Lanzamientos /></Req>} />
          <Route path="/dashboard" element={<Req to="/dashboard"><Dashboard /></Req>} />
          <Route path="/despacho" element={<Req to="/despacho"><Despacho /></Req>} />
          <Route path="/motor" element={<Req to="/motor"><Motor /></Req>} />
          <Route path="/reglas" element={<Req to="/reglas"><Reglas /></Req>} />
          <Route path="/config" element={<Req to="/config"><Config /></Req>} />
          <Route path="/usuarios" element={<Req to="/usuarios"><Usuarios /></Req>} />
          <Route path="/auditoria" element={<Req to="/auditoria"><Auditoria /></Req>} />
          <Route path="/log" element={<Req to="/log"><Log /></Req>} />
          <Route path="*" element={<Inicio />} />
        </Route>
      </Routes>
    </YoCtx.Provider>)
}
