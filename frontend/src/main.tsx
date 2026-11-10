import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './app.css'
import App from './App.tsx'
import { importSellerLink } from './myShops'

importSellerLink() // before the first render, so the page's first request has the token

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
