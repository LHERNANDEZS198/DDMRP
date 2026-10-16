import { useState } from 'react'
import { Alert, Box, Button, IconButton, InputAdornment, Paper, TextField } from '@mui/material'
import PersonOutline from '@mui/icons-material/PersonOutline'
import LockOutlined from '@mui/icons-material/LockOutlined'
import Visibility from '@mui/icons-material/Visibility'
import VisibilityOff from '@mui/icons-material/VisibilityOff'
import { login } from './api'
import { VERDE } from './theme'

export default function Login({ onOk }: { onOk: () => void }) {
  const [u, setU] = useState(''); const [p, setP] = useState(''); const [ver, setVer] = useState(false)
  const [err, setErr] = useState(''); const [cargando, setCargando] = useState(false)
  const enviar = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(''); setCargando(true)
    try { await login(u.trim(), p); onOk() } catch (x: any) { setErr(x.message) } finally { setCargando(false) }
  }
  return (
    <Box sx={{ minHeight: '100vh', bgcolor: '#f5f7f0', display: 'flex', alignItems: 'center', justifyContent: 'center', px: 2 }}>
      <Paper elevation={3} sx={{ width: '100%', maxWidth: 400, borderRadius: 3, overflow: 'hidden' }}>
        <Box sx={{ bgcolor: 'white', py: 3, display: 'flex', justifyContent: 'center', borderBottom: `4px solid ${VERDE}` }}>
          <Box component="img" src="/logo-sersa.jpeg" alt="Logo" sx={{ height: 64, objectFit: 'contain' }} />
        </Box>
        <Box component="form" onSubmit={enviar} sx={{ p: 4, display: 'grid', gap: 2 }}>
          <Box>
            <Box sx={{ fontSize: 20, fontWeight: 700 }}>Abastecimiento DDMRP</Box>
            <Box sx={{ color: 'text.secondary', fontSize: 14 }}>Inicia sesión para continuar</Box>
          </Box>
          {err && <Alert severity="error">{err}</Alert>}
          <TextField label="Usuario" value={u} onChange={e => setU(e.target.value)} autoFocus fullWidth size="small"
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><PersonOutline fontSize="small" /></InputAdornment> } }} />
          <TextField label="Clave" type={ver ? 'text' : 'password'} value={p} onChange={e => setP(e.target.value)} fullWidth size="small"
            slotProps={{ input: {
              startAdornment: <InputAdornment position="start"><LockOutlined fontSize="small" /></InputAdornment>,
              endAdornment: <InputAdornment position="end"><IconButton size="small" onClick={() => setVer(!ver)}>{ver ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}</IconButton></InputAdornment> } }} />
          <Button type="submit" variant="contained" size="large" disabled={cargando || !u || !p}>{cargando ? 'Entrando…' : 'Entrar'}</Button>
        </Box>
      </Paper>
    </Box>)
}
