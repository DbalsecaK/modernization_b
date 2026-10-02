// Shim of next/link for the sandbox bundle (ADR-0028): a plain anchor. The bundle is only built, never run.
export default function Link({ href, children, prefetch: _prefetch, replace: _replace, scroll: _scroll, ...rest }) {
  return (
    <a href={typeof href === 'string' ? href : String(href?.pathname ?? '')} {...rest}>
      {children}
    </a>
  )
}
