let token = localStorage.getItem('token') || ''
export const setToken = (t: string) => { token = t; localStorage.setItem('token', t) }
export const hasToken = () => !!token

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch('/api' + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(init.headers || {}) },
  })
  if (r.status === 401) { localStorage.removeItem('token'); location.reload() }
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function login(usuario: string, clave: string) {
  const r = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: usuario, password: clave }),
  })
  if (!r.ok) throw new Error('Credenciales invalidas')
  setToken((await r.json()).access_token)
}

/** POST que devuelve un archivo: lo descarga en el navegador. Devuelve el nombre y los avisos del servidor. */
export async function descargar(path: string, body: unknown) {
  const r = await fetch('/api' + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  })
  if (r.status === 401) { localStorage.removeItem('token'); location.reload() }
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? (await r.text()))
  const nombre = /filename="([^"]+)"/.exec(r.headers.get('content-disposition') ?? '')?.[1] ?? 'archivo.xlsx'
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a'); a.href = url; a.download = nombre; a.click(); URL.revokeObjectURL(url)
  return { nombre, derivado: r.headers.get('x-bodegas-co-derivado') }
}
