import Swal from 'sweetalert2'
import { VERDE } from './theme'

/** Diálogos de confirmación (SweetAlert2) en lugar de window.confirm: mismo color de la app, botón de cancelar a la izquierda y el foco en
 *  "Cancelar" para que un Enter distraído no borre ni envíe nada. Devuelve true si la persona confirma. */
const base = Swal.mixin({ confirmButtonColor: VERDE, cancelButtonColor: '#757575', reverseButtons: true, focusCancel: true, showCancelButton: true, cancelButtonText: 'Cancelar' })

export async function confirmar(titulo: string, texto = '', o: { si?: string; peligro?: boolean; html?: string } = {}): Promise<boolean> {
  const r = await base.fire({ title: titulo, text: o.html ? undefined : texto, html: o.html, icon: o.peligro ? 'warning' : 'question',
    confirmButtonText: o.si ?? 'Continuar', ...(o.peligro ? { confirmButtonColor: '#c62828' } : {}) })
  return r.isConfirmed
}

/** Confirmación fuerte para lo que no se puede deshacer: hay que escribir la palabra pedida (ej. el nombre del maestro). */
export async function confirmarEscribiendo(titulo: string, texto: string, palabra: string, si = 'Eliminar'): Promise<boolean> {
  const r = await base.fire({ title: titulo, html: texto, icon: 'warning', input: 'text', inputPlaceholder: `Escribe ${palabra} para confirmar`,
    confirmButtonText: si, confirmButtonColor: '#c62828',
    preConfirm: (v: string) => { if ((v ?? '').trim().toLowerCase() !== palabra.toLowerCase()) { Swal.showValidationMessage(`Escribe exactamente: ${palabra}`); return false } return true } })
  return r.isConfirmed
}

export const esc = (t: string) => t.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string))
