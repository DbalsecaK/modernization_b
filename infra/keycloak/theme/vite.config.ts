import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { keycloakify } from 'keycloakify/vite-plugin'

// Login pages only (the account console stays Keycloak's); one jar for Keycloak 26 (ADR-0022).
export default defineConfig({
  plugins: [
    react(),
    keycloakify({
      themeName: 'nexti',
      accountThemeImplementation: 'none',
      keycloakVersionTargets: { '22-to-25': false, 'all-other-versions': 'nexti-keycloak-theme.jar' },
    }),
  ],
})
