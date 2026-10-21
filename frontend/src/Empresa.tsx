import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from 'react'
import { useYo } from './Yo'

/** Empresa con la que se trabaja en toda la aplicación (05 Funat, 21 Stores o '*' = ambas). Se elige en la barra y se conserva hasta que se cambie. */
export const NOMBRE_EMPRESA: Record<string, string> = { '05': 'Funat', '21': 'Stores' }
const LS = 'ddmrp_empresa'

type Ctx = { empresa: string; setEmpresa: (e: string) => void; opciones: string[]; lista: string[]; una: string }
const EmpresaCtx = createContext<Ctx>({ empresa: '05', setEmpresa: () => {}, opciones: ['05'], lista: ['05'], una: '05' })

export function EmpresaProvider({ children }: { children: ReactNode }) {
  const { yo } = useYo()
  const permitidas = (yo?.empresas?.length ? yo.empresas : ['05', '21']) as string[]
  const opciones = permitidas.length > 1 ? [...permitidas, '*'] : permitidas
  const [empresa, setE] = useState<string>(() => { try { return localStorage.getItem(LS) || '05' } catch { return '05' } })
  // la guardada puede no estar permitida para este usuario: por defecto Funat, o la primera que tenga
  const valida = opciones.includes(empresa) ? empresa : (opciones.includes('05') ? '05' : opciones[0])
  useEffect(() => { if (valida !== empresa) setE(valida) }, [valida, empresa])
  const setEmpresa = (e: string) => { setE(e); try { localStorage.setItem(LS, e) } catch { /* sin almacenamiento */ } }
  const v = useMemo<Ctx>(() => ({ empresa: valida, setEmpresa, opciones, lista: valida === '*' ? [] : [valida], una: valida === '*' ? '' : valida }), [valida, opciones.join()])
  return <EmpresaCtx.Provider value={v}>{children}</EmpresaCtx.Provider>
}

/** `lista`: [] cuando son ambas (sin filtro) o [empresa]; `una`: la empresa o '' si son ambas. */
export const useEmpresa = () => useContext(EmpresaCtx)
