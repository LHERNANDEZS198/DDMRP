let token = localStorage.getItem('token') || ''
export const setToken = (t: string) => { token = t; localStorage.setItem('token', t) }
export const hasToken = () => !!token
export const getUser = () => localStorage.getItem('user') || ''
export const logout = () => { ['token', 'user', 'token_admin', 'user_admin'].forEach(k => localStorage.removeItem(k)); location.reload() }

/** Modo "ver como perfil": se guarda el token del administrador y se entra con uno temporal del perfil elegido (sin reloj). */
export const enPrueba = () => !!localStorage.getItem('token_admin')
export async function verComo(perfil_id: string, bodegas: string[], categorias: string[], empresas: string[] = []) {
  const r = await api('/usuarios/ver-como', { method: 'POST', body: JSON.stringify({ perfil_id, bodegas, categorias, empresas }) })
  if (!enPrueba()) { localStorage.setItem('token_admin', token); localStorage.setItem('user_admin', getUser()) }
  setToken(r.access_token); localStorage.setItem('user', r.usuario); location.href = '/'
}
export async function volverDePrueba() {
  const ta = localStorage.getItem('token_admin') || ''
  try { await api('/auth/salir-prueba', { method: 'POST' }) } catch { /* el token temporal pudo vencer: igual se vuelve */ }
  setToken(ta); localStorage.setItem('user', localStorage.getItem('user_admin') || '')
  localStorage.removeItem('token_admin'); localStorage.removeItem('user_admin'); location.href = '/usuarios'
}

/** Mensaje de error de una respuesta: lee el cuerpo UNA sola vez y saca `detail` si es JSON de FastAPI. */
async function errorDe(r: Response): Promise<string> {
  const t = await r.text()
  try { const j = JSON.parse(t); return typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j) } catch { return t || `Error ${r.status}` }
}

/** «Ver solo CEDI» de los Informes: se guarda en el navegador y se agrega como ?solo_cedi=true a las consultas de Control, Alertas, Salud y Clasificación. */
const LS_CEDI = 'ddmrp_solo_cedi'
export const soloCediOn = () => { try { return localStorage.getItem(LS_CEDI) === '1' } catch { return false } }
export const setSoloCedi = (v: boolean) => { try { localStorage.setItem(LS_CEDI, v ? '1' : '0') } catch { /* sin almacenamiento */ } }
const RUTAS_INFORMES = /^\/(control|alertas|salud|clasificacion)(\/|\?|$)/
const conModo = (path: string) =>
  soloCediOn() && RUTAS_INFORMES.test(path) && !/[?&]solo_cedi=/.test(path) ? path + (path.includes('?') ? '&' : '?') + 'solo_cedi=true' : path

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch('/api' + conModo(path), {
    ...init,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(init.headers || {}) },
  })
  if (r.status === 401) { localStorage.removeItem('token'); location.reload() }
  if (!r.ok) throw new Error(await errorDe(r))
  return r.json()
}

/** GET de una lista que el servidor puede recortar: devuelve las filas y el total real (cabecera X-Total-Rows). */
export async function apiLista<T = any>(path: string): Promise<{ datos: T[]; total: number }> {
  const r = await fetch('/api' + conModo(path), { headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } })
  if (r.status === 401) { localStorage.removeItem('token'); location.reload() }
  if (!r.ok) throw new Error(await errorDe(r))
  const datos = await r.json()
  return { datos, total: Number(r.headers.get('x-total-rows') ?? datos.length) }
}

export async function login(usuario: string, clave: string) {
  const r = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: usuario, password: clave }),
  })
  if (r.status === 401) throw new Error('Credenciales invalidas')
  if (!r.ok) throw new Error(await errorDe(r))
  setToken((await r.json()).access_token); localStorage.setItem('user', usuario)
}

/** POST que devuelve un archivo: lo descarga en el navegador. Devuelve el nombre y los avisos del servidor. */
export async function descargar(path: string, body: unknown) {
  const r = await fetch('/api' + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  })
  if (r.status === 401) { localStorage.removeItem('token'); location.reload() }
  if (!r.ok) throw new Error(await errorDe(r))
  const nombre = /filename="([^"]+)"/.exec(r.headers.get('content-disposition') ?? '')?.[1] ?? 'archivo.xlsx'
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a'); a.href = url; a.download = nombre; a.click(); URL.revokeObjectURL(url)
  return { nombre, derivado: r.headers.get('x-bodegas-co-derivado'), bajoMinimo: r.headers.get('x-bodegas-bajo-minimo') }
}

function bajarBlob(blob: Blob, nombre: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = nombre; a.click(); URL.revokeObjectURL(url)
}

/** GET que devuelve un archivo (p.ej. el Excel de un maestro). */
export async function bajar(path: string, nombre: string) {
  const r = await fetch('/api' + conModo(path), { headers: { Authorization: `Bearer ${token}` } })
  if (r.status === 401) { localStorage.removeItem('token'); location.reload() }
  if (!r.ok) throw new Error(await errorDe(r))
  bajarBlob(await r.blob(), nombre)
}

/** POST multipart con un archivo (Excel / CSV). */
export async function subir<T = any>(path: string, archivo: File): Promise<T> {
  const fd = new FormData(); fd.append('archivo', archivo)
  const r = await fetch('/api' + path, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd })
  if (r.status === 401) { localStorage.removeItem('token'); location.reload() }
  if (!r.ok) throw new Error(await errorDe(r))
  return r.json()
}

const espera = (ms: number) => new Promise(r => setTimeout(r, ms))
const texto = (e: any) => { const m: string = e.mensaje || 'Trabajando…'; return /…\s*$/.test(m) ? m : m + '…' }

/** Ejecuta una tarea larga (la peticion espera la respuesta) y mientras tanto muestra lo que el servidor va haciendo. */
export async function conProgreso<T>(setMsg: (s: string) => void, fn: () => Promise<T>): Promise<T> {
  let vivo = true
  const t = setInterval(async () => {
    try { const e = await api('/admin/progreso'); if (vivo && e.estado === 'corriendo') setMsg(texto(e)) } catch { /* sin progreso: se queda el mensaje inicial */ }
  }, 2000)
  try { return await fn() } finally { vivo = false; clearInterval(t) }
}

/** Para tareas que el servidor corre en segundo plano (ETL + motor): sigue el progreso hasta que termine. */
export async function seguirTarea(setMsg: (s: string) => void, inicioPrevio: number | null): Promise<{ estado: string; mensaje: string }> {
  let visto = false
  for (let i = 0; i < 2000; i++) {
    await espera(2000)
    try {
      const e = await api('/admin/progreso')
      if (e.inicio !== inicioPrevio) visto = true
      if (visto && e.estado === 'corriendo') setMsg(texto(e))
      else if (visto) return e
      else if (i > 10) return { estado: 'ok', mensaje: 'Lanzado; revisa Alertas en unos minutos' }
    } catch { /* reintenta */ }
  }
  return { estado: 'ok', mensaje: 'Sigue corriendo en segundo plano' }
}
