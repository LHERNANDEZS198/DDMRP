import { useState } from 'react'
import { Route, Routes, Navigate } from 'react-router-dom'
import { hasToken } from './api'
import Login from './Login'
import Shell from './Shell'
import Control from './pages/Control'
import Dashboard from './pages/Dashboard'
import Config from './pages/Config'
import Despacho from './pages/Despacho'
import Reglas from './pages/Reglas'

export default function App() {
  const [ok, setOk] = useState(hasToken())
  if (!ok) return <Login onOk={() => setOk(true)} />
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/control" element={<Control />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/despacho" element={<Despacho />} />
        <Route path="/reglas" element={<Reglas />} />
        <Route path="/config" element={<Config />} />
        <Route path="*" element={<Navigate to="/control" />} />
      </Route>
    </Routes>)
}
