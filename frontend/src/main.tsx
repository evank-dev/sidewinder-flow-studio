import React, { Suspense, lazy } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'

// Phase 0 spike: Graphic Walker is lazy-loaded so it stays out of the main bundle.
const ExploreSpike = lazy(() => import('./components/explore/ExploreSpike'))
const isExplore = window.location.hash.startsWith('#/explore')

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {isExplore ? <Suspense fallback={null}><ExploreSpike /></Suspense> : <App />}
  </React.StrictMode>,
)
