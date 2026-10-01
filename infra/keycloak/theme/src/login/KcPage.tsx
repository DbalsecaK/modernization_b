import { lazy, Suspense } from 'react'
import type { ClassKey } from 'keycloakify/login'
import DefaultPage from 'keycloakify/login/DefaultPage'
import type { KcContext } from './KcContext'
import { useI18n } from './i18n'
import Template from './Template'
import './main.css'

const UserProfileFormFields = lazy(() => import('keycloakify/login/UserProfileFormFields'))

// Every page is Keycloak's own (so security fixes come with Keycloak), inside the platform's layout and colours.
export default function KcPage(props: { kcContext: KcContext }) {
  const { kcContext } = props
  const { i18n } = useI18n({ kcContext })
  return (
    <Suspense>
      <DefaultPage
        kcContext={kcContext}
        i18n={i18n}
        classes={classes}
        Template={Template}
        doUseDefaultCss={true}
        UserProfileFormFields={UserProfileFormFields}
        doMakeUserConfirmPassword={true}
      />
    </Suspense>
  )
}

const classes = {
  kcBodyClass: 'nx-body',
  kcFormCardClass: 'nx-card',
  kcButtonPrimaryClass: 'nx-primary',
} satisfies { [key in ClassKey]?: string }
