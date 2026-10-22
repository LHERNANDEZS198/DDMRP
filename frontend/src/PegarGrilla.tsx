import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Box, Button, Chip, Paper, Stack, Tooltip, Typography } from '@mui/material'
import Check from '@mui/icons-material/Check'
import Close from '@mui/icons-material/Close'

/** Grilla para pegar desde Excel (Ctrl+V): se parece a una hoja. Se puede escribir celda por celda, moverse con flechas/Tab/Enter y pegar
 *  bloques de cualquier tamaño (con o sin fila de encabezados). Solo dibuja las filas visibles, así aguanta decenas de miles de filas. */
export type ColPegar = { key: string; titulo: string; obligatoria?: boolean; ayuda?: string }

const ALTO = 28          // alto de cada fila (px)
const VISIBLES = 12      // filas que se ven sin desplazarse
const ANCHO_NUM = 52
const MIN_COL = 140

const norm = (s: string) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')

/** Texto del portapapeles de Excel: columnas con tab, filas con salto de línea; las celdas con saltos o comillas vienen entre comillas. */
export function leerPortapapeles(txt: string): string[][] {
  const sep = txt.includes('\t') ? '\t' : txt.includes(';') && !txt.includes(',') ? ';' : '\t'
  const filas: string[][] = []
  let fila: string[] = [], celda = '', comillas = false
  for (let i = 0; i < txt.length; i++) {
    const ch = txt[i]
    if (comillas) {
      if (ch === '"') { if (txt[i + 1] === '"') { celda += '"'; i++ } else comillas = false } else celda += ch
    } else if (ch === '"' && celda === '') comillas = true
    else if (ch === sep) { fila.push(celda); celda = '' }
    else if (ch === '\n') { fila.push(celda); filas.push(fila); fila = []; celda = '' }
    else if (ch !== '\r') celda += ch
  }
  if (celda !== '' || fila.length) { fila.push(celda); filas.push(fila) }
  return filas
}

type Props = {
  titulo: string
  ayuda?: string
  columnas: ColPegar[]
  ocupado?: boolean
  onFinalizar: (filas: Record<string, string>[]) => void | Promise<void>
  onCancelar: () => void
}

export default function PegarGrilla({ titulo, ayuda, columnas, ocupado, onFinalizar, onCancelar }: Props) {
  const n = columnas.length
  const [filas, setFilas] = useState<string[][]>([])
  const [sel, setSel] = useState({ r: 0, c: 0 })
  const [edit, setEdit] = useState<string | null>(null)
  const [scroll, setScroll] = useState(0)
  const [aviso, setAviso] = useState('')
  const caja = useRef<HTMLDivElement>(null)
  const total = Math.max(filas.length + 1, VISIBLES)   // siempre sobra una fila vacía para seguir escribiendo
  const plantilla = `${ANCHO_NUM}px repeat(${n}, minmax(${MIN_COL}px, 1fr))`
  const get = (r: number, c: number) => filas[r]?.[c] ?? ''
  const vacia = (f?: string[]) => !f || f.every(x => !x?.trim())

  const poner = (r: number, c: number, v: string) => setFilas(fs => {
    const out = fs.slice(); while (out.length <= r) out.push(Array(n).fill(''))
    const fila = out[r].slice(); fila[c] = v; out[r] = fila; return out
  })

  const revisar = useMemo(() => {
    const incompletas = new Set<number>(); let conDatos = 0
    filas.forEach((f, r) => {
      if (vacia(f)) return
      conDatos++
      if (columnas.some((col, c) => col.obligatoria && !f[c]?.trim())) incompletas.add(r)
    })
    return { incompletas, conDatos }
  }, [filas, columnas])

  const confirmarEdicion = () => { if (edit !== null) { poner(sel.r, sel.c, edit); setEdit(null) } }
  const ir = (r: number, c: number) => {
    const rr = Math.min(Math.max(r, 0), total - 1), cc = Math.min(Math.max(c, 0), n - 1)
    setSel({ r: rr, c: cc })
  }

  // que la celda elegida siempre quede a la vista
  useEffect(() => {
    const el = caja.current; if (!el) return
    const arriba = sel.r * ALTO, abajo = (sel.r + 1) * ALTO, h = el.clientHeight - ALTO   // el encabezado ocupa una fila
    if (arriba < el.scrollTop) el.scrollTop = arriba
    else if (abajo > el.scrollTop + h) el.scrollTop = abajo - h
  }, [sel.r])

  const pegar = (e: React.ClipboardEvent) => {
    const texto = e.clipboardData.getData('text/plain')
    if (edit !== null && !/[\t\n]/.test(texto)) return        // pegar un valor suelto dentro de una celda en edición: lo normal
    e.preventDefault()
    let datos = leerPortapapeles(texto)
    if (!datos.length) return
    let r0 = filas.some(f => !vacia(f)) ? sel.r : 0, c0 = sel.c, mapa: number[] | null = null   // grilla vacía: se pega desde la primera fila
    // si lo pegado trae los encabezados de la hoja (en cualquier orden), se acomoda por nombre y no por posición
    const conocidas = new Map<string, number>()
    columnas.forEach((col, i) => { conocidas.set(norm(col.key), i); conocidas.set(norm(col.titulo.replace('*', '')), i) })
    const idx = datos[0].map(h => conocidas.get(norm(h)) ?? -1)
    const aciertos = idx.filter(i => i >= 0).length
    if (aciertos > 0 && aciertos >= Math.ceil(datos[0].length / 2) && idx.filter((v, i) => v >= 0 && idx.indexOf(v) === i).length === aciertos) {
      mapa = idx; datos = datos.slice(1); c0 = 0
    }
    if (!datos.length) { setAviso('Solo pegaste los encabezados: pega también las filas de datos'); return }
    let recortadas = 0
    const out = filas.slice()
    datos.forEach((fila, i) => {
      const r = r0 + i
      while (out.length <= r) out.push(Array(n).fill(''))
      const destino = out[r].slice()
      fila.forEach((v, j) => {
        const c = mapa ? mapa[j] : c0 + j
        if (c == null || c < 0) return
        if (c >= n) { recortadas++; return }
        destino[c] = v.trim()
      })
      out[r] = destino
    })
    setFilas(out)
    setEdit(null)
    setAviso(`Pegadas ${datos.length.toLocaleString('es-CO')} filas${mapa ? ' (acomodadas por el nombre de las columnas)' : ''}` + (recortadas ? `; se ignoraron ${recortadas} celdas de columnas que este maestro no tiene` : ''))
    setSel({ r: r0 + datos.length, c: mapa ? 0 : c0 })
  }

  const teclas = (e: React.KeyboardEvent) => {
    if (edit !== null) return          // la celda en edición maneja sus propias teclas
    const { r, c } = sel
    if (e.ctrlKey || e.metaKey) return  // Ctrl+V lo atiende onPaste
    switch (e.key) {
      case 'ArrowDown': e.preventDefault(); ir(r + 1, c); break
      case 'ArrowUp': e.preventDefault(); ir(r - 1, c); break
      case 'ArrowLeft': e.preventDefault(); ir(r, c - 1); break
      case 'ArrowRight': e.preventDefault(); ir(r, c + 1); break
      case 'Tab': e.preventDefault(); if (e.shiftKey) { c > 0 ? ir(r, c - 1) : ir(r - 1, n - 1) } else { c < n - 1 ? ir(r, c + 1) : ir(r + 1, 0) } break
      case 'Enter': case 'F2': e.preventDefault(); setEdit(get(r, c)); break
      case 'Delete': case 'Backspace': e.preventDefault(); poner(r, c, ''); break
      case 'PageDown': e.preventDefault(); ir(r + VISIBLES, c); break
      case 'PageUp': e.preventDefault(); ir(r - VISIBLES, c); break
      default: if (e.key.length === 1 && !e.altKey) { e.preventDefault(); setEdit(e.key) }
    }
  }

  const teclasEdicion = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const { r, c } = sel
    if (e.key === 'Escape') { e.preventDefault(); setEdit(null); caja.current?.focus() }
    else if (e.key === 'Enter') { e.preventDefault(); poner(r, c, edit ?? ''); setEdit(null); ir(r + 1, c); caja.current?.focus() }
    else if (e.key === 'Tab') { e.preventDefault(); poner(r, c, edit ?? ''); setEdit(null); c < n - 1 ? ir(r, c + 1) : ir(r + 1, 0); caja.current?.focus() }
  }

  const limpiar = () => { setFilas([]); setSel({ r: 0, c: 0 }); setEdit(null); setAviso(''); caja.current?.focus() }
  const finalizar = () => {
    const salida = filas.filter(f => !vacia(f)).map(f => Object.fromEntries(columnas.map((col, c) => [col.key, (f[c] ?? '').trim()])))
    return onFinalizar(salida)
  }

  const desde = Math.max(0, Math.floor(scroll / ALTO) - 3), hasta = Math.min(total, desde + VISIBLES + 8)
  const obligatorias = columnas.filter(c => c.obligatoria).map(c => c.titulo)
  const celda = { borderRight: '1px solid', borderBottom: '1px solid', borderColor: 'divider', px: 1, display: 'flex', alignItems: 'center', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis', fontSize: 13, position: 'relative' as const }

  return (
    <Paper variant="outlined" sx={{ borderTop: '3px solid', borderTopColor: 'primary.main', p: 2, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5 }}>
      <Typography variant="subtitle1" sx={{ textTransform: 'uppercase', fontWeight: 400 }}>Cargar datos a <b>{titulo}</b></Typography>
      <Alert severity="info" icon={false} sx={{ py: 0.25, fontStyle: 'italic' }}>
        Copia las celdas directamente de Excel y pégalas aquí con <b>Ctrl+V</b> (puedes incluir la fila de encabezados o no). También puedes escribir celda por celda.
        {obligatorias.length ? <> Obligatorias: <b>{obligatorias.join(', ')}</b>.</> : null}
        {ayuda ? <> {ayuda}</> : null}
      </Alert>
      <Box ref={caja} data-pegar="1" tabIndex={0} onKeyDown={teclas} onPaste={pegar} onScroll={e => setScroll((e.target as HTMLElement).scrollTop)}
        sx={{ height: (VISIBLES + 1) * ALTO + 2, overflow: 'auto', border: '1px solid', borderColor: 'primary.main', outline: 'none', bgcolor: 'background.paper', '&:focus-visible': { boxShadow: 3 } }}>
        <Box sx={{ minWidth: ANCHO_NUM + n * MIN_COL }}>
          <Box sx={{ display: 'grid', gridTemplateColumns: plantilla, position: 'sticky', top: 0, zIndex: 3, height: ALTO, bgcolor: 'primary.main', color: '#fff' }}>
            <Box sx={{ ...celda, borderColor: 'rgba(255,255,255,.25)' }} />
            {columnas.map(col => (
              <Tooltip key={col.key} title={col.ayuda ?? ''} disableHoverListener={!col.ayuda}>
                <Box sx={{ ...celda, borderColor: 'rgba(255,255,255,.25)', justifyContent: 'center', fontWeight: 700, fontSize: 12, textTransform: 'uppercase' }}>{col.titulo}{col.obligatoria ? ' *' : ''}</Box>
              </Tooltip>))}
          </Box>
          <Box sx={{ position: 'relative', height: total * ALTO }}>
            {Array.from({ length: hasta - desde }, (_, k) => desde + k).map(r => {
              const fila = filas[r], malaFila = revisar.incompletas.has(r)
              return (
                <Box key={r} sx={{ display: 'grid', gridTemplateColumns: plantilla, position: 'absolute', top: r * ALTO, left: 0, right: 0, height: ALTO }}>
                  <Box sx={{ ...celda, justifyContent: 'center', bgcolor: 'primary.main', color: '#fff', fontWeight: 700, borderColor: 'rgba(255,255,255,.25)' }}>{r + 1}</Box>
                  {columnas.map((col, c) => {
                    const activa = sel.r === r && sel.c === c
                    const falta = malaFila && col.obligatoria && !fila?.[c]?.trim()
                    return (
                      <Box key={col.key} onMouseDown={() => { confirmarEdicion(); setSel({ r, c }); caja.current?.focus() }}
                        onDoubleClick={() => setEdit(get(r, c))}
                        sx={{ ...celda, bgcolor: falta ? '#ffebee' : undefined, outline: activa ? '2px solid' : 'none', outlineColor: 'primary.main', outlineOffset: -2, zIndex: activa ? 1 : 0, cursor: 'cell' }}>
                        {activa && edit !== null
                          ? <input autoFocus value={edit} onChange={e => setEdit(e.target.value)} onKeyDown={teclasEdicion} onBlur={confirmarEdicion}
                              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', border: 0, outline: 0, padding: '0 8px', font: 'inherit', boxSizing: 'border-box' }} />
                          : get(r, c)}
                      </Box>)
                  })}
                </Box>)
            })}
          </Box>
        </Box>
      </Box>
      <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
        <Button startIcon={<Close />} onClick={onCancelar} disabled={ocupado}>Cancelar</Button>
        <Button onClick={limpiar} disabled={ocupado || !filas.length}>Limpiar</Button>
        <Chip size="small" label={`${revisar.conDatos.toLocaleString('es-CO')} ${revisar.conDatos === 1 ? 'fila' : 'filas'} con datos`} />
        {revisar.incompletas.size > 0 && <Chip size="small" color="error" label={`${revisar.incompletas.size.toLocaleString('es-CO')} incompletas (celdas rojas)`} />}
        {aviso && <Typography variant="caption" color="text.secondary">{aviso}</Typography>}
        <Box sx={{ flex: 1 }} />
        <Button variant="contained" color="success" endIcon={<Check />} onClick={finalizar} disabled={ocupado || !revisar.conDatos || revisar.incompletas.size > 0}>
          {ocupado ? 'Cargando…' : `Finalizar${revisar.conDatos ? ` (${revisar.conDatos.toLocaleString('es-CO')})` : ''}`}
        </Button>
      </Stack>
    </Paper>)
}
