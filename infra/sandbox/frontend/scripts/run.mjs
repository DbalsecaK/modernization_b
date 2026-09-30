// Builds and tests one generated frontend in the sandbox (ADR-0016). Input: /input/project (a React or Angular
// project written by the platform and the agent) and /input/screens.json (the screen contracts). The type check is
// the compiler (tsc for React, ngc with strict templates for Angular); then the app and the platform's harness entry
// are bundled, and every screen is mounted in jsdom with a recording API and navigation and checked against its
// contract, with axe-core. Prints one JSON report between markers; the container has no network.
import { execFileSync } from 'node:child_process'
import { cpSync, existsSync, readFileSync, symlinkSync } from 'node:fs'
import { createRequire } from 'node:module'

const require = createRequire('/opt/sandbox/')
const esbuild = require('esbuild')
const { JSDOM } = require('jsdom')
const axe = require('axe-core')

const flavour = process.argv[2]
const report = { flavour, compiled: false, errors: [], app: false, screens: [] }
const done = () => {
  console.log('===FRONTEND===')
  console.log(JSON.stringify(report))
  console.log('===END===')
}

cpSync('/input/project', '/work/project', { recursive: true })
symlinkSync('/opt/sandbox/node_modules', '/work/project/node_modules')
cpSync('/opt/ds', '/work/project/ds', { recursive: true }) // the design system, inside the project for the compiler
process.chdir('/work/project')

// -- 1. the compiler ------------------------------------------------------------------------------------------------
try {
  const compiler = flavour === 'angular' ? 'ngc' : 'tsc'
  const args = flavour === 'angular' ? ['-p', 'tsconfig.json'] : ['-p', 'tsconfig.json', '--noEmit']
  execFileSync(`/opt/sandbox/node_modules/.bin/${compiler}`, args, { stdio: 'pipe', timeout: 240_000 })
  report.compiled = true
} catch (error) {
  const text = `${error.stdout ?? ''}${error.stderr ?? ''}`.replace(/\x1b\[[0-9;]*m/g, '')
  report.errors = text.split('\n').filter((l) => l.includes('error')).slice(0, 40)
  if (report.errors.length === 0) report.errors = [text.slice(0, 3000) || String(error)]
  done()
  process.exit(0)
}

// -- 2. the bundles -------------------------------------------------------------------------------------------------
const options = {
  absWorkingDir: '/work/project',
  bundle: true,
  write: false,
  format: 'iife',
  target: 'es2022',
  jsx: 'automatic',
  nodePaths: ['/opt/sandbox/node_modules'],
  alias: { '@nexti/ds/ds.css': '/work/project/ds/ds.css', '@nexti/ds': '/work/project/ds/index.ts' },
  loader: { '.css': 'empty' },
  tsconfig: 'tsconfig.json',
  define: { 'process.env.NODE_ENV': '"production"' },
  logLevel: 'silent',
}
const entry = flavour === 'angular' ? 'src' : 'src'
const ext = flavour === 'angular' ? 'ts' : 'tsx'
let harness
try {
  await esbuild.build({ ...options, entryPoints: [`${entry}/main.${ext}`] })
  report.app = true
  harness = (await esbuild.build({ ...options, entryPoints: [`${entry}/harness.${ext}`] })).outputFiles[0].text
} catch (error) {
  report.errors = (error.errors ?? [{ text: String(error) }]).slice(0, 20).map((e) =>
    e.location ? `${e.location.file}:${e.location.line}: ${e.text}` : e.text)
  done()
  process.exit(0)
}

// -- 3. the screens -------------------------------------------------------------------------------------------------
const contracts = JSON.parse(readFileSync('/input/screens.json', 'utf8'))
const wait = (ms = 30) => new Promise((resolve) => setTimeout(resolve, ms))

async function mount(id) {
  const dom = new JSDOM('<!doctype html><html lang="es"><head><title>screen</title></head><body><div id="root"></div></body></html>', {
    runScripts: 'outside-only',
    pretendToBeVisual: true,
  })
  const w = dom.window
  const calls = []
  const navigations = []
  const api = new Proxy({}, {
    get: (_target, method) => (request) => {
      calls.push({ method: String(method), request })
      return Promise.resolve({})
    },
  })
  w.eval(harness)
  await w.__nexti.mount(id, api, (to) => navigations.push(String(to)))
  await wait()
  return { w, doc: w.document, calls, navigations }
}

// The text a screen reader announces: decorative parts (aria-hidden, like a required asterisk) do not count.
function spoken(element) {
  if (!element) return ''
  const copy = element.cloneNode(true)
  copy.querySelectorAll('[aria-hidden="true"]').forEach((hidden) => hidden.remove())
  return copy.textContent.trim()
}

function accessibleName(doc, control) {
  if (control.getAttribute('aria-label')?.trim()) return control.getAttribute('aria-label').trim()
  const labelledby = control.getAttribute('aria-labelledby')
  if (labelledby) return labelledby.split(/\s+/).map((i) => spoken(doc.getElementById(i))).join(' ').trim()
  if (control.id) {
    const label = doc.querySelector(`label[for="${control.id}"]`)
    if (label) return spoken(label)
  }
  return spoken(control.closest('label'))
}

function type(w, control, value) {
  const proto = control.tagName === 'SELECT' ? w.HTMLSelectElement.prototype : control.tagName === 'TEXTAREA'
    ? w.HTMLTextAreaElement.prototype : w.HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(control, value)
  control.dispatchEvent(new w.Event('input', { bubbles: true }))
  control.dispatchEvent(new w.Event('change', { bubbles: true }))
}

function sample(field, control) {
  if (control.tagName === 'SELECT') return [...control.options].find((o) => o.value)?.value ?? ''
  const length = Math.max(1, Math.min(field.length || 3, control.maxLength > 0 ? control.maxLength : 3, 3))
  return (field.numeric ? '1' : 'A').repeat(length)
}

const check = (key, ok, detail) => ({ key, status: ok ? 'passed' : 'failed', detail })

for (const contract of contracts) {
  const result = { id: contract.id, checks: [] }
  report.screens.push(result)
  let screen
  try {
    screen = await mount(contract.id)
  } catch (error) {
    result.checks.push(check('mounts', false, `the screen did not mount: ${String(error).slice(0, 500)}`))
    continue
  }
  const { w, doc } = screen
  const main = doc.querySelector('main')
  result.checks.push(check('mounts', !!main && !!(main.getAttribute('aria-label') || main.getAttribute('aria-labelledby')),
    main ? 'the page root is a labelled main' : 'there is no main element'))

  // fields: present, labelled, of the right kind, with length, numeric and secret traits
  const problems = []
  const controls = {}
  for (const field of contract.fields) {
    const holder = doc.querySelector(`[data-field="${field.name}"]`)
    if (!holder) {
      problems.push(`${field.name}: missing`)
      continue
    }
    const control = holder.matches('input,select,textarea') ? holder : holder.querySelector('input,select,textarea')
    if (field.kind === 'input') {
      if (!control) { problems.push(`${field.name}: no input`); continue }
      controls[field.name] = control
      if (!accessibleName(doc, control)) problems.push(`${field.name}: no accessible label`)
      if (control.readOnly || control.disabled) problems.push(`${field.name}: an input field is read-only`)
      if (field.length && control.tagName === 'INPUT' && !(control.maxLength > 0 && control.maxLength <= field.length)) {
        problems.push(`${field.name}: maxLength must be at most ${field.length}`)
      }
      if (field.numeric && control.tagName === 'INPUT' && control.inputMode !== 'numeric' && control.type !== 'number') {
        problems.push(`${field.name}: a numeric field needs inputMode="numeric"`)
      }
      if (field.secret && control.type !== 'password') problems.push(`${field.name}: a secret field must be a password input`)
    } else if (control && !(control.readOnly || control.disabled)) {
      problems.push(`${field.name}: an output field must not be editable`)
    }
  }
  result.checks.push(check('fields', problems.length === 0, problems.length ? problems.join('; ') : `${contract.fields.length} field(s)`))

  const missingActions = contract.actions.filter((a) => !doc.querySelector(`[data-action="${a.key}"]`)).map((a) => a.key)
  result.checks.push(check('actions', missingActions.length === 0,
    missingActions.length ? `missing actions: ${missingActions.join(', ')}` : `${contract.actions.length} action(s)`))

  const required = contract.fields.filter((f) => f.kind === 'input' && f.required)
  const enter = () => doc.querySelector('[data-action="ENTER"]')
  if (required.length && enter()) {
    enter().click()
    await wait()
    const alerts = [...doc.querySelectorAll('[role="alert"]')].filter((a) => a.textContent.trim())
    const quiet = screen.calls.length === 0 && screen.navigations.length === 0
    result.checks.push(check('validation', alerts.length > 0 && quiet, alerts.length === 0
      ? 'submitting with required fields empty shows no alert'
      : quiet ? `${alerts.length} alert(s), nothing called` : 'the empty form called the backend or navigated'))
  } else {
    result.checks.push({ key: 'validation', status: 'not_checked', detail: 'no required input field' })
  }

  // axe on the page as mounted (after the empty submit, the error messages are part of it)
  w.eval(axe.source)
  const scan = await w.axe.run(doc, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
    rules: { 'color-contrast': { enabled: false } } })
  const serious = scan.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  result.checks.push(check('accessibility', serious.length === 0, serious.length
    ? serious.map((v) => `${v.id}: ${v.help}`).join('; ') : 'axe: no serious or critical violation (contrast not measurable in jsdom)'))

  // a valid ENTER calls the backend or navigates
  if (enter() && Object.keys(controls).length) {
    const fresh = await mount(contract.id)
    for (const field of contract.fields.filter((f) => f.kind === 'input')) {
      const control = fresh.doc.querySelector(`[data-field="${field.name}"]`)
      const input = control && (control.matches('input,select,textarea') ? control : control.querySelector('input,select,textarea'))
      if (input) type(fresh.w, input, sample(field, input))
    }
    fresh.doc.querySelector('[data-action="ENTER"]').click()
    await wait(60)
    const acted = fresh.calls.length + fresh.navigations.length > 0
    result.checks.push(check('submit', acted, acted
      ? `calls: ${fresh.calls.map((c) => c.method).join(', ') || 'none'}; navigates: ${fresh.navigations.join(', ') || 'no'}`
      : 'a valid ENTER neither called the backend nor navigated'))
  }

  // actions with a target navigate to it
  const targeted = contract.actions.filter((a) => a.target)
  const wrong = []
  for (const action of targeted) {
    const fresh = await mount(contract.id)
    fresh.doc.querySelector(`[data-action="${action.key}"]`)?.click()
    await wait()
    if (!fresh.navigations.includes(action.target)) wrong.push(`${action.key} -> ${action.target}`)
  }
  if (targeted.length) {
    result.checks.push(check('navigation', wrong.length === 0, wrong.length ? `do not navigate: ${wrong.join(', ')}` : `${targeted.length} navigation(s)`))
  }
}
done()
