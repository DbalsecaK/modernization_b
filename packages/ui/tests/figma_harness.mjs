// A fake of the Figma plugin API that records what code.js creates (ADR-0030, plan M15 step 5). It runs code.js in a
// context of its own with only `figma` and `console`, so a script that reached for the network, eval or anything else
// outside the plugin API would fail here. Prints the document tree, the styles and the closing message as JSON.
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

let nextId = 1
const loaded = new Set()
const styles = []
const fontKey = (font) => `${font.family}/${font.style}`

class Node {
  constructor(type) {
    this.id = `${type}:${nextId++}`
    this.type = type
    this.name = ''
    this.children = []
    this.parent = null
    this.x = 0
    this.y = 0
    this.width = 100
    this.height = 100
  }
  appendChild(child) {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
    child.parent = this
    this.children.push(child)
  }
  resize(width, height) {
    this.width = width
    this.height = height
  }
  async setFillStyleIdAsync(id) {
    if (!styles.some((s) => s.id === id)) throw new Error(`unknown paint style ${id}`)
    this.fillStyleId = id
  }
}

class TextNode extends Node {
  constructor() {
    super('TEXT')
    this._font = { family: 'Inter', style: 'Regular' }
    this._characters = ''
  }
  get fontName() {
    return this._font
  }
  set fontName(font) {
    if (!loaded.has(fontKey(font))) throw new Error(`font not loaded: ${fontKey(font)}`)
    this._font = font
  }
  get characters() {
    return this._characters
  }
  set characters(value) {
    if (!loaded.has(fontKey(this._font))) throw new Error(`font not loaded: ${fontKey(this._font)}`)
    this._characters = String(value)
  }
  async setTextStyleIdAsync(id) {
    if (!styles.some((s) => s.id === id)) throw new Error(`unknown text style ${id}`)
    this.textStyleId = id
  }
}

const root = new Node('DOCUMENT')
const firstPage = new Node('PAGE')
firstPage.name = 'Page 1'
root.appendChild(firstPage)
let current = firstPage
let closed
let timer

const done = new Promise((resolve) => {
  closed = resolve
  timer = setTimeout(() => resolve('TIMEOUT'), 20000)
})

const figma = {
  root,
  get currentPage() {
    return current
  },
  async setCurrentPageAsync(page) {
    current = page
  },
  async loadFontAsync(font) {
    if (!['Inter'].includes(font.family)) throw new Error(`font not available: ${font.family}`)
    loaded.add(fontKey(font))
  },
  async getLocalPaintStylesAsync() {
    return styles.filter((s) => s.type === 'PAINT')
  },
  async getLocalTextStylesAsync() {
    return styles.filter((s) => s.type === 'TEXT')
  },
  createPaintStyle() {
    const style = { id: `S:${nextId++}`, type: 'PAINT', name: '', paints: [] }
    styles.push(style)
    return style
  },
  createTextStyle() {
    let font = null
    const style = {
      id: `S:${nextId++}`,
      type: 'TEXT',
      name: '',
      fontSize: 12,
      get fontName() {
        return font
      },
      set fontName(value) {
        if (!loaded.has(fontKey(value))) throw new Error(`font not loaded: ${fontKey(value)}`)
        font = value
      },
    }
    styles.push(style)
    return style
  },
  createPage() {
    const page = new Node('PAGE')
    root.appendChild(page)
    return page
  },
  createFrame() {
    const frame = new Node('FRAME')
    current.appendChild(frame)
    return frame
  },
  createText() {
    const text = new TextNode()
    current.appendChild(text)
    return text
  },
  closePlugin(message) {
    closed(message === undefined ? '' : String(message))
  },
}

const code = readFileSync('/input/code.js', 'utf8')
vm.runInContext(code, vm.createContext({ figma, console }), { filename: 'code.js' })
const message = await done
clearTimeout(timer)

const tree = (node) => ({
  type: node.type,
  name: node.name,
  ...(node.type === 'TEXT' ? { characters: node.characters, textStyleId: node.textStyleId ?? null } : {}),
  ...(node.type === 'FRAME' ? { x: node.x, y: node.y, fillStyleId: node.fillStyleId ?? null } : {}),
  children: node.children.map(tree),
})
const out = {
  message,
  root: tree(root),
  styles: styles.map((s) => ({ id: s.id, type: s.type, name: s.name, fontSize: s.fontSize ?? null })),
}
process.stdout.write(JSON.stringify(out))
