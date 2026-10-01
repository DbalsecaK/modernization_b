import { useQuery } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// The generated code of a project (spec 18.3, tab "Code"): the file tree of the newest generation and one file at a
// time (`code.view`), and the whole project as a zip (`code.download`, audited by the API).
export type CodeTree = Schemas['CodeTreeOut']
export type CodeFileEntry = Schemas['CodeFileEntryOut']
export type CodeFile = Schemas['CodeFileOut']

/** The project permission the zip requires. */
export const CODE_DOWNLOAD = 'code.download'

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const keys = {
  tree: (projectId: string) => ['projects', projectId, 'code'],
  file: (projectId: string, path: string) => ['projects', projectId, 'code', 'file', path],
} as const

/** `null` until the pipeline generates code. */
export const useCodeTree = (projectId: string, enabled = true) =>
  useQuery({
    queryKey: keys.tree(projectId),
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/code', { params: { path: { project_id: projectId } } })),
    enabled,
  })

export const useCodeFile = (projectId: string, path: string | null) =>
  useQuery({
    queryKey: keys.file(projectId, path ?? ''),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/code/file', {
          params: { path: { project_id: projectId }, query: { path: path! } },
        }),
      ),
    enabled: !!path,
  })

/** A plain same-origin link: the browser sends the session cookie and saves the zip (Content-Disposition). */
export const codeDownloadUrl = (projectId: string) => `/api/v1/projects/${projectId}/code:download`
