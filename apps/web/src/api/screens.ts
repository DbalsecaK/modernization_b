import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// Screens and prototypes of a project (spec 4.1, 7.4, ADR-0013, D-24): the screen specs read from the legacy maps,
// the design system, prototype versions served for an isolated frame, comments anchored to a field and the change
// chat with the UX/UI designer. The API enqueues each change for the worker; the web polls until the designer answers.
export type ScreenRow = Schemas['nexti_api__spec__schemas__RuleOut']
export type DesignSystem = Schemas['DesignSystemOut']
export type PrototypeVersion = Schemas['PrototypeOut']
export type PrototypeComment = Schemas['CommentOut']
export type ChatMessage = Schemas['ChatMessageOut']

/** The screen spec as stored (spec 4.1 "Pantalla"): snake_case, as the model writes it. */
export type ScreenField = {
  name: string
  kind: 'literal' | 'input' | 'output'
  label?: string
  position?: { row: number; column: number } | null
  length: number
  attributes?: string[]
  required?: boolean
  validation?: string
  format?: string
  message?: string
  initial?: string
}
export type ScreenAction = { key: string; label?: string; target?: string | null }
export type ScreenData = {
  id: string
  name: string
  mapset?: string | null
  map?: string | null
  rows?: number | null
  columns?: number | null
  fields: ScreenField[]
  actions?: ScreenAction[]
  navigation_out?: string[]
}

/** The project permissions the tab uses to show or hide actions (the API checks them anyway). */
export const PROTOTYPE_EDIT = 'prototype.edit'
export const PROTOTYPE_COMMENT = 'prototype.comment'
export const CODE_VIEW = 'code.view'

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const keys = {
  screens: (projectId: string) => ['projects', projectId, 'screens'],
  prototypes: (projectId: string, key: string) => ['projects', projectId, 'screens', key, 'prototypes'],
  comments: (projectId: string, key: string, version: number) => [
    'projects',
    projectId,
    'screens',
    key,
    'prototypes',
    version,
    'comments',
  ],
  chat: (projectId: string, key: string) => ['projects', projectId, 'screens', key, 'chat'],
  designSystem: (projectId: string) => ['projects', projectId, 'design-system'],
} as const

const path = (projectId: string) => ({ params: { path: { project_id: projectId } } })
const screenPath = (projectId: string, key: string) => ({ params: { path: { project_id: projectId, key } } })
const versionPath = (projectId: string, key: string, version: number) => ({
  params: { path: { project_id: projectId, key, version } },
})

export const screenData = (row: ScreenRow) => row.data as unknown as ScreenData

export const useScreens = (projectId: string) =>
  useQuery({
    queryKey: keys.screens(projectId),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/screens', path(projectId))),
  })

/** 404 until the UI phase ran: no design system yet. */
export const useDesignSystem = (projectId: string) =>
  useQuery({
    queryKey: keys.designSystem(projectId),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/design-system', path(projectId))),
    retry: false,
  })

/** Newest first. */
export const usePrototypes = (projectId: string, key: string | null) =>
  useQuery({
    queryKey: keys.prototypes(projectId, key ?? ''),
    queryFn: async () => {
      const versions = await unwrap(
        api.GET('/api/v1/projects/{project_id}/screens/{key}/prototypes', screenPath(projectId, key!)),
      )
      return [...versions].sort((a, b) => b.version - a.version)
    },
    enabled: !!key,
  })

/** The page of a version, for an iframe with sandbox="allow-scripts" (the API serves it with a strict CSP). */
export const prototypePageUrl = (projectId: string, key: string, version: number) =>
  `/api/v1/projects/${projectId}/screens/${key}/prototypes/${version}/page`

/** The TSX of a version; needs code.view. */
export const prototypeSourceUrl = (projectId: string, key: string, version: number) =>
  `/api/v1/projects/${projectId}/screens/${key}/prototypes/${version}/source`

/** Every screen as a Figma development plugin in a zip (ADR-0030); audited by the API. */
export const figmaExportUrl = (projectId: string) => `/api/v1/projects/${projectId}/screens:figma-export`

export const useComments = (projectId: string, key: string | null, version: number | null) =>
  useQuery({
    queryKey: keys.comments(projectId, key ?? '', version ?? 0),
    queryFn: () =>
      unwrap(
        api.GET(
          '/api/v1/projects/{project_id}/screens/{key}/prototypes/{version}/comments',
          versionPath(projectId, key!, version!),
        ),
      ),
    enabled: !!key && !!version,
  })

export function useAddComment(projectId: string, key: string, version: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['CommentIn']) =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/screens/{key}/prototypes/{version}/comments', {
          ...versionPath(projectId, key, version),
          body,
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.prototypes(projectId, key) }),
  })
}

export function useResolveComment(projectId: string, key: string, version: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, resolved }: { id: string; resolved: boolean }) =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/screens/{key}/prototypes/{version}/comments/{comment_id}:resolve', {
          params: { path: { project_id: projectId, key, version, comment_id: id } },
          body: { resolved },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.prototypes(projectId, key) }),
  })
}

/** Polls while a change waits for the designer; when it is answered, the versions and the specs are refreshed. */
export function useChat(projectId: string, key: string | null) {
  const client = useQueryClient()
  const query = useQuery({
    queryKey: keys.chat(projectId, key ?? ''),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/screens/{key}/chat', screenPath(projectId, key!))),
    enabled: !!key,
    refetchInterval: (q) => (q.state.data?.some((m) => m.status === 'pending') ? 2500 : false),
  })
  const pending = !!query.data?.some((m) => m.status === 'pending')
  const was = useRef(pending)
  useEffect(() => {
    if (was.current && !pending) void client.invalidateQueries({ queryKey: keys.screens(projectId) })
    was.current = pending
  }, [client, pending, projectId])
  return query
}

function useChatMutation<A>(projectId: string, key: string, fn: (args: A) => Promise<ChatMessage[]>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (messages) => {
      client.setQueryData(keys.chat(projectId, key), messages)
      void client.invalidateQueries({ queryKey: keys.screens(projectId) })
    },
  })
}

export const useAskChange = (projectId: string, key: string) =>
  useChatMutation(projectId, key, (body: string) =>
    unwrap(
      api.POST('/api/v1/projects/{project_id}/screens/{key}/chat', { ...screenPath(projectId, key), body: { body } }),
    ),
  )

export const useDecideProposal = (projectId: string, key: string) =>
  useChatMutation(projectId, key, ({ id, accept }: { id: string; accept: boolean }) => {
    const params = { params: { path: { project_id: projectId, key, message_id: id } } }
    return unwrap(
      accept
        ? api.POST('/api/v1/projects/{project_id}/screens/{key}/chat/{message_id}:accept', params)
        : api.POST('/api/v1/projects/{project_id}/screens/{key}/chat/{message_id}:reject', params),
    )
  })
