// Checks that every static translation key used in src/ exists in the English catalog.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const en = JSON.parse(readFileSync('src/i18n/locales/en.json', 'utf8'))
const tops = new Set(Object.keys(en))
const files = []
const walk = (d) =>
  readdirSync(d).forEach((f) => {
    const p = join(d, f)
    statSync(p).isDirectory() ? walk(p) : /\.tsx?$/.test(p) && files.push(p)
  })
walk('src')
// Normalize Windows separators so the mocks folder is excluded on every OS.
const scanned = files.filter((f) => !f.replaceAll('\\', '/').includes('/mocks/'))

const resolve = (key) => {
  let node = en
  for (const part of key.split('.')) {
    if (node && typeof node === 'object' && part in node) node = node[part]
    else return false
  }
  return true
}
const exists = (key) => resolve(key) || resolve(key + '_one') || resolve(key + '_other')

const missing = new Set()
for (const f of scanned) {
  const src = readFileSync(f, 'utf8')
  for (const m of src.matchAll(/['"`]([a-zA-Z]+(?:\.[a-zA-Z0-9_]+)+)['"`]/g)) {
    const key = m[1]
    if (!tops.has(key.split('.')[0])) continue
    if (/\.(ts|tsx|json|css|js|mjs)$/.test(key)) continue
    if (!exists(key)) missing.add(`${key}  (${f})`)
  }
  for (const m of src.matchAll(/`([a-zA-Z]+(?:\.[a-zA-Z]+)*)\.\$\{/g)) {
    if (tops.has(m[1].split('.')[0]) && !resolve(m[1])) missing.add(`${m[1]}.*  (${f})`)
  }
}
if (missing.size) {
  console.error('Missing keys:\n' + [...missing].sort().join('\n'))
  process.exit(1)
}
console.log('All static keys resolve.')
