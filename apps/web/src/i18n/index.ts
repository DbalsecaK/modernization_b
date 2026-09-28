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

export function setLanguage(lng: Language) {
  writeStorage(KEY, lng)
  void i18n.changeLanguage(lng)
}

export default i18n
