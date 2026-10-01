import type { TemplateProps } from 'keycloakify/login/TemplateProps'
import DefaultTemplate from 'keycloakify/login/Template'
import type { KcContext } from './KcContext'
import type { I18n } from './i18n'

// The prototype's sign-in layout: the brand panel on the left, Keycloak's page (login, second factor, recovery,
// activation) on the right with the platform's colours.
export default function Template(props: TemplateProps<KcContext, I18n>) {
  const { msgStr } = props.i18n
  return (
    <div className="nx-split">
      <aside className="nx-hero" aria-hidden="true">
        <div className="nx-logo">
          Nex<span>TI</span>
        </div>
        <div>
          <h2>{msgStr('nxHeroTitle')}</h2>
          <p>{msgStr('nxHeroBody')}</p>
          <ul>
            <li>{msgStr('nxHeroPoint1')}</li>
            <li>{msgStr('nxHeroPoint2')}</li>
            <li>{msgStr('nxHeroPoint3')}</li>
          </ul>
        </div>
        <p className="nx-note">{msgStr('nxSecurityNote')}</p>
      </aside>
      <main className="nx-main">
        <DefaultTemplate {...props} />
      </main>
    </div>
  )
}
