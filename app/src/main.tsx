import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { LoginBoundary } from './auth/LoginBoundary'
import './styles/index.css'

const root = document.getElementById('root')
if (!root) throw new Error('Chybí kořenový prvek #root.')

createRoot(root).render(
  <StrictMode>
    <LoginBoundary />
  </StrictMode>,
)
