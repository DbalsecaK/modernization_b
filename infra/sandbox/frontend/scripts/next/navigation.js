// Shim of next/navigation for the sandbox bundle (ADR-0028): the router without a server. The bundle is only built.
const router = { push() {}, replace() {}, back() {}, forward() {}, refresh() {}, prefetch() {} }

export const useRouter = () => router
export const usePathname = () => '/'
export const useSearchParams = () => new URLSearchParams()
export const useParams = () => ({})
export function redirect(url) {
  throw new Error(`redirect to ${url}`)
}
export function notFound() {
  throw new Error('not found')
}
