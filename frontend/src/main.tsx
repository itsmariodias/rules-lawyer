import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
/* The book's three faces, stood in for and bundled rather than fetched:
   Cabin for headings (Gill Sans), Caladea for reading text (Cambria),
   Alegreya Sans for the chrome (Optima). Imported above the stylesheet so
   our own rules win the cascade. */
import '@fontsource/cabin/400.css'
import '@fontsource/cabin/600.css'
import '@fontsource/cabin/700.css'
import '@fontsource/caladea/400.css'
import '@fontsource/caladea/400-italic.css'
import '@fontsource/caladea/700.css'
import '@fontsource/alegreya-sans/400.css'
import '@fontsource/alegreya-sans/400-italic.css'
import '@fontsource/alegreya-sans/500.css'
import '@fontsource/alegreya-sans/700.css'
import './index.css'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
