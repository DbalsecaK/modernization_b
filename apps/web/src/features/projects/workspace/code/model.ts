import type { CodeFileEntry } from '@/api/code'

/** One row of the file browser: a folder (its label may join a chain of single folders) or a file. */
export type TreeNode = { key: string; label: string; depth: number; file?: CodeFileEntry }

type Folder = { folders: Map<string, Folder>; files: CodeFileEntry[] }

const emptyFolder = (): Folder => ({ folders: new Map(), files: [] })

/**
 * The flat, indented rows of a file tree: folders before files, both by name, and a chain of folders with a single
 * subfolder and no files shown as one row (`src/main/java/demo/`), as IDEs do.
 */
export function buildTree(files: CodeFileEntry[]): TreeNode[] {
  const root = emptyFolder()
  for (const file of files) {
    const parts = file.path.split('/')
    let folder = root
    for (const part of parts.slice(0, -1)) {
      if (!folder.folders.has(part)) folder.folders.set(part, emptyFolder())
      folder = folder.folders.get(part)!
    }
    folder.files.push(file)
  }
  const rows: TreeNode[] = []
  const walk = (folder: Folder, prefix: string, depth: number) => {
    for (const name of [...folder.folders.keys()].sort()) {
      let label = `${name}/`
      let current = folder.folders.get(name)!
      while (current.files.length === 0 && current.folders.size === 1) {
        const [next, child] = [...current.folders.entries()][0]
        label += `${next}/`
        current = child
      }
      rows.push({ key: `${prefix}${label}`, label, depth })
      walk(current, `${prefix}${label}`, depth + 1)
    }
    for (const file of [...folder.files].sort((a, b) => a.path.localeCompare(b.path))) {
      rows.push({ key: file.path, label: file.path.split('/').at(-1)!, depth, file })
    }
  }
  walk(root, '', 0)
  return rows
}

/** The file shown first: the one asked for in the URL if it exists, else the first file of the tree. */
export function initialFile(rows: TreeNode[], asked?: string): string | null {
  return rows.find((r) => r.file?.path === asked)?.file?.path ?? rows.find((r) => r.file)?.file?.path ?? null
}

/** Size in a short human form (B, KB, MB). */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** The project's code apart from the documents of the generation (findings, engine notes, convergence): they are
 * evidence of how the code was reached, not part of the project, so the browser shows them in their own group. */
export function splitDocs(files: CodeFileEntry[]): { code: CodeFileEntry[]; docs: CodeFileEntry[] } {
  return {
    code: files.filter((f) => f.layer !== 'docs'),
    docs: files.filter((f) => f.layer === 'docs'),
  }
}

/** A run of the project is generating code now: the tab shows the files saved so far, not the finished project. */
export function generationInProgress(runs: { status: string; currentPhase: string | null }[] | undefined): boolean {
  return (runs ?? []).some(
    (r) => ['queued', 'running', 'waiting'].includes(r.status) && r.currentPhase === 'generation',
  )
}
