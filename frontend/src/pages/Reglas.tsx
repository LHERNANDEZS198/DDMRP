import { useEffect, useState } from 'react'
import { api } from '../api'

type Regla = { clave: string; titulo: string; ayuda: string; opciones: { valor: number; label: string }[] | null; valor: number | null }

export default function Reglas() {
  const [reglas, setReglas] = useState<Regla[]>([])
  const [msg, setMsg] = useState('')
  const cargar = () => api('/reglas').then(setReglas).catch(e => setMsg('Error: ' + e.message))
  useEffect(() => { cargar() }, [])

  const guardar = async (r: Regla, valor: number) => {
    try {
      const x = await api('/reglas/' + r.clave, { method: 'PUT', body: JSON.stringify({ valor }) })
      setMsg(`${r.titulo}: guardado. ${x.aviso}`); cargar()
    } catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const recalcular = async () => {
    setMsg('Recalculando...')
    try { const x = await api('/admin/correr-motor', { method: 'POST' }); setMsg(`Listo: ${x.filas} combinaciones calculadas`) }
    catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const pipeline = async () => {
    setMsg('Lanzando ETL + motor (tarda unos minutos)...')
    try { await api('/admin/correr-pipeline', { method: 'POST' }); setMsg('Lanzado en segundo plano. Revisa Alertas en unos minutos.') }
    catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const grupos: [string, string[]][] = [
    ['Decision de pedido', ['regla_disparo', 'regla_objetivo', 'regla_redondeo', 'cantidad_minima']],
    ['Que entra al flujo neto y a lo sugerido', ['incluir_transito', 'restar_demanda_calificada', 'sumar_vectorizacion']],
    ['Parametros del modelo (hoja Modelo)', ['meses_historia', 'meses_adu', 'mult_cota_max_promo', 'mult_cota_min_promo', 'adu_bajo_min', 'adu_bajo_max']],
  ]
  return (
    <div style={{ maxWidth: 820, overflow: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>Reglas de pedido</h3>
        <button onClick={recalcular}>Recalcular ahora (solo motor)</button>
        <button onClick={pipeline}>Correr ETL + motor completo</button>
        <small>{msg}</small>
      </div>
      <p><small>Los cambios se aplican en la siguiente corrida del motor (cada noche, o con “Recalcular ahora”).
        Flujo neto = inventario + transito − demanda calificada.</small></p>
      {grupos.map(([titulo, claves]) => (
        <fieldset key={titulo} style={{ margin: '0 0 16px', padding: 12 }}>
          <legend><b>{titulo}</b></legend>
          {claves.map(k => reglas.find(r => r.clave === k)).filter(Boolean).map(r => r!).map(r => (
            <div key={r.clave} style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 8, alignItems: 'center', padding: '6px 0' }}>
              <div><div>{r.titulo}</div><small style={{ color: '#666' }}>{r.ayuda}</small></div>
              {r.opciones
                ? <select value={r.valor ?? ''} onChange={e => guardar(r, Number(e.target.value))}>
                    {r.opciones.map(o => <option key={o.valor} value={o.valor}>{o.label}</option>)}
                  </select>
                : <input type="number" step="any" min={0} style={{ width: 120 }} defaultValue={r.valor ?? 0} key={r.valor}
                    onBlur={e => { const v = Number(e.target.value); if (v !== r.valor) guardar(r, v) }} />}
            </div>))}
        </fieldset>))}
    </div>)
}
