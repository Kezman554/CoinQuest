import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// DESIGN.md's two typefaces, bundled rather than fetched: Lilita One for
// display, Nunito at the three weights the design uses and no others.
import '@fontsource/lilita-one/400.css'
import '@fontsource/nunito/600.css'
import '@fontsource/nunito/700.css'
import '@fontsource/nunito/800.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
