import { createContext, useContext } from 'react'

export type Yo = { id: string; nombre: string; funciones: string[]; es_admin: boolean; empresas?: string[] }
export const YoCtx = createContext<Yo | null>(null)

/** Quién es el usuario y qué funciones tiene su perfil. `puede('a','b')` = tiene alguna de las dos. */
export function useYo() {
  const yo = useContext(YoCtx)
  return { yo, puede: (...claves: string[]) => !!yo && claves.some(c => yo.funciones.includes(c)) }
}
