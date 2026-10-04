import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, toApiError, type Schemas } from './client'

// Projects, their composition and their inputs (spec 18.3, 9, 7.1). The team and skills are proposed and validated
// by the server's deterministic engine; the web only shows the result and sends the user's choices.
export type Catalog = Schemas['CatalogOut']
export type CatalogAgent = Schemas['AgentOut']
export type CatalogSkill = Schemas['SkillOut']
export type TargetOption = Schemas['TargetOptionOut']
export type ComposeInput = Schemas['ComposeIn']
export type Composition = Schemas['CompositionOut']
export type ProjectSummary = Schemas['ProjectOut']
export type ProjectDetail = Schemas['ProjectDetail']
export type ProjectCreateInput = Schemas['ProjectCreate']
export type ConfigInput = Schemas['ConfigIn']
export type ConfigVersion = Schemas['ConfigVersionOut']
export type InputItem = Schemas['InputOut']
export type Repository = Schemas['RepositoryOut']
export type RepositoryInput = Schemas['RepositoryIn']
export type Target = Schemas['TargetIn']
export type Flow = ProjectCreateInput['flow']
export type FileKind = 'source_archive' | 'target_archive' | 'document' | 'screenshot'
export type LinkKind = 'figma_link' | 'prototype_link'

export const AXES = ['architecture', 'backend', 'frontend', 'database', 'cloud'] as const

// Project permissions the screens use to show or hide actions (the API checks them anyway).
const PROJECT_PERMISSIONS = {
  configure: 'project.configure',
  upload: 'input.upload',
  selectAgents: 'agents.select',
  selectSkills: 'skills.select',
  downloadCode: 'code.download',
} as const

export function hasProjectPermission(project: ProjectDetail, action: keyof typeof PROJECT_PERMISSIONS): boolean {
  return project.permissions.includes(PROJECT_PERMISSIONS[action])
}

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const keys = {
  catalog: ['catalog'],
  projects: ['projects'],
  project: (id: string) => ['projects', id],
  inputs: (id: string) => ['projects', id, 'inputs'],
  repository: (id: string) => ['projects', id, 'repository'],
  versions: (id: string) => ['projects', id, 'versions'],
} as const

function useRefreshing<A, R>(fn: (args: A) => Promise<R>, refresh: (args: A) => readonly (readonly string[])[]) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async (_data, args) => {
      await Promise.all(refresh(args).map((queryKey) => client.invalidateQueries({ queryKey })))
    },
  })
}

// Catalog
export const useCatalog = () =>
  useQuery({ queryKey: keys.catalog, queryFn: () => unwrap(api.GET('/api/v1/catalog')), staleTime: 5 * 60_000 })

export const useSkill = (key: string | null) =>
  useQuery({
    queryKey: [...keys.catalog, 'skill', key],
    queryFn: () => unwrap(api.GET('/api/v1/catalog/skills/{skill_key}', { params: { path: { skill_key: key! } } })),
    enabled: !!key,
  })

/** The recommendation and validation of a composition, recomputed by the server as the user changes it. */
export const useComposition = (input: ComposeInput | null) =>
  useQuery({
    queryKey: ['compose', input],
    queryFn: () => unwrap(api.POST('/api/v1/projects:compose', { body: input! })),
    enabled: !!input && input.sources.length > 0,
    placeholderData: keepPreviousData,
  })

// Projects
export const useProjectList = () =>
  useQuery({ queryKey: keys.projects, queryFn: () => unwrap(api.GET('/api/v1/projects')) })

export const useProject = (id: string) =>
  useQuery({
    queryKey: keys.project(id),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}', { params: { path: { project_id: id } } })),
    // A refused or missing project is final (it shows "not found"); a network hiccup is tried again.
    retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 2,
  })

export const useCreateProject = () =>
  useRefreshing(
    (body: ProjectCreateInput) => unwrap(api.POST('/api/v1/projects', { body })),
    () => [keys.projects, ['admin', 'projects']],
  )

export const useUpdateProject = (id: string) =>
  useRefreshing(
    (body: Schemas['ProjectUpdate']) =>
      unwrap(api.PATCH('/api/v1/projects/{project_id}', { params: { path: { project_id: id } }, body })),
    () => [keys.project(id), keys.projects],
  )

export const useChangeConfig = (id: string) =>
  useRefreshing(
    (body: ConfigInput) =>
      unwrap(api.PUT('/api/v1/projects/{project_id}/config', { params: { path: { project_id: id } }, body })),
    () => [keys.project(id), keys.versions(id), keys.projects],
  )

export const useConfigVersions = (id: string) =>
  useQuery({
    queryKey: keys.versions(id),
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/config/versions', { params: { path: { project_id: id } } })),
  })

// Inputs
export const useInputs = (id: string) =>
  useQuery({
    queryKey: keys.inputs(id),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/inputs', { params: { path: { project_id: id } } })),
  })

/** Upload one input; the server validates it before storing it and answers 422 with the reason if it is rejected.
 * A code input takes one zip or several loose code files, which the server packs into one archive. */
export function uploadInput(projectId: string, file: File | File[], kind: FileKind, notes = '') {
  const files = Array.isArray(file) ? file : [file]
  return unwrap(
    api.POST('/api/v1/projects/{project_id}/inputs', {
      params: { path: { project_id: projectId } },
      body: { file: files as unknown as string[], kind, notes },
      bodySerializer: (body) => {
        const form = new FormData()
        for (const f of files) form.append('file', f, f.name)
        form.append('kind', body.kind)
        form.append('notes', body.notes ?? '')
        return form
      },
    }),
  )
}

export function addLink(projectId: string, kind: LinkKind, url: string, notes = '') {
  return unwrap(
    api.POST('/api/v1/projects/{project_id}/inputs:link', {
      params: { path: { project_id: projectId } },
      body: { kind, url, notes },
    }),
  )
}

export const useUploadInput = (id: string) =>
  useRefreshing(
    ({ file, kind, notes }: { file: File | File[]; kind: FileKind; notes?: string }) =>
      uploadInput(id, file, kind, notes),
    () => [keys.inputs(id)],
  )

export const useAddLink = (id: string) =>
  useRefreshing(
    ({ kind, url, notes }: { kind: LinkKind; url: string; notes?: string }) => addLink(id, kind, url, notes),
    () => [keys.inputs(id)],
  )

export const useDeleteInput = (id: string) =>
  useRefreshing(
    (inputId: string) =>
      unwrap(
        api.DELETE('/api/v1/projects/{project_id}/inputs/{input_id}', {
          params: { path: { project_id: id, input_id: inputId } },
        }),
      ),
    () => [keys.inputs(id)],
  )

/** Same-origin URL of an input's content (thumbnails and downloads; the session cookie authorizes it). */
export const inputContentUrl = (projectId: string, inputId: string) =>
  `/api/v1/projects/${projectId}/inputs/${inputId}/content`

// Repository
export const useRepository = (id: string) =>
  useQuery({
    queryKey: keys.repository(id),
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/repository', { params: { path: { project_id: id } } })),
  })

export function setRepository(projectId: string, body: RepositoryInput) {
  return unwrap(
    api.PUT('/api/v1/projects/{project_id}/repository', { params: { path: { project_id: projectId } }, body }),
  )
}

export const useSetRepository = (id: string) =>
  useRefreshing(
    (body: RepositoryInput) => setRepository(id, body),
    () => [keys.repository(id)],
  )

export const useTestRepository = (id: string) =>
  useRefreshing(
    () => unwrap(api.POST('/api/v1/projects/{project_id}/repository:test', { params: { path: { project_id: id } } })),
    () => [keys.repository(id)],
  )

export const useDeleteRepository = (id: string) =>
  useRefreshing(
    () => unwrap(api.DELETE('/api/v1/projects/{project_id}/repository', { params: { path: { project_id: id } } })),
    () => [keys.repository(id)],
  )
