import { createTheme } from '@mui/material/styles'
export const VERDE = '#6e8a37'
export default createTheme({
  palette: { primary: { main: VERDE, contrastText: '#fff' }, background: { default: '#f5f7f0' } },
  typography: { fontFamily: "'Basic Sans', Arimo, Nunito, system-ui, sans-serif" },
  shape: { borderRadius: 8 },
  components: { MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { textTransform: 'none' } } } },
})
