import { useEffect, useMemo, useState } from 'react'
import { Autocomplete, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, IconButton, MenuItem,
  Paper, Stack, Switch, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import Add from '@mui/icons-material/Add'
import Edit from '@mui/icons-material/Edit'
import DeleteOutline from '@mui/icons-material/DeleteOutline'
import Visibility from '@mui/icons-material/Visibility'
import { api, verComo } from '../api'
import Aviso from '../Aviso'
import { useYo } from '../Yo'
import { confirmar } from '../alertas'

type Perm = { clave: string; label: string; grupo: string }
type Perfil = { perfil_id: string; nombre: string; descripcion: string; nivel: string; permisos: string[]; sistema: boolean; usuarios: number }
type Usr = { usuario_id: string; nombre: string; perfil_id: string; perfil: string; activo: boolean; bodegas: string[]; categorias: string[]; bootstrap: boolean }
type Op = { id: string; nombre: string }

const NIVELES: Record<string, string> = {
  lectura: 'Lectura — solo ve',
  edicion: 'Edición — puede corregir datos de sus tiendas',
  aprobacion: 'Aprobación — además aprueba y genera planos',
}
const alcance = (u: Usr) => `${u.bodegas.length ? u.bodegas.length + ' tienda(s)' : 'Todas las tiendas'} · ${u.categorias.length ? u.categorias.length + ' lab(s)' : 'todos los labs'}`

/* ---------------- Usuarios ---------------- */
function Usuarios({ perfiles, setMsg }: { perfiles: Perfil[]; setMsg: (s: string) => void }) {
  const { yo } = useYo()
  const [lista, setLista] = useState<Usr[]>([])
  const [q, setQ] = useState('')
  const [ed, setEd] = useState<Partial<Usr> & { nuevo?: boolean } | null>(null)
  const [op, setOp] = useState<{ tiendas: Op[]; laboratorios: Op[] }>({ tiendas: [], laboratorios: [] })
  const [vc, setVc] = useState<{ perfil_id: string; bodegas: string[]; categorias: string[] } | null>(null)
  const [reloj, setReloj] = useState<Op[]>([])
  const [relojOk, setRelojOk] = useState(true)
  const cargar = () => api('/usuarios').then(setLista).catch(e => setMsg('Error: ' + e.message))
  useEffect(() => { cargar(); api('/usuarios/opciones').then(setOp).catch(() => {}) }, [])

  // búsqueda en reloj al escribir el código/nombre de un usuario nuevo
  useEffect(() => {
    if (!ed?.nuevo) return
    const t = ed.usuario_id ?? ''
    if (t.length < 2) { setReloj([]); return }
    const h = setTimeout(() => api('/usuarios/reloj?q=' + encodeURIComponent(t)).then(r => { setReloj(r.usuarios); setRelojOk(r.disponible) }).catch(() => {}), 350)
    return () => clearTimeout(h)
  }, [ed?.usuario_id, ed?.nuevo])

  const filas = useMemo(() => {
    const s = q.trim().toLowerCase()
    return lista.filter(u => !s || u.usuario_id.toLowerCase().includes(s) || (u.nombre ?? '').toLowerCase().includes(s) || (u.perfil ?? '').toLowerCase().includes(s))
  }, [lista, q])

  const guardar = async (u: Partial<Usr>, cerrar = true) => {
    try {
      await api('/usuarios/' + encodeURIComponent(u.usuario_id!.trim()), { method: 'PUT', body: JSON.stringify({
        nombre: u.nombre ?? '', perfil_id: u.perfil_id, activo: u.activo ?? true, bodegas: u.bodegas ?? [], categorias: u.categorias ?? [] }) })
      setMsg(`Usuario ${u.usuario_id} guardado`); if (cerrar) setEd(null); cargar()
    } catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const borrar = async (u: Usr) => {
    if (!(await confirmar(`Quitar a ${u.nombre || u.usuario_id}`, 'No se borra de reloj: solo pierde el acceso a esta aplicación.', { peligro: true, si: 'Sí, quitar' }))) return
    try { await api('/usuarios/' + encodeURIComponent(u.usuario_id), { method: 'DELETE' }); setMsg('Usuario eliminado'); cargar() }
    catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const perfilSel = perfiles.find(p => p.perfil_id === ed?.perfil_id)
  const esAdminPerfil = !!perfilSel?.permisos.includes('admin')

  return (
    <Stack spacing={1.5}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
        <TextField size="small" label="Buscar" value={q} onChange={e => setQ(e.target.value)} sx={{ minWidth: 260 }} />
        <Box sx={{ flex: 1 }} />
        <Button variant="outlined" startIcon={<Visibility />} onClick={() => setVc({ perfil_id: perfiles[0]?.perfil_id ?? '', bodegas: [], categorias: [] })}
          title="Entrar como un perfil, sin reloj, para ver sus menús">Ver como perfil</Button>
        <Button variant="contained" startIcon={<Add />} onClick={() => setEd({ nuevo: true, usuario_id: '', nombre: '', perfil_id: 'consulta', activo: true, bodegas: [], categorias: [] })}>Agregar usuario</Button>
      </Stack>
      <Typography variant="body2" color="text.secondary">
        La clave sigue siendo la de reloj. Aquí se decide qué puede hacer cada persona (perfil) y sobre qué tiendas y laboratorios. Quien no esté en esta lista entra pero no ve nada.
      </Typography>
      <Paper variant="outlined" sx={{ overflow: 'auto' }}>
        <Table size="small">
          <TableHead><TableRow sx={{ bgcolor: '#eef2e3' }}>
            {['Código', 'Nombre', 'Perfil', 'Alcance', 'Activo', ''].map(h => <TableCell key={h} sx={{ fontWeight: 700 }}>{h}</TableCell>)}
          </TableRow></TableHead>
          <TableBody>
            {filas.map(u => (
              <TableRow key={u.usuario_id} hover sx={{ opacity: u.activo ? 1 : .5 }}>
                <TableCell>{u.usuario_id}{u.bootstrap && <Chip size="small" label="ADMIN_BOOTSTRAP" sx={{ ml: 1 }} title="Entra siempre como administrador por la configuración del servidor" />}</TableCell>
                <TableCell>{u.nombre}</TableCell>
                <TableCell><Chip size="small" label={u.perfil ?? 'sin perfil'} color={u.perfil_id === 'administrador' ? 'primary' : 'default'} /></TableCell>
                <TableCell>{u.perfil_id === 'administrador' ? 'Todo' : alcance(u)}</TableCell>
                <TableCell><Switch size="small" checked={u.activo} disabled={u.usuario_id === yo?.id}
                  onChange={e => guardar({ ...u, activo: e.target.checked }, false)} /></TableCell>
                <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                  <Tooltip title="Ver la aplicación como este usuario (sin reloj)"><span><IconButton size="small" disabled={!u.perfil_id || u.usuario_id === yo?.id}
                    onClick={() => verComo(u.perfil_id!, u.bodegas, u.categorias).catch(e => setMsg('Error: ' + e.message))}><Visibility fontSize="small" /></IconButton></span></Tooltip>
                  <Tooltip title="Editar"><IconButton size="small" onClick={() => setEd(u)}><Edit fontSize="small" /></IconButton></Tooltip>
                  <Tooltip title="Quitar acceso"><span><IconButton size="small" disabled={u.usuario_id === yo?.id} onClick={() => borrar(u)}><DeleteOutline fontSize="small" /></IconButton></span></Tooltip>
                </TableCell>
              </TableRow>))}
            {!filas.length && <TableRow><TableCell colSpan={6} align="center" sx={{ color: 'text.secondary', py: 3 }}>Sin usuarios</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Paper>

      <Dialog open={!!vc} onClose={() => setVc(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Ver como perfil</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2" color="text.secondary">Entras con ese perfil sin pasar por reloj. Arriba verás un aviso con el botón para volver a tu usuario; la sesión de prueba dura 2 horas.</Typography>
            <TextField select size="small" label="Perfil" value={vc?.perfil_id ?? ''} onChange={e => setVc(x => ({ ...x!, perfil_id: e.target.value }))}>
              {perfiles.map(p => <MenuItem key={p.perfil_id} value={p.perfil_id}>{p.nombre}</MenuItem>)}
            </TextField>
            <Autocomplete multiple size="small" options={op.tiendas.map(t => t.id)} value={vc?.bodegas ?? []}
              getOptionLabel={id => { const t = op.tiendas.find(x => x.id === id); return t?.nombre ? `${id} · ${t.nombre}` : id }}
              onChange={(_, v) => setVc(x => ({ ...x!, bodegas: v }))}
              renderInput={p => <TextField {...p} label="Tiendas" placeholder={vc?.bodegas?.length ? '' : 'Todas las tiendas'} />} />
            <Autocomplete multiple size="small" options={op.laboratorios.map(t => t.id)} value={vc?.categorias ?? []}
              getOptionLabel={id => { const t = op.laboratorios.find(x => x.id === id); return t?.nombre ? `${id} · ${t.nombre}` : id }}
              onChange={(_, v) => setVc(x => ({ ...x!, categorias: v }))}
              renderInput={p => <TextField {...p} label="Laboratorios" placeholder={vc?.categorias?.length ? '' : 'Todos los laboratorios'} />} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setVc(null)}>Cancelar</Button>
          <Button variant="contained" disabled={!vc?.perfil_id} onClick={() => verComo(vc!.perfil_id, vc!.bodegas, vc!.categorias).catch(e => setMsg('Error: ' + e.message))}>Entrar</Button>
        </DialogActions>
      </Dialog>
      <Dialog open={!!ed} onClose={() => setEd(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{ed?.nuevo ? 'Agregar usuario' : `Usuario ${ed?.usuario_id}`}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {ed?.nuevo ? (
              <Autocomplete freeSolo options={reloj} getOptionLabel={o => typeof o === 'string' ? o : `${o.id} — ${o.nombre}`}
                inputValue={ed.usuario_id ?? ''} onInputChange={(_, v) => setEd(x => ({ ...x!, usuario_id: v.split(' — ')[0] }))}
                onChange={(_, v) => { if (v && typeof v !== 'string') setEd(x => ({ ...x!, usuario_id: v.id, nombre: v.nombre })) }}
                renderInput={p => <TextField {...p} size="small" label="Código de reloj (el que usa para entrar)"
                  helperText={relojOk ? 'Escribe el código o el nombre para buscarlo en reloj' : 'No pude consultar reloj: escribe el código y el nombre a mano'} />} />
            ) : null}
            <TextField size="small" label="Nombre" value={ed?.nombre ?? ''} onChange={e => setEd(x => ({ ...x!, nombre: e.target.value }))} />
            <TextField select size="small" label="Perfil" value={ed?.perfil_id ?? ''} onChange={e => setEd(x => ({ ...x!, perfil_id: e.target.value }))}
              helperText={perfilSel ? [perfilSel.descripcion, NIVELES[perfilSel.nivel]].filter(Boolean).join(' · ') : ''}>
              {perfiles.map(p => <MenuItem key={p.perfil_id} value={p.perfil_id}>{p.nombre}</MenuItem>)}
            </TextField>
            {esAdminPerfil ? <Typography variant="body2" color="text.secondary">El administrador ve todas las tiendas y laboratorios.</Typography> : <>
              <Autocomplete multiple size="small" options={op.tiendas.map(t => t.id)} value={ed?.bodegas ?? []}
                getOptionLabel={id => { const t = op.tiendas.find(x => x.id === id); return t?.nombre ? `${id} · ${t.nombre}` : id }}
                onChange={(_, v) => setEd(x => ({ ...x!, bodegas: v }))}
                renderInput={p => <TextField {...p} label="Tiendas" placeholder={ed?.bodegas?.length ? '' : 'Todas las tiendas'} helperText="Vacío = todas las tiendas" />} />
              <Autocomplete multiple size="small" options={op.laboratorios.map(t => t.id)} value={ed?.categorias ?? []}
                getOptionLabel={id => { const t = op.laboratorios.find(x => x.id === id); return t?.nombre ? `${id} · ${t.nombre}` : id }}
                onChange={(_, v) => setEd(x => ({ ...x!, categorias: v }))}
                renderInput={p => <TextField {...p} label="Laboratorios" placeholder={ed?.categorias?.length ? '' : 'Todos los laboratorios'} helperText="Vacío = todos los laboratorios" />} />
            </>}
            <FormControlLabel control={<Switch checked={ed?.activo ?? true} onChange={e => setEd(x => ({ ...x!, activo: e.target.checked }))} />} label="Activo" />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEd(null)}>Cancelar</Button>
          <Button variant="contained" disabled={!ed?.usuario_id?.trim() || !ed?.perfil_id} onClick={() => guardar(ed!)}>Guardar</Button>
        </DialogActions>
      </Dialog>
    </Stack>)
}

/* ---------------- Perfiles (matriz de permisos) ---------------- */
function Perfiles({ perfiles, permisos, recargar, setMsg }: { perfiles: Perfil[]; permisos: Perm[]; recargar: () => void; setMsg: (s: string) => void }) {
  const [nuevo, setNuevo] = useState<{ id: string; nombre: string; descripcion: string } | null>(null)
  const guardar = async (p: Perfil, cambio: Partial<Perfil>) => {
    const x = { ...p, ...cambio }
    try {
      await api('/usuarios/perfiles/' + p.perfil_id, { method: 'PUT', body: JSON.stringify({ nombre: x.nombre, descripcion: x.descripcion, nivel: x.nivel, permisos: x.permisos }) })
      setMsg(`Perfil “${x.nombre}” guardado`); recargar()
    } catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const alternar = (p: Perfil, clave: string, on: boolean) =>
    guardar(p, { permisos: on ? [...p.permisos, clave] : p.permisos.filter(c => c !== clave) })
  const borrar = async (p: Perfil) => {
    if (!(await confirmar(`Borrar el perfil “${p.nombre}”`, 'Solo se puede borrar si ningún usuario lo tiene asignado.', { peligro: true, si: 'Sí, borrar' }))) return
    try { await api('/usuarios/perfiles/' + p.perfil_id, { method: 'DELETE' }); setMsg('Perfil borrado'); recargar() } catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const crear = async () => {
    if (!nuevo) return
    try {
      await api('/usuarios/perfiles/' + nuevo.id, { method: 'PUT', body: JSON.stringify({ nombre: nuevo.nombre, descripcion: nuevo.descripcion, nivel: 'lectura', permisos: ['ver_control'] }) })
      setNuevo(null); setMsg('Perfil creado: marca sus funciones en la matriz'); recargar()
    } catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const grupos = [...new Set(permisos.map(p => p.grupo))]
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          Cada columna es un perfil; marca lo que puede hacer. Los cambios se guardan al instante y aplican a todos sus usuarios.
          El <b>nivel</b> define qué puede hacer sobre las tiendas y laboratorios de cada usuario.
        </Typography>
        <Button variant="contained" startIcon={<Add />} onClick={() => setNuevo({ id: '', nombre: '', descripcion: '' })}>Nuevo perfil</Button>
      </Stack>
      <Paper variant="outlined" sx={{ overflow: 'auto' }}>
        <Table size="small" sx={{ minWidth: 700 }}>
          <TableHead><TableRow sx={{ bgcolor: '#eef2e3' }}>
            <TableCell sx={{ fontWeight: 700, minWidth: 280 }}>Función</TableCell>
            {perfiles.map(p => (
              <TableCell key={p.perfil_id} align="center" sx={{ minWidth: 120, verticalAlign: 'top' }}>
                <Tooltip title={p.descripcion || ''}><Box sx={{ fontWeight: 700 }}>{p.nombre}</Box></Tooltip>
                <Box sx={{ fontSize: 11, color: 'text.secondary' }}>{p.usuarios} usuario(s)</Box>
                {!p.sistema && <IconButton size="small" onClick={() => borrar(p)} title="Borrar perfil"><DeleteOutline fontSize="inherit" /></IconButton>}
              </TableCell>))}
          </TableRow></TableHead>
          <TableBody>
            <TableRow>
              <TableCell><b>Nivel sobre sus tiendas</b><Box sx={{ fontSize: 12, color: 'text.secondary' }}>Lectura · Edición · Aprobación</Box></TableCell>
              {perfiles.map(p => (
                <TableCell key={p.perfil_id} align="center">
                  <TextField select size="small" value={p.nivel} disabled={p.permisos.includes('admin')} onChange={e => guardar(p, { nivel: e.target.value })} sx={{ minWidth: 112 }}>
                    {Object.entries(NIVELES).map(([k, l]) => <MenuItem key={k} value={k} title={l}>{k[0].toUpperCase() + k.slice(1)}</MenuItem>)}
                  </TextField></TableCell>))}
            </TableRow>
            {grupos.map(g => [
              <TableRow key={'g' + g}><TableCell colSpan={perfiles.length + 1} sx={{ bgcolor: '#f6f7f1', fontWeight: 700, fontSize: 12, letterSpacing: .5, textTransform: 'uppercase', color: 'text.secondary' }}>{g}</TableCell></TableRow>,
              ...permisos.filter(x => x.grupo === g).map(x => (
                <TableRow key={x.clave} hover>
                  <TableCell>{x.label}</TableCell>
                  {perfiles.map(p => {
                    const adm = p.permisos.includes('admin')
                    return <TableCell key={p.perfil_id} align="center" padding="checkbox">
                      <Checkbox size="small" checked={adm || p.permisos.includes(x.clave)} disabled={adm} onChange={e => alternar(p, x.clave, e.target.checked)} /></TableCell>
                  })}
                </TableRow>))])}
          </TableBody>
        </Table>
      </Paper>
      <Dialog open={!!nuevo} onClose={() => setNuevo(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Nuevo perfil</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ mt: 1 }}>
          <TextField size="small" label="Nombre" value={nuevo?.nombre ?? ''} onChange={e => setNuevo(x => ({ ...x!, nombre: e.target.value,
            id: x!.id && x!.id !== slug(x!.nombre) ? x!.id : slug(e.target.value) }))} />
          <TextField size="small" label="Id (minúsculas, sin espacios)" value={nuevo?.id ?? ''} onChange={e => setNuevo(x => ({ ...x!, id: e.target.value }))} />
          <TextField size="small" label="Descripción" value={nuevo?.descripcion ?? ''} onChange={e => setNuevo(x => ({ ...x!, descripcion: e.target.value }))} />
        </Stack></DialogContent>
        <DialogActions><Button onClick={() => setNuevo(null)}>Cancelar</Button>
          <Button variant="contained" disabled={!nuevo?.id || !nuevo?.nombre.trim()} onClick={crear}>Crear</Button></DialogActions>
      </Dialog>
    </Stack>)
}
const slug = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 40)

export default function UsuariosPage() {
  const [tab, setTab] = useState(0)
  const [perfiles, setPerfiles] = useState<Perfil[]>([])
  const [permisos, setPermisos] = useState<Perm[]>([])
  const [msg, setMsg] = useState('')
  const cargar = () => api('/usuarios/perfiles').then(setPerfiles).catch(e => setMsg('Error: ' + e.message))
  useEffect(() => { cargar(); api('/usuarios/catalogo').then(x => setPermisos(x.permisos)) }, [])
  return (
    <Box sx={{ maxWidth: 1100, mx: 'auto', display: 'grid', gap: 1.5 }}>
      <Typography variant="h6" sx={{ fontWeight: 700 }}>Usuarios y perfiles</Typography>
      <Tabs value={tab} onChange={(_, v) => { setTab(v); cargar() }}><Tab label="Usuarios" /><Tab label="Perfiles y permisos" /></Tabs>
      {tab === 0 ? <Usuarios perfiles={perfiles} setMsg={setMsg} /> : <Perfiles perfiles={perfiles} permisos={permisos} recargar={cargar} setMsg={setMsg} />}
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
