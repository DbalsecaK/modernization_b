// Builds one prototype in the sandbox (ADR-0013): /input/prototype/Screen.tsx (the agent's screen) with the
// platform's entry and the NexTI design system, into one script and one stylesheet. Prints a JSON report between
// markers; nothing is written outside /work and the container has no network.
import { cpSync, mkdirSync } from 'node:fs'
import { build } from 'esbuild'

mkdirSync('/work/prototype', { recursive: true })
cpSync('/input/prototype/Screen.tsx', '/work/prototype/Screen.tsx')
cpSync('/opt/sandbox/entry.tsx', '/work/entry.tsx')

const report = { ok: false, js: '', css: '', errors: [] }
try {
  const result = await build({
    entryPoints: ['/work/entry.tsx'],
    bundle: true,
    minify: true,
    format: 'iife',
    target: 'es2020',
    jsx: 'automatic',
    write: false,
    outdir: '/work/out',
    nodePaths: ['/opt/sandbox/node_modules'],
    alias: { '@nexti/ds/ds.css': '/opt/ds/ds.css', '@nexti/ds': '/opt/ds/index.ts' },
    define: { 'process.env.NODE_ENV': '"production"' },
    logLevel: 'silent',
  })
  for (const file of result.outputFiles) {
    if (file.path.endsWith('.js')) report.js = Buffer.from(file.contents).toString('base64')
    if (file.path.endsWith('.css')) report.css = Buffer.from(file.contents).toString('base64')
  }
  report.ok = true
} catch (error) {
  report.errors = (error.errors ?? [{ text: String(error) }]).map((e) => ({
    text: e.text,
    file: e.location?.file?.replace('/work/', '') ?? null,
    line: e.location?.line ?? null,
    column: e.location?.column ?? null,
  }))
}
console.log('===PROTOTYPE===')
console.log(JSON.stringify(report))
console.log('===END===')
