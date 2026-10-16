import { useState } from 'react'
import { NavLink, Route, Routes, Navigate } from 'react-router-dom'
import { hasToken, login } from './api'
import Dashboard from './pages/Dashboard'
import Config from './pages/Config'
import Despacho from './pages/Despacho'
import Reglas from './pages/Reglas'

export default function App() {
  const [ok, setOk] = useState(hasToken())
  const [u, setU] = useState(''); const [p, setP] = useState(''); const [err, setErr] = useState('')
  if (!ok) return (
    <form style={{ maxWidth: 320, margin: '15vh auto', display: 'grid', gap: 8 }}
      onSubmit={async e => { e.preventDefault(); try { await login(u, p); setOk(true) } catch (x: any) { setErr(x.message) } }}>
      <h2>DDMRP Abastecimiento</h2>
      <input placeholder="Usuario" value={u} onChange={e => setU(e.target.value)} />
      <input placeholder="Clave" type="password" value={p} onChange={e => setP(e.target.value)} />
      <button>Entrar</button><span style={{ color: 'crimson' }}>{err}</span>
    </form>)
  return (
    <div style={{ fontFamily: 'system-ui', height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <nav style={{ display: 'flex', gap: 16, padding: 12, borderBottom: '1px solid #ddd' }}>
        <NavLink to="/dashboard">Alertas</NavLink>
        <NavLink to="/despacho">Matriz de despacho</NavLink>
        <NavLink to="/reglas">Reglas de pedido</NavLink>
        <NavLink to="/config">Maestros</NavLink>
      </nav>
      <main style={{ flex: 1, padding: 12, minHeight: 0 }}>
        <Routes>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/despacho" element={<Despacho />} />
          <Route path="/reglas" element={<Reglas />} />
          <Route path="/config" element={<Config />} />
          <Route path="*" element={<Navigate to="/dashboard" />} />
        </Routes>
      </main>
    </div>)
}
