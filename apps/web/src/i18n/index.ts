import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import es from './locales/es.json'
import { readStorage, writeStorage } from '@/lib/storage'

// English is the native language of the platform. Spanish is a full translation selected by the user.
// Resolution order (spec 18.6): user preference -> tenant default -> English.
export const SUPPORTED_LANGUAGES = ['en', 'es'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]

const KEY = 'nexti.language'

function initialLanguage(): Language {
  const stored = readStorage(KEY)
  return stored === 'es' || stored === 'en' ? stored : 'en'
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, es: { translation: es } },
  lng: initialLanguage(),
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
  returnNull: false,
})

i18n.on('languageChanged', (lng) => {
  document.documentElement.lang = lng
})
document.documentElement.lang = i18n.language

// Saves the preference on the server for the signed-in user (registered by api/session.ts).
let persistLanguage: ((lng: Language) => Promise<void>) | null = null

export function registerLanguagePersister(persist: (lng: Language) => Promise<void>) {
  persistLanguage = persist
}

export function setLanguage(lng: Language, options: { persist?: boolean } = {}) {
  writeStorage(KEY, lng)
  if (i18n.language !== lng) void i18n.changeLanguage(lng)
  if (options.persist !== false && persistLanguage) void persistLanguage(lng).catch(() => undefined)
}

export default i18n
