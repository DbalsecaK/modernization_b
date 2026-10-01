import { i18nBuilder } from 'keycloakify/login'
import type { ThemeName } from '../kc.gen'

// The texts of the prototype's sign-in screen (apps/web, auth.*), in English and Spanish.
const { useI18n, ofTypeI18n } = i18nBuilder
  .withThemeName<ThemeName>()
  .withCustomTranslations({
    en: {
      nxHeroTitle: 'Modernize legacy systems and build new features with verified AI agents.',
      nxHeroBody: 'Extract business rules, generate from an approved specification and prove equivalence with evidence.',
      nxHeroPoint1: 'Spec-driven: every line of generated code traces back to a rule.',
      nxHeroPoint2: 'Independent verification with a verdict computed by code.',
      nxHeroPoint3: 'Multi-customer, with your data kept inside your perimeter.',
      nxSecurityNote: "Protected by the platform's identity provider, per-customer isolation and full audit logging.",
    },
    es: {
      nxHeroTitle: 'Moderniza sistemas legacy y construye nuevas funcionalidades con agentes de IA verificados.',
      nxHeroBody: 'Extrae reglas de negocio, genera desde una especificación aprobada y demuestra la equivalencia con evidencia.',
      nxHeroPoint1: 'Guiado por especificación: cada línea generada se traza a una regla.',
      nxHeroPoint2: 'Verificación independiente con un veredicto calculado por código.',
      nxHeroPoint3: 'Multi-cliente, con tus datos dentro de tu perímetro.',
      nxSecurityNote: 'Protegido por el proveedor de identidad de la plataforma, aislamiento por cliente y auditoría completa.',
    },
  })
  .build()

type I18n = typeof ofTypeI18n

export { useI18n, type I18n }
