import { Component, ReactNode } from 'react'
import { Alert, Button } from '@mui/material'

/** Si una pantalla falla al dibujarse, muestra un aviso en vez de dejar la página en blanco. */
export default class Errores extends Component<{ children: ReactNode; clave?: string }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  componentDidUpdate(prev: { clave?: string }) { if (prev.clave !== this.props.clave && this.state.error) this.setState({ error: null }) }
  componentDidCatch(e: Error) { console.error('Error de pantalla:', e) }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <Alert severity="error" sx={{ m: 2 }} action={<Button color="inherit" size="small" onClick={() => this.setState({ error: null })}>Reintentar</Button>}>
        Esta pantalla tuvo un error al dibujarse ({this.state.error.message}). Pulsa Reintentar o recarga la página; si se repite, avísame con lo que estabas haciendo.
      </Alert>)
  }
}
