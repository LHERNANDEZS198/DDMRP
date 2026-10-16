let token = localStorage.getItem('token') || ''
export const setToken = (t: string) => { token = t; localStorage.setItem('token', t) }
export const hasToken = () => !!token
export const getUser = () => localStorage.getItem('user') || ''
export const logout = () => { localStorage.removeItem('token'); localStorage.removeItem('user'); location.reload() }

/** Mensaje de error de una respuesta: lee el cuerpo UNA sola vez y saca `detail` si es JSON de FastAPI. */
async function errorDe(r: Response): Promise<string> {
  const t = await r.text()
  try { const j = JSON.parse(t); return typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j) } catch { return t || `Error ${r.status}` }
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch('/api' + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(init.headers || {}) },
  })
  if (r.status === 401) { localStorage.removeItem('token'); location.reload() }
  if (!r.ok) throw new Error(await errorDe(r))
  return r.json()
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
  return { nombre, derivado: r.headers.get('x-bodegas-co-derivado') }
}

function bajarBlob(blob: Blob, nombre: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = nombre; a.click(); URL.revokeObjectURL(url)
}

/** GET que devuelve un archivo (p.ej. el Excel de un maestro). */
export async function bajar(path: string, nombre: string) {
  const r = await fetch('/api' + path, { headers: { Authorization: `Bearer ${token}` } })
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
