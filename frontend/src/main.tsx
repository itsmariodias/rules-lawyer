import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
/* Free stand-ins for the book's faces: Cabin (Gill Sans), Caladea (Cambria),
   Alegreya Sans (Optima).  Before index.css so our rules win the cascade. */
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
