import type { Design } from '@/api/architecture'

/** One row of the bounded contexts table: the context with the rules, services and endpoints of its use cases. */
export interface ContextSummary {
  name: string
  rules: number
  services: string[]
  endpoints: number
}

/** The packs generate one application service per use case, named `<UseCase>Service`. */
export const serviceOf = (useCase: string) => `${useCase}Service`

export function contextSummary(design: Design): ContextSummary {
  const useCases = design.useCases ?? []
  const rules = new Set(useCases.flatMap((u) => u.rules ?? []))
  return {
    name: design.context,
    rules: rules.size,
    services: useCases.map((u) => serviceOf(u.name)),
    endpoints: useCases.length,
  }
}

/** The OpenAPI document as text for reading, cut at `maxLines` so a large contract does not flood the page. */
export function contractText(document: unknown, maxLines = 120): { text: string; truncated: boolean } {
  const lines = JSON.stringify(document, null, 2).split('\n')
  return { text: lines.slice(0, maxLines).join('\n'), truncated: lines.length > maxLines }
}
