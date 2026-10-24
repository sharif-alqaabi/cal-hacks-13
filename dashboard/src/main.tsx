import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { SpacetimeDBProvider } from 'spacetimedb/react'
import { DbConnection } from './module_bindings'
import App from './App'
import './index.css'

// Anonymous connection: the tables are public and the page only calls the resolve and delete reducers.
const connection = DbConnection.builder()
  .withUri(import.meta.env.VITE_SPACETIME_HOST ?? 'wss://maincloud.spacetimedb.com')
  .withDatabaseName(import.meta.env.VITE_SPACETIME_DB ?? 'calhacks13-memory')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SpacetimeDBProvider connectionBuilder={connection}>
      <App />
    </SpacetimeDBProvider>
  </StrictMode>,
)
