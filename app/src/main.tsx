import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { DemoEntry } from './features/demo/DemoEntry'
import { bootOnce } from './session'
import './styles/index.css'

const root = document.getElementById('root')
if (!root) throw new Error('Chybí kořenový prvek #root.')

createRoot(root).render(
  <StrictMode>
    <DemoEntry boot={bootOnce()} />
  </StrictMode>,
)
