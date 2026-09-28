import { useSyncExternalStore } from 'react'
import { storyHistorySeed, userStories, type UserStory } from '@/mocks/data'
import { moveStory, suggestPlan, type Plan } from '@/lib/migrationPlan'

// Shared state of the user stories and the migration plan of the project (mock). In the real platform it is
// the API (spec 19.4: user_story, story_version, migration_plan); every change is versioned and audited.

export type StoryRole = 'productOwner' | 'techLead' | 'executive'

export interface HistoryEntry {
  story: string
  version: number
  by: string
  at: string
  change: string
}

interface State {
  stories: UserStory[]
  plan: Plan
  history: HistoryEntry[]
  approved: boolean
  role: StoryRole
  dismissed: string[]
}

const active = (s: UserStory) => s.status !== 'discarded' && s.status !== 'merged'

export const suggestedFor = (stories: UserStory[]) => suggestPlan(stories.filter(active))

let state: State = {
  stories: userStories,
  plan: suggestedFor(userStories),
  history: storyHistorySeed,
  approved: false,
  role: 'productOwner',
  dismissed: [],
}
const listeners = new Set<() => void>()
const set = (next: Partial<State>) => {
  state = { ...state, ...next }
  listeners.forEach((l) => l())
}

export function useStories() {
  return useSyncExternalStore(
    (l) => (listeners.add(l), () => listeners.delete(l)),
    () => state,
  )
}

export const can = {
  editStories: (r: StoryRole) => r === 'productOwner',
  editPlan: (r: StoryRole) => r === 'productOwner' || r === 'techLead',
}

const who = () => (state.role === 'productOwner' ? 'You (product owner)' : 'You (tech lead)')

function log(story: string, version: number, change: string) {
  const suffix = state.approved ? ' [scope change after C1]' : ''
  return [{ story, version, by: who(), at: new Date().toISOString(), change: change + suffix }, ...state.history]
}

export function setRole(role: StoryRole) {
  set({ role })
}

export function nextStoryId() {
  const max = Math.max(...state.stories.map((s) => Number(s.id.slice(3))))
  return `US-${String(max + 1).padStart(3, '0')}`
}

// Saves a new or edited story. After C1 an edit reopens the story for review (scope change).
export function saveStory(story: UserStory, change: string) {
  const exists = state.stories.some((s) => s.id === story.id)
  const version = exists ? story.version + 1 : 1
  const saved = { ...story, version, status: state.approved && story.status === 'approved' ? ('inReview' as const) : story.status }
  const stories = exists ? state.stories.map((s) => (s.id === story.id ? saved : s)) : [...state.stories, saved]
  // New stories join the wave the suggestion gives them; existing ones keep their place.
  const plan = exists ? state.plan : placeNew(saved, stories)
  set({ stories, plan, history: log(story.id, version, change) })
}

function placeNew(story: UserStory, stories: UserStory[]): Plan {
  const wave = suggestedFor(stories).findIndex((w) => w.includes(story.id))
  const r = moveStory(state.plan, stories, story.id, Math.max(wave, 0))
  return r.accepted ? r.plan : [...state.plan, [story.id]]
}

export function discardStory(id: string, reason: string, outOfScope: boolean) {
  const s = state.stories.find((x) => x.id === id)!
  set({
    stories: state.stories.map((x) => (x.id === id ? { ...x, status: 'discarded', discardReason: reason, outOfScope, version: x.version + 1 } : x)),
    plan: state.plan.map((w) => w.filter((x) => x !== id)).filter((w) => w.length > 0),
    history: log(id, s.version + 1, `${outOfScope ? 'Marked out of scope' : 'Discarded'}: ${reason}`),
  })
}

export function restoreStory(id: string) {
  const s = state.stories.find((x) => x.id === id)!
  const restored = { ...s, status: 'inReview' as const, discardReason: undefined, outOfScope: undefined, version: s.version + 1 }
  const stories = state.stories.map((x) => (x.id === id ? restored : x))
  set({ stories, plan: placeNew(restored, stories), history: log(id, restored.version, 'Restored') })
}

// Splits a story: the selected criteria and links move to a new story that depends on nothing new.
export function splitStory(id: string, title: string, criteria: number[], rules: string[]) {
  const s = state.stories.find((x) => x.id === id)!
  const newId = nextStoryId()
  const part: UserStory = {
    ...s,
    id: newId,
    title,
    criteria: s.criteria.filter((_, i) => criteria.includes(i)),
    rules: s.rules.filter((r) => rules.includes(r)),
    origin: 'user',
    source: `Split from ${id}`,
    status: 'inReview',
    points: Math.max(1, Math.round(s.points / 2)),
    version: 1,
  }
  const rest: UserStory = {
    ...s,
    criteria: s.criteria.filter((_, i) => !criteria.includes(i)),
    rules: s.rules.filter((r) => !rules.includes(r)),
    points: Math.max(1, s.points - part.points),
    status: 'inReview',
    version: s.version + 1,
  }
  const stories = [...state.stories.map((x) => (x.id === id ? rest : x)), part]
  const w = state.plan.findIndex((x) => x.includes(id))
  const plan = state.plan.map((x, i) => (i === w ? [...x, newId] : x))
  set({ stories, plan, history: [{ story: newId, version: 1, by: who(), at: new Date().toISOString(), change: `Created by splitting ${id}` }, ...log(id, rest.version, `Split: "${title}" moved to ${newId}`)] })
  return newId
}

// Merges `other` into `id`: criteria, links and dependencies are joined; `other` stays as merged for traceability.
export function mergeStories(id: string, other: string) {
  const a = state.stories.find((x) => x.id === id)!
  const b = state.stories.find((x) => x.id === other)!
  const uniq = <T,>(xs: T[]) => Array.from(new Set(xs))
  const merged: UserStory = {
    ...a,
    criteria: [...a.criteria, ...b.criteria],
    rules: uniq([...a.rules, ...b.rules]),
    screens: uniq([...a.screens, ...b.screens]),
    contracts: uniq([...a.contracts, ...b.contracts]),
    nodes: uniq([...a.nodes, ...b.nodes]),
    dependsOn: [...a.dependsOn, ...b.dependsOn].filter((d, i, all) => d.story !== id && d.story !== other && all.findIndex((x) => x.story === d.story) === i),
    points: a.points + b.points,
    status: 'inReview',
    version: a.version + 1,
  }
  // Stories that depended on `other` now depend on the merged story.
  const stories = state.stories.map((x) =>
    x.id === id
      ? merged
      : x.id === other
        ? { ...x, status: 'merged' as const, mergedInto: id, version: x.version + 1 }
        : { ...x, dependsOn: x.dependsOn.map((d) => (d.story === other ? { ...d, story: id } : d)) },
  )
  set({
    stories,
    plan: state.plan.map((w) => w.filter((x) => x !== other)).filter((w) => w.length > 0),
    history: [...log(id, merged.version, `Merged ${other} into this story`)],
  })
}

export function setPlan(plan: Plan) {
  set({ plan })
}

export function resetPlan() {
  set({ plan: suggestedFor(state.stories) })
}

export function approveC1() {
  set({ approved: true, stories: state.stories.map((s) => (s.status === 'inReview' || s.status === 'draft' ? { ...s, status: 'approved' } : s)) })
}

export function dismissSuggestion(id: string) {
  set({ dismissed: [...state.dismissed, id] })
}
