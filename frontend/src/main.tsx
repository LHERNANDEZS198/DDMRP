import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { CssBaseline, ThemeProvider } from '@mui/material'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-quartz.css'
import './grid.css'
import theme from './theme'
import App from './App'
createRoot(document.getElementById('root')!).render(
  <ThemeProvider theme={theme}><CssBaseline /><BrowserRouter><App /></BrowserRouter></ThemeProvider>)
