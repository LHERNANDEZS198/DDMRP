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
