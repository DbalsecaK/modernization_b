// Sample data for the prototype. Names of companies and people are fictional.
// Model IDs, regions and prices are illustrative placeholders, not current provider values.
import type {
  AgentDefinition,
  AuditEntry,
  ModelOffering,
  ModelProfile,
  Project,
  ProviderConnection,
  Rule,
  RunEvent,
  SkillDefinition,
  Task,
  Tenant,
  User,
} from './types'

export const currentUser = {
  id: 'u1',
  name: 'David Balseca',
  email: 'david.balseca@nexti.example',
  initials: 'DB',
  platformRole: 'superAdmin',
}

export const tenants: Tenant[] = [
  {
    id: 't1',
    name: 'Andes Bank',
    deployment: 'customerCloud',
    projects: 3,
    users: 24,
    monthCostUsd: 4210,
    defaultLanguage: 'es',
  },
  {
    id: 't2',
    name: 'Pacific Credit Union',
    deployment: 'sharedSaas',
    projects: 1,
    users: 9,
    monthCostUsd: 960,
    defaultLanguage: 'es',
  },
  {
    id: 't3',
    name: 'NexTI Internal',
    deployment: 'sharedSaas',
    projects: 1,
    users: 14,
    monthCostUsd: 530,
    defaultLanguage: 'en',
  },
]

const modernizationPhases = [
  'preflight',
  'inventory',
  'domains',
  'classification',
  'ruleExtraction',
  'ruleReview',
  'ui',
  'design',
  'characterization',
  'generation',
  'verification',
  'hardening',
  'delivery',
]

const newFeaturePhases = [
  'ingestion',
  'normalization',
  'consolidation',
  'specReview',
  'ui',
  'design',
  'generation',
  'validation',
  'delivery',
]

const gates: Record<string, 'C1' | 'C2' | 'C3' | 'C4'> = {
  ruleReview: 'C1',
  specReview: 'C1',
  ui: 'C2',
  design: 'C3',
  verification: 'C4',
  validation: 'C4',
}

function phasesUpTo(keys: string[], currentIndex: number, currentStatus: Project['phases'][number]['status']) {
  return keys.map((key, index) => ({
    key,
    gate: gates[key],
    status: index < currentIndex ? ('done' as const) : index === currentIndex ? currentStatus : ('pending' as const),
  }))
}

export const projects: Project[] = [
  {
    id: 'p1',
    tenantId: 't1',
    name: 'Card Management — CICS to Spring Boot',
    flow: 'modernization',
    sources: ['COBOL CICS', 'BMS maps', 'DB2'],
    target: {
      architecture: 'Microservices (hexagonal)',
      backend: 'Java Spring Boot',
      frontend: 'Angular',
      database: 'PostgreSQL',
      cloud: 'AWS',
    },
    phases: phasesUpTo(modernizationPhases, 5, 'waiting'),
    verdict: 'NOT_VERIFIED',
    progress: 42,
    costUsd: 1840,
    budgetUsd: 5000,
    tokens: 61_400_000,
    rules: { total: 148, approved: 97, verified: 0 },
    openQuestions: 7,
    artifactLanguage: 'es',
    owner: 'María Torres',
    updatedAt: '2026-09-28T09:14:00Z',
  },
  {
    id: 'p2',
    tenantId: 't1',
    name: 'Interest Accrual SP — Sybase to .NET 10',
    flow: 'modernization',
    sources: ['Sybase ASE stored procedures'],
    target: {
      architecture: 'Modular monolith (hexagonal)',
      backend: '.NET 10',
      frontend: '—',
      database: 'PostgreSQL',
      cloud: 'Azure',
    },
    phases: phasesUpTo(modernizationPhases, 10, 'running'),
    verdict: 'PARTLY_PROVEN',
    progress: 81,
    costUsd: 620,
    budgetUsd: 1500,
    tokens: 19_800_000,
    rules: { total: 31, approved: 31, verified: 27 },
    openQuestions: 1,
    artifactLanguage: 'en',
    owner: 'Luis Andrade',
    updatedAt: '2026-09-28T08:40:00Z',
  },
  {
    id: 'p3',
    tenantId: 't1',
    name: 'Branch Portal — ASPX to React + .NET 10',
    flow: 'modernization',
    sources: ['ASP.NET WebForms', 'C# .NET Framework 4.8'],
    target: {
      architecture: 'BFF + microservices',
      backend: '.NET 10',
      frontend: 'React',
      database: 'SQL Server',
      cloud: 'Azure',
    },
    phases: phasesUpTo(modernizationPhases, 1, 'running'),
    verdict: 'NOT_VERIFIED',
    progress: 9,
    costUsd: 145,
    budgetUsd: 6000,
    tokens: 4_200_000,
    rules: { total: 0, approved: 0, verified: 0 },
    openQuestions: 0,
    artifactLanguage: 'en',
    owner: 'María Torres',
    updatedAt: '2026-09-28T09:30:00Z',
  },
  {
    id: 'p4',
    tenantId: 't2',
    name: 'Digital Onboarding — from Figma and user stories',
    flow: 'newFeature',
    sources: ['User stories (Jira)', 'Figma', 'User manual (PDF)'],
    target: {
      architecture: 'Microservices (hexagonal)',
      backend: 'Java Quarkus',
      frontend: 'React',
      database: 'PostgreSQL',
      cloud: 'AWS',
    },
    phases: phasesUpTo(newFeaturePhases, 4, 'waiting'),
    verdict: 'NOT_VERIFIED',
    progress: 48,
    costUsd: 310,
    budgetUsd: 2500,
    tokens: 9_700_000,
    rules: { total: 42, approved: 42, verified: 0 },
    openQuestions: 3,
    artifactLanguage: 'es',
    owner: 'Ana Vélez',
    updatedAt: '2026-09-27T21:05:00Z',
  },
  {
    id: 'p5',
    tenantId: 't3',
    name: 'Loan Simulator — new feature',
    flow: 'newFeature',
    sources: ['Screenshots', 'Functional document (Word)'],
    target: { architecture: 'MVC', backend: 'Next.js', frontend: 'Next.js', database: 'MySQL', cloud: 'GCP' },
    phases: phasesUpTo(newFeaturePhases, 9, 'done'),
    verdict: 'PROVEN',
    progress: 100,
    costUsd: 205,
    budgetUsd: 800,
    tokens: 6_100_000,
    rules: { total: 18, approved: 18, verified: 18 },
    openQuestions: 0,
    artifactLanguage: 'en',
    owner: 'Carlos Ruiz',
    updatedAt: '2026-09-20T16:00:00Z',
  },
]

export const agents: AgentDefinition[] = [
  {
    id: 'legacy-analyst',
    name: 'Legacy analyst',
    nameEs: 'Analista legacy',
    group: 'analysis',
    description: 'Builds the inventory and dependency map of the legacy system and flags risky areas.',
    descriptionEs: 'Construye el inventario y el mapa de dependencias del legacy y señala las zonas de riesgo.',
    phases: ['inventory', 'domains', 'classification'],
    capabilities: ['longContext', 'structuredOutput'],
    tools: ['readGraph', 'readCode'],
    mandatory: false,
    level: 'certified',
    version: '1.4.0',
    defaultProfile: 'fast-analysis',
    relativeCost: 1,
  },
  {
    id: 'rules-extractor',
    name: 'Business rules extractor',
    nameEs: 'Extractor de reglas de negocio',
    group: 'analysis',
    description: 'Turns program slices into business rules with concrete Given/When/Then and exact source citations.',
    descriptionEs:
      'Convierte slices de programa en reglas de negocio con Given/When/Then concretos y citas exactas al fuente.',
    phases: ['ruleExtraction'],
    capabilities: ['longContext', 'structuredOutput'],
    tools: ['readGraph', 'readCode'],
    mandatory: false,
    level: 'certified',
    version: '2.1.0',
    defaultProfile: 'deep-analysis',
    relativeCost: 3,
  },
  {
    id: 'data-analyst',
    name: 'Data analyst',
    nameEs: 'Analista de datos',
    group: 'analysis',
    description: 'Maps copybooks, tables and files to neutral types, including COMP-3, zoned and EBCDIC semantics.',
    descriptionEs:
      'Mapea copybooks, tablas y archivos a tipos neutrales, incluida la semántica COMP-3, zoned y EBCDIC.',
    phases: ['inventory', 'design'],
    capabilities: ['structuredOutput'],
    tools: ['readGraph', 'readCode'],
    mandatory: false,
    level: 'certified',
    version: '1.2.0',
    defaultProfile: 'fast-analysis',
    relativeCost: 1,
  },
  {
    id: 'ui-analyst',
    name: 'UI analyst',
    nameEs: 'Analista de UI',
    group: 'analysis',
    description: 'Reads BMS maps, ASPX pages, Figma files and screenshots into screen specifications.',
    descriptionEs: 'Lee mapas BMS, páginas ASPX, Figma y capturas y los convierte en especificaciones de pantalla.',
    phases: ['ui', 'normalization'],
    capabilities: ['vision', 'structuredOutput'],
    tools: ['readGraph', 'readInputs'],
    mandatory: false,
    level: 'certified',
    version: '1.1.0',
    defaultProfile: 'vision',
    relativeCost: 2,
  },
  {
    id: 'functional-analyst',
    name: 'Functional analyst',
    nameEs: 'Analista funcional',
    group: 'analysis',
    description: 'Normalizes user stories, manuals and documents, and detects gaps and contradictions.',
    descriptionEs: 'Normaliza historias de usuario, manuales y documentos, y detecta huecos y contradicciones.',
    phases: ['ingestion', 'normalization', 'consolidation'],
    capabilities: ['longContext', 'vision', 'structuredOutput'],
    tools: ['readInputs', 'readGraph'],
    mandatory: false,
    level: 'assisted',
    version: '0.9.0',
    defaultProfile: 'deep-analysis',
    relativeCost: 2,
  },
  {
    id: 'solution-architect',
    name: 'Solution architect',
    nameEs: 'Arquitecto de soluciones',
    group: 'design',
    description: 'Proposes bounded contexts, contracts and ADRs, and checks the compatibility matrix.',
    descriptionEs: 'Propone bounded contexts, contratos y ADR, y revisa la matriz de compatibilidad.',
    phases: ['domains', 'design'],
    capabilities: ['longContext', 'structuredOutput'],
    tools: ['readGraph'],
    mandatory: false,
    level: 'certified',
    version: '1.3.0',
    defaultProfile: 'deep-analysis',
    relativeCost: 2,
  },
  {
    id: 'data-architect',
    name: 'Data architect',
    nameEs: 'Arquitecto de datos',
    group: 'design',
    description: 'Designs the target data model, aggregates and the data migration plan.',
    descriptionEs: 'Diseña el modelo de datos destino, los agregados y el plan de migración de datos.',
    phases: ['design'],
    capabilities: ['structuredOutput'],
    tools: ['readGraph'],
    mandatory: false,
    level: 'certified',
    version: '1.0.0',
    defaultProfile: 'deep-analysis',
    relativeCost: 2,
  },
  {
    id: 'ux-designer',
    name: 'UX/UI designer',
    nameEs: 'Diseñador UX/UI',
    group: 'design',
    description: 'Proposes a design system and clickable prototypes when no Figma is provided.',
    descriptionEs: 'Propone un design system y prototipos navegables cuando no hay Figma.',
    phases: ['ui'],
    capabilities: ['vision', 'toolCalling'],
    tools: ['writeWorkspace', 'sandbox'],
    mandatory: false,
    level: 'assisted',
    version: '0.8.0',
    defaultProfile: 'codegen',
    relativeCost: 2,
  },
  {
    id: 'backend-dev',
    name: 'Backend developer',
    nameEs: 'Desarrollador backend',
    group: 'build',
    description: 'Generates domain, adapters and APIs from the approved specification, layer by layer.',
    descriptionEs: 'Genera dominio, adaptadores y APIs desde la especificación aprobada, capa por capa.',
    phases: ['generation'],
    capabilities: ['toolCalling', 'longContext'],
    tools: ['writeWorkspace', 'sandbox'],
    mandatory: false,
    level: 'certified',
    version: '1.5.0',
    defaultProfile: 'codegen',
    relativeCost: 3,
  },
  {
    id: 'frontend-dev',
    name: 'Frontend developer',
    nameEs: 'Desarrollador frontend',
    group: 'build',
    description: 'Builds screens with the approved design system and the typed API client.',
    descriptionEs: 'Construye las pantallas con el design system aprobado y el cliente tipado de la API.',
    phases: ['generation'],
    capabilities: ['toolCalling', 'vision'],
    tools: ['writeWorkspace', 'sandbox'],
    mandatory: false,
    level: 'certified',
    version: '1.2.0',
    defaultProfile: 'codegen',
    relativeCost: 2,
  },
  {
    id: 'fullstack-dev',
    name: 'Full stack developer',
    nameEs: 'Desarrollador full stack',
    group: 'build',
    description: 'Covers backend and frontend with one shared context. Less parallelism, fewer hand-offs.',
    descriptionEs: 'Cubre backend y frontend con un solo contexto. Menos paralelismo, menos traspasos.',
    phases: ['generation'],
    capabilities: ['toolCalling', 'longContext', 'vision'],
    tools: ['writeWorkspace', 'sandbox'],
    mandatory: false,
    level: 'assisted',
    version: '0.9.0',
    defaultProfile: 'codegen',
    relativeCost: 3,
  },
  {
    id: 'data-migration',
    name: 'Data migration engineer',
    nameEs: 'Ingeniero de migración de datos',
    group: 'build',
    description: 'Generates and tests the data conversion from VSAM or legacy tables to the target database.',
    descriptionEs: 'Genera y prueba la conversión de datos desde VSAM o tablas legacy hacia la base destino.',
    phases: ['generation'],
    capabilities: ['toolCalling'],
    tools: ['writeWorkspace', 'sandbox'],
    mandatory: false,
    level: 'assisted',
    version: '0.7.0',
    defaultProfile: 'codegen',
    relativeCost: 2,
  },
  {
    id: 'devops',
    name: 'DevOps / cloud engineer',
    nameEs: 'Ingeniero DevOps / cloud',
    group: 'build',
    description: 'Produces IaC, pipelines and the strangler-fig routing plan for the chosen cloud.',
    descriptionEs: 'Produce IaC, pipelines y el plan de enrutamiento strangler fig para la nube elegida.',
    phases: ['delivery'],
    capabilities: ['toolCalling'],
    tools: ['writeWorkspace', 'sandbox'],
    mandatory: false,
    level: 'assisted',
    version: '0.8.0',
    defaultProfile: 'codegen',
    relativeCost: 1,
  },
  {
    id: 'test-engineer',
    name: 'Test engineer',
    nameEs: 'Ingeniero de pruebas',
    group: 'quality',
    description: 'Writes characterization and acceptance tests that pin every rule id before code is generated.',
    descriptionEs: 'Escribe pruebas de caracterización y aceptación que fijan cada regla antes de generar código.',
    phases: ['characterization', 'validation'],
    capabilities: ['toolCalling'],
    tools: ['writeWorkspace', 'sandbox'],
    mandatory: false,
    level: 'certified',
    version: '1.6.0',
    defaultProfile: 'codegen',
    relativeCost: 2,
  },
  {
    id: 'code-reviewer',
    name: 'Code reviewer',
    nameEs: 'Revisor de código',
    group: 'quality',
    description: 'Reviews generated code against the target conventions and the customer constitution.',
    descriptionEs: 'Revisa el código generado contra las convenciones del destino y la constitución del cliente.',
    phases: ['generation'],
    capabilities: ['longContext'],
    tools: ['readWorkspace'],
    mandatory: false,
    level: 'certified',
    version: '1.1.0',
    defaultProfile: 'review',
    relativeCost: 1,
  },
  {
    id: 'security-auditor',
    name: 'Security auditor',
    nameEs: 'Auditor de seguridad',
    group: 'quality',
    description: 'Scans legacy and generated code for OWASP issues, secrets and vulnerable dependencies.',
    descriptionEs:
      'Analiza el código legacy y el generado en busca de problemas OWASP, secretos y dependencias vulnerables.',
    phases: ['hardening'],
    capabilities: ['toolCalling'],
    tools: ['readWorkspace', 'sandbox'],
    mandatory: false,
    level: 'certified',
    version: '1.2.0',
    defaultProfile: 'review',
    relativeCost: 1,
  },
  {
    id: 'rules-verifier',
    name: 'Rules verifier',
    nameEs: 'Verificador de reglas',
    group: 'control',
    description: 'Independently checks every citation and that each rule explains its whole slice.',
    descriptionEs: 'Verifica de forma independiente cada cita y que cada regla explique todo su slice.',
    phases: ['ruleExtraction', 'consolidation'],
    capabilities: ['longContext', 'structuredOutput'],
    tools: ['readGraph', 'readCode'],
    mandatory: true,
    level: 'certified',
    version: '1.3.0',
    defaultProfile: 'review',
    relativeCost: 2,
  },
  {
    id: 'equivalence-validator',
    name: 'Equivalence validator',
    nameEs: 'Validador de equivalencia',
    group: 'control',
    description: 'Re-runs tests from clean, compares outputs, invents fresh inputs and runs the canary.',
    descriptionEs: 'Re-ejecuta las pruebas desde cero, compara salidas, inventa inputs nuevos y corre el canario.',
    phases: ['verification'],
    capabilities: ['toolCalling'],
    tools: ['readWorkspace', 'sandbox'],
    mandatory: true,
    level: 'certified',
    version: '1.4.0',
    defaultProfile: 'review',
    relativeCost: 2,
  },
  {
    id: 'acceptance-judge',
    name: 'Acceptance judge',
    nameEs: 'Juez de aceptación',
    group: 'control',
    description: 'Runs acceptance, contract and visual checks against the approved specification.',
    descriptionEs: 'Ejecuta las pruebas de aceptación, contrato y fidelidad visual contra la especificación aprobada.',
    phases: ['validation'],
    capabilities: ['toolCalling', 'vision'],
    tools: ['readWorkspace', 'sandbox'],
    mandatory: true,
    level: 'certified',
    version: '1.0.0',
    defaultProfile: 'review',
    relativeCost: 2,
  },
]

export const skills: SkillDefinition[] = [
  {
    id: 'cobol-data-semantics',
    name: 'COBOL data semantics',
    type: 'source',
    description: 'COMP-3, zoned decimals, EBCDIC, REDEFINES and sort-order pitfalls.',
    appliesTo: ['data-analyst', 'rules-extractor'],
    tags: ['COBOL', 'COBOL CICS'],
    conflictsWith: [],
    version: '1.3.0',
    evalScore: 0.95,
    status: 'published',
  },
  {
    id: 'exec-cics',
    name: 'EXEC CICS commands',
    type: 'source',
    description: 'LINK, XCTL, READ, SYNCPOINT and pseudo-conversational state.',
    appliesTo: ['legacy-analyst', 'rules-extractor'],
    tags: ['COBOL CICS'],
    conflictsWith: [],
    version: '1.1.0',
    evalScore: 0.91,
    status: 'published',
  },
  {
    id: 'bms-parsing',
    name: 'BMS map parsing',
    type: 'source',
    description: 'DFHMSD/DFHMDI/DFHMDF fields, positions, lengths and attributes.',
    appliesTo: ['ui-analyst'],
    tags: ['BMS maps'],
    conflictsWith: [],
    version: '1.0.2',
    evalScore: 0.99,
    status: 'published',
  },
  {
    id: 'sybase-tsql',
    name: 'Sybase T-SQL',
    type: 'source',
    description: 'Temp tables, cursors, @@error, chained mode and implicit conversions.',
    appliesTo: ['legacy-analyst', 'rules-extractor', 'data-analyst'],
    tags: ['Sybase ASE stored procedures'],
    conflictsWith: [],
    version: '0.9.0',
    evalScore: 0.88,
    status: 'published',
  },
  {
    id: 'webforms',
    name: 'ASP.NET WebForms',
    type: 'source',
    description: 'ViewState, postbacks, code-behind, server controls and web.config.',
    appliesTo: ['legacy-analyst', 'ui-analyst', 'rules-extractor'],
    tags: ['ASP.NET WebForms'],
    conflictsWith: [],
    version: '0.6.0',
    evalScore: null,
    status: 'evaluating',
  },
  {
    id: 'spring-hexagonal',
    name: 'Spring Boot hexagonal',
    type: 'target',
    description: 'Ports and adapters layout, conventions and test setup for Spring Boot.',
    appliesTo: ['backend-dev', 'fullstack-dev', 'code-reviewer'],
    tags: ['Java Spring Boot'],
    conflictsWith: ['quarkus'],
    version: '2.0.0',
    evalScore: 0.93,
    status: 'published',
  },
  {
    id: 'quarkus',
    name: 'Quarkus services',
    type: 'target',
    description: 'Quarkus layout, Panache persistence and native build settings.',
    appliesTo: ['backend-dev', 'fullstack-dev', 'code-reviewer'],
    tags: ['Java Quarkus'],
    conflictsWith: ['spring-hexagonal'],
    version: '1.0.0',
    evalScore: 0.86,
    status: 'published',
  },
  {
    id: 'dotnet10',
    name: '.NET 10 minimal APIs',
    type: 'target',
    description: 'Minimal APIs, EF Core and hexagonal layout for .NET 10.',
    appliesTo: ['backend-dev', 'fullstack-dev', 'code-reviewer'],
    tags: ['.NET 10'],
    conflictsWith: [],
    version: '1.1.0',
    evalScore: 0.9,
    status: 'published',
  },
  {
    id: 'angular-material',
    name: 'Angular + Material',
    type: 'target',
    description: 'Standalone components, typed forms and Angular Material.',
    appliesTo: ['frontend-dev', 'fullstack-dev'],
    tags: ['Angular'],
    conflictsWith: [],
    version: '1.2.0',
    evalScore: 0.89,
    status: 'published',
  },
  {
    id: 'react-ds',
    name: 'React + design system',
    type: 'target',
    description: 'React with the approved design system and a generated typed API client.',
    appliesTo: ['frontend-dev', 'fullstack-dev', 'ux-designer'],
    tags: ['React', 'Next.js'],
    conflictsWith: [],
    version: '1.3.0',
    evalScore: 0.9,
    status: 'published',
  },
  {
    id: 'postgres',
    name: 'PostgreSQL persistence',
    type: 'target',
    description: 'Schema, migrations, NUMERIC precision and collation rules.',
    appliesTo: ['data-architect', 'backend-dev', 'data-migration'],
    tags: ['PostgreSQL'],
    conflictsWith: [],
    version: '1.4.0',
    evalScore: 0.94,
    status: 'published',
  },
  {
    id: 'aws-iac',
    name: 'AWS IaC',
    type: 'target',
    description: 'Terraform modules for ECS/EKS, RDS, Step Functions and KMS.',
    appliesTo: ['devops'],
    tags: ['AWS'],
    conflictsWith: [],
    version: '0.9.0',
    evalScore: null,
    status: 'published',
  },
  {
    id: 'azure-iac',
    name: 'Azure IaC',
    type: 'target',
    description: 'Terraform modules for AKS, Azure Database, Logic Apps and Key Vault.',
    appliesTo: ['devops'],
    tags: ['Azure'],
    conflictsWith: [],
    version: '0.8.0',
    evalScore: null,
    status: 'published',
  },
  {
    id: 'cics-to-rest',
    name: 'CICS pseudo-conversational → REST',
    type: 'conversion',
    description: 'Maps COMMAREA state and transactions to stateless REST services.',
    appliesTo: ['solution-architect', 'backend-dev'],
    tags: ['COBOL CICS'],
    conflictsWith: [],
    version: '1.0.0',
    evalScore: 0.87,
    status: 'published',
  },
  {
    id: 'bms-to-forms',
    name: 'BMS → modern forms',
    type: 'conversion',
    description: 'Turns 3270 fields and attributes into accessible web form components.',
    appliesTo: ['ux-designer', 'frontend-dev'],
    tags: ['BMS maps'],
    conflictsWith: [],
    version: '0.9.0',
    evalScore: 0.92,
    status: 'published',
  },
  {
    id: 'sybase-to-service',
    name: 'Sybase SP → service layer',
    type: 'conversion',
    description: 'Moves stored procedure logic into domain services with equivalent transactions.',
    appliesTo: ['solution-architect', 'backend-dev'],
    tags: ['Sybase ASE stored procedures'],
    conflictsWith: [],
    version: '0.8.0',
    evalScore: 0.84,
    status: 'published',
  },
  {
    id: 'vsam-to-postgres',
    name: 'VSAM → PostgreSQL',
    type: 'conversion',
    description: 'Key design, record layouts and data conversion scripts.',
    appliesTo: ['data-architect', 'data-migration'],
    tags: ['COBOL', 'COBOL CICS'],
    conflictsWith: [],
    version: '0.7.0',
    evalScore: null,
    status: 'evaluating',
  },
  {
    id: 'owasp',
    name: 'OWASP secure coding',
    type: 'crossCutting',
    description: 'Input validation, authZ checks, secrets handling and dependency hygiene.',
    appliesTo: ['backend-dev', 'frontend-dev', 'fullstack-dev', 'security-auditor', 'code-reviewer'],
    tags: ['*'],
    conflictsWith: [],
    version: '1.5.0',
    evalScore: 0.9,
    status: 'published',
  },
  {
    id: 'gherkin',
    name: 'Gherkin specifications',
    type: 'crossCutting',
    description: 'Concrete Given/When/Then scenarios with real values.',
    appliesTo: ['rules-extractor', 'functional-analyst', 'test-engineer'],
    tags: ['*'],
    conflictsWith: [],
    version: '1.2.0',
    evalScore: 0.93,
    status: 'published',
  },
  {
    id: 'golden-master',
    name: 'Golden master testing',
    type: 'crossCutting',
    description: 'Recording legacy outputs, masks, tolerances and fresh inputs.',
    appliesTo: ['test-engineer', 'equivalence-validator'],
    tags: ['*'],
    conflictsWith: [],
    version: '1.1.0',
    evalScore: 0.96,
    status: 'published',
  },
  {
    id: 'wcag',
    name: 'WCAG 2.1 AA',
    type: 'crossCutting',
    description: 'Accessible forms, contrast, keyboard navigation and ARIA.',
    appliesTo: ['ux-designer', 'frontend-dev', 'acceptance-judge'],
    tags: ['*'],
    conflictsWith: [],
    version: '1.0.0',
    evalScore: 0.88,
    status: 'published',
  },
  {
    id: 'andes-conventions',
    name: 'Andes Bank conventions',
    type: 'customer',
    description: 'Naming, logging, error codes and audit fields required by the customer.',
    appliesTo: ['backend-dev', 'frontend-dev', 'fullstack-dev', 'code-reviewer'],
    tags: ['*'],
    conflictsWith: [],
    version: '1.0.0',
    evalScore: null,
    status: 'published',
  },
]

export const connections: ProviderConnection[] = [
  {
    id: 'c1',
    provider: 'azureFoundry',
    name: 'Andes — Azure AI Foundry',
    region: 'eastus2',
    auth: 'Entra ID service principal',
    status: 'connected',
    models: 6,
    lastCheck: '2026-09-28T07:00:00Z',
  },
  {
    id: 'c2',
    provider: 'awsBedrock',
    name: 'Andes — AWS Bedrock',
    region: 'us-east-1',
    auth: 'IAM role (cross-account)',
    status: 'connected',
    models: 9,
    lastCheck: '2026-09-28T07:00:00Z',
  },
  {
    id: 'c3',
    provider: 'openai',
    name: 'NexTI — OpenAI API',
    region: 'global',
    auth: 'API key (Vault)',
    status: 'connected',
    models: 5,
    lastCheck: '2026-09-28T07:00:00Z',
  },
  {
    id: 'c4',
    provider: 'anthropic',
    name: 'NexTI — Anthropic API',
    region: 'global',
    auth: 'API key (Vault)',
    status: 'error',
    models: 0,
    lastCheck: '2026-09-28T06:58:00Z',
  },
  {
    id: 'c5',
    provider: 'vertex',
    name: 'Google Vertex AI',
    region: '—',
    auth: '—',
    status: 'notConfigured',
    models: 0,
    lastCheck: '',
  },
]

export const offerings: ModelOffering[] = [
  {
    id: 'o1',
    family: 'Claude',
    model: 'Claude Opus',
    version: '5.5',
    connectionId: 'c2',
    providerModelId: 'bedrock/claude-opus-5-5 (sample)',
    region: 'us-east-1',
    contextK: 200,
    capabilities: ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'],
    inputPerMTokUsd: 15,
    outputPerMTokUsd: 75,
    status: 'available',
  },
  {
    id: 'o2',
    family: 'Claude',
    model: 'Claude Sonnet',
    version: '5',
    connectionId: 'c1',
    providerModelId: 'deployment: andes-sonnet-5',
    region: 'eastus2',
    contextK: 200,
    capabilities: ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'],
    inputPerMTokUsd: 3,
    outputPerMTokUsd: 15,
    status: 'available',
  },
  {
    id: 'o3',
    family: 'Claude',
    model: 'Claude Sonnet',
    version: '5',
    connectionId: 'c2',
    providerModelId: 'bedrock/claude-sonnet-5 (sample)',
    region: 'us-east-1',
    contextK: 200,
    capabilities: ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'],
    inputPerMTokUsd: 3,
    outputPerMTokUsd: 15,
    status: 'available',
  },
  {
    id: 'o4',
    family: 'Claude',
    model: 'Claude Haiku',
    version: '4.5',
    connectionId: 'c2',
    providerModelId: 'bedrock/claude-haiku-4-5 (sample)',
    region: 'us-east-1',
    contextK: 200,
    capabilities: ['toolCalling', 'vision', 'structuredOutput'],
    inputPerMTokUsd: 1,
    outputPerMTokUsd: 5,
    status: 'available',
  },
  {
    id: 'o5',
    family: 'GPT',
    model: 'GPT (large)',
    version: 'sample-2026-06',
    connectionId: 'c3',
    providerModelId: 'gpt-large-sample',
    region: 'global',
    contextK: 256,
    capabilities: ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'],
    inputPerMTokUsd: 5,
    outputPerMTokUsd: 20,
    status: 'available',
  },
  {
    id: 'o6',
    family: 'GPT',
    model: 'GPT (mini)',
    version: 'sample-2026-06',
    connectionId: 'c3',
    providerModelId: 'gpt-mini-sample',
    region: 'global',
    contextK: 128,
    capabilities: ['toolCalling', 'vision', 'structuredOutput'],
    inputPerMTokUsd: 0.5,
    outputPerMTokUsd: 2,
    status: 'available',
  },
  {
    id: 'o7',
    family: 'GPT',
    model: 'GPT (large)',
    version: 'sample-2026-06',
    connectionId: 'c1',
    providerModelId: 'deployment: andes-gpt-large',
    region: 'eastus2',
    contextK: 256,
    capabilities: ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'],
    inputPerMTokUsd: 5.5,
    outputPerMTokUsd: 22,
    status: 'available',
  },
]

export const profiles: ModelProfile[] = [
  {
    id: 'deep-analysis',
    name: 'Deep analysis',
    offeringId: 'o2',
    effort: 'high',
    providerParameter: 'effort = high',
    maxOutputTokens: 32000,
    fallbackOfferingId: 'o3',
  },
  {
    id: 'fast-analysis',
    name: 'Fast analysis',
    offeringId: 'o4',
    effort: 'low',
    providerParameter: 'effort = low',
    maxOutputTokens: 8000,
    fallbackOfferingId: 'o6',
  },
  {
    id: 'codegen',
    name: 'Code generation',
    offeringId: 'o3',
    effort: 'medium',
    providerParameter: 'effort = medium',
    maxOutputTokens: 64000,
    fallbackOfferingId: 'o2',
  },
  {
    id: 'review',
    name: 'Independent review',
    offeringId: 'o5',
    effort: 'high',
    providerParameter: 'reasoning_effort = high',
    maxOutputTokens: 16000,
    fallbackOfferingId: 'o7',
  },
  {
    id: 'vision',
    name: 'Vision',
    offeringId: 'o5',
    effort: 'medium',
    providerParameter: 'reasoning_effort = medium',
    maxOutputTokens: 16000,
    fallbackOfferingId: 'o2',
  },
  {
    id: 'max-reasoning',
    name: 'Maximum reasoning',
    offeringId: 'o1',
    effort: 'max',
    providerParameter: 'effort = max',
    maxOutputTokens: 64000,
    fallbackOfferingId: 'o2',
  },
]

export const monthlyCost = [
  { month: '2026-04', usd: 820 },
  { month: '2026-05', usd: 1310 },
  { month: '2026-06', usd: 1880 },
  { month: '2026-07', usd: 2460 },
  { month: '2026-08', usd: 3920 },
  { month: '2026-09', usd: 5700 },
]

export const costByProvider = [
  { key: 'awsBedrock', usd: 2860 },
  { key: 'azureFoundry', usd: 1730 },
  { key: 'openai', usd: 1110 },
]

export const costByPhase = [
  { key: 'ruleExtraction', usd: 1190 },
  { key: 'generation', usd: 980 },
  { key: 'verification', usd: 540 },
  { key: 'inventory', usd: 210 },
  { key: 'ui', usd: 180 },
  { key: 'design', usd: 160 },
]

export const costByAgent = [
  { key: 'rules-extractor', usd: 1120 },
  { key: 'backend-dev', usd: 760 },
  { key: 'rules-verifier', usd: 420 },
  { key: 'equivalence-validator', usd: 390 },
  { key: 'test-engineer', usd: 310 },
  { key: 'ui-analyst', usd: 170 },
]

export const rules: Rule[] = [
  {
    id: 'RULE-001',
    name: 'Credit limit check on purchase',
    domain: 'Authorizations',
    category: 'validation',
    priority: 'P0',
    confidence: 'high',
    status: 'approved',
    statement: 'A purchase is declined when it would take the balance over the credit limit.',
    given: 'an account with limit 5,000.00 and balance 4,900.00',
    when: 'a purchase of 150.00 is authorized',
    then: 'the purchase is declined with reason code 51',
    source: 'COCRDUPC.cbl:412-438',
    testStatus: 'namedNotRun',
  },
  {
    id: 'RULE-002',
    name: 'Daily interest accrual',
    domain: 'Interest',
    category: 'calculation',
    priority: 'P0',
    confidence: 'high',
    status: 'approved',
    statement: 'Daily interest is balance × annual rate ÷ 360, rounded half-up to 2 decimals.',
    given: 'a balance of 12,345.67 and an annual rate of 18.5%',
    when: 'the nightly accrual runs',
    then: 'interest of 6.34 is posted',
    source: 'CBACT04C.cbl:233-260',
    testStatus: 'namedNotRun',
  },
  {
    id: 'RULE-003',
    name: 'Card expiry validation',
    domain: 'Cards',
    category: 'validation',
    priority: 'P1',
    confidence: 'medium',
    status: 'question',
    statement: 'A card cannot be activated after its expiry month.',
    given: 'a card expiring 2026-08',
    when: 'activation is requested on 2026-09-02',
    then: 'activation is rejected',
    source: 'COCRDUPC.cbl:510-527',
    smeQuestion: 'Is the expiry inclusive of the last day of the month?',
    testStatus: 'none',
  },
  {
    id: 'RULE-004',
    name: 'Late fee on missed minimum payment',
    domain: 'Billing',
    category: 'policy',
    priority: 'P0',
    confidence: 'medium',
    status: 'inReview',
    statement: 'A late fee of 25.00 is charged when the minimum payment is not received by the due date.',
    given: 'a statement with minimum payment 80.00 due 2026-09-10',
    when: 'no payment is received by 2026-09-10',
    then: 'a late fee of 25.00 is posted on 2026-09-11',
    source: 'CBSTM03A.cbl:118-141',
    testStatus: 'none',
  },
  {
    id: 'RULE-005',
    name: 'Account status transitions',
    domain: 'Accounts',
    category: 'lifecycle',
    priority: 'P1',
    confidence: 'high',
    status: 'approved',
    statement: 'Only active accounts can be suspended; suspended accounts can be reactivated or closed.',
    given: 'a suspended account',
    when: 'a reactivation is requested',
    then: 'the account becomes active',
    source: 'COACTUPC.cbl:640-702',
    testStatus: 'namedNotRun',
  },
  {
    id: 'RULE-006',
    name: 'Customer name mandatory fields',
    domain: 'Customers',
    category: 'validation',
    priority: 'P2',
    confidence: 'high',
    status: 'draft',
    statement: 'First and last names are mandatory and alphabetic.',
    given: 'a customer update with last name "O2"',
    when: 'the update is submitted',
    then: 'the field is rejected with message "Last name must be alphabetic"',
    source: 'COACTUPC.cbl:1102-1130',
    testStatus: 'none',
  },
]

export const runEvents: RunEvent[] = [
  {
    id: 'e1',
    time: '09:14:02',
    agent: 'Business rules extractor',
    phase: 'ruleExtraction',
    kind: 'fanOut',
    detail: '12 subagents launched, one per shard (ACCT, CARD, AUTH, BILL…).',
  },
  {
    id: 'e2',
    time: '09:21:40',
    agent: 'Business rules extractor',
    phase: 'ruleExtraction',
    kind: 'completed',
    detail: 'Shard AUTH: 23 candidate rules.',
    tokens: 1_240_000,
  },
  {
    id: 'e3',
    time: '09:22:05',
    agent: 'Rules verifier',
    phase: 'ruleExtraction',
    kind: 'verificationFailed',
    detail: 'RULE-017: citation COCRDUPC.cbl:980 does not support the stated threshold.',
  },
  {
    id: 'e4',
    time: '09:22:51',
    agent: 'Business rules extractor',
    phase: 'ruleExtraction',
    kind: 'selfCorrected',
    detail: 'RULE-017 corrected to cite COCRDUPC.cbl:1004-1011 (iteration 2 of 3).',
    tokens: 84_000,
  },
  {
    id: 'e5',
    time: '09:30:12',
    agent: 'Rules verifier',
    phase: 'ruleExtraction',
    kind: 'escalated',
    detail: 'RULE-031: two judges disagree on the rounding mode. Sent to the SME.',
  },
  {
    id: 'e6',
    time: '09:41:00',
    agent: 'Supervisor',
    phase: 'ruleReview',
    kind: 'gateWaiting',
    detail: 'Gate C1 — 148 rules waiting for business approval.',
  },
]

export const tasks: Task[] = [
  {
    id: 'k1',
    projectId: 'p1',
    kind: 'approveSpec',
    title: 'Approve 51 rules in Authorizations and Billing',
    due: '2026-09-30',
    priority: 'high',
  },
  {
    id: 'k7',
    projectId: 'p1',
    kind: 'reviewStories',
    title: 'Review 9 user stories and the migration plan before the migration starts',
    due: '2026-09-30',
    priority: 'high',
  },
  {
    id: 'k2',
    projectId: 'p1',
    kind: 'answerQuestion',
    title: 'RULE-003: is card expiry inclusive of the last day?',
    due: '2026-09-29',
    priority: 'normal',
  },
  {
    id: 'k3',
    projectId: 'p1',
    kind: 'escalation',
    title: 'RULE-031: judges disagree on the rounding mode',
    due: '2026-09-29',
    priority: 'high',
  },
  {
    id: 'k4',
    projectId: 'p4',
    kind: 'reviewPrototype',
    title: 'Review 8 onboarding prototypes and the design system',
    due: '2026-10-02',
    priority: 'normal',
  },
  {
    id: 'k5',
    projectId: 'p2',
    kind: 'signOff',
    title: 'Sign off the verification of module ACCRUAL',
    due: '2026-10-01',
    priority: 'normal',
  },
  {
    id: 'k6',
    projectId: 'p4',
    kind: 'approveArchitecture',
    title: 'Approve bounded contexts and OpenAPI contracts',
    due: '2026-10-05',
    priority: 'normal',
  },
]

export const users: User[] = [
  {
    id: 'u1',
    name: 'David Balseca',
    email: 'david.balseca@nexti.example',
    tenant: 'NexTI Internal',
    roles: ['superAdmin'],
    mfa: true,
    lastSeen: '2026-09-28T09:40:00Z',
    status: 'active',
  },
  {
    id: 'u2',
    name: 'María Torres',
    email: 'mtorres@andesbank.example',
    tenant: 'Andes Bank',
    roles: ['tenantAdmin', 'projectOwner'],
    mfa: true,
    lastSeen: '2026-09-28T09:12:00Z',
    status: 'active',
  },
  {
    id: 'u3',
    name: 'Luis Andrade',
    email: 'landrade@andesbank.example',
    tenant: 'Andes Bank',
    roles: ['architect'],
    mfa: true,
    lastSeen: '2026-09-28T08:30:00Z',
    status: 'active',
  },
  {
    id: 'u4',
    name: 'Ana Vélez',
    email: 'avelez@pacificcu.example',
    tenant: 'Pacific Credit Union',
    roles: ['businessReviewer'],
    mfa: true,
    lastSeen: '2026-09-27T20:10:00Z',
    status: 'active',
  },
  {
    id: 'u5',
    name: 'Jorge Mena',
    email: 'jmena@andesbank.example',
    tenant: 'Andes Bank',
    roles: ['auditor'],
    mfa: false,
    lastSeen: '',
    status: 'invited',
  },
  {
    id: 'u6',
    name: 'Carlos Ruiz',
    email: 'cruiz@nexti.example',
    tenant: 'NexTI Internal',
    roles: ['analyst', 'developer'],
    mfa: true,
    lastSeen: '2026-09-26T15:00:00Z',
    status: 'active',
  },
]

export const roles = [
  { id: 'superAdmin', scope: 'platform', members: 2, permissions: 42 },
  { id: 'supportOperator', scope: 'platform', members: 3, permissions: 12 },
  { id: 'tenantAdmin', scope: 'tenant', members: 4, permissions: 30 },
  { id: 'auditor', scope: 'tenant', members: 2, permissions: 8 },
  { id: 'finance', scope: 'tenant', members: 1, permissions: 5 },
  { id: 'projectOwner', scope: 'project', members: 5, permissions: 22 },
  { id: 'architect', scope: 'project', members: 4, permissions: 14 },
  { id: 'analyst', scope: 'project', members: 9, permissions: 12 },
  { id: 'businessReviewer', scope: 'project', members: 6, permissions: 7 },
  { id: 'developer', scope: 'project', members: 11, permissions: 9 },
  { id: 'observer', scope: 'project', members: 8, permissions: 3 },
]

export const permissionMatrix: { permission: string; roles: string[] }[] = [
  { permission: 'project.create', roles: ['superAdmin', 'tenantAdmin'] },
  { permission: 'project.configure', roles: ['superAdmin', 'tenantAdmin', 'projectOwner'] },
  { permission: 'input.upload', roles: ['superAdmin', 'tenantAdmin', 'projectOwner', 'analyst'] },
  { permission: 'pipeline.run', roles: ['superAdmin', 'projectOwner', 'analyst'] },
  { permission: 'gate.c1.approve', roles: ['projectOwner', 'businessReviewer'] },
  { permission: 'gate.c2.approve', roles: ['projectOwner', 'businessReviewer'] },
  { permission: 'gate.c3.approve', roles: ['architect'] },
  { permission: 'signoff.sign', roles: ['projectOwner', 'architect'] },
  { permission: 'code.view', roles: ['superAdmin', 'projectOwner', 'architect', 'analyst', 'developer', 'auditor'] },
  { permission: 'code.download', roles: ['projectOwner', 'developer'] },
  { permission: 'models.configure', roles: ['superAdmin', 'tenantAdmin'] },
  { permission: 'usage.view', roles: ['superAdmin', 'tenantAdmin', 'projectOwner', 'finance', 'auditor'] },
  { permission: 'cost.view', roles: ['superAdmin', 'tenantAdmin', 'finance'] },
  { permission: 'users.manage', roles: ['superAdmin', 'tenantAdmin'] },
  { permission: 'audit.view', roles: ['superAdmin', 'tenantAdmin', 'auditor'] },
]

export const auditLog: AuditEntry[] = [
  {
    id: 'a1',
    time: '2026-09-28T09:41:00Z',
    actor: 'Supervisor (agent)',
    action: 'gate.waiting',
    target: 'p1 / C1',
    tenant: 'Andes Bank',
  },
  {
    id: 'a2',
    time: '2026-09-28T09:12:00Z',
    actor: 'María Torres',
    action: 'rule.approve',
    target: 'p1 / RULE-001',
    tenant: 'Andes Bank',
  },
  {
    id: 'a3',
    time: '2026-09-28T08:55:00Z',
    actor: 'Luis Andrade',
    action: 'profile.update',
    target: 'p2 / codegen → effort medium',
    tenant: 'Andes Bank',
  },
  {
    id: 'a4',
    time: '2026-09-28T08:31:00Z',
    actor: 'David Balseca',
    action: 'connection.test',
    target: 'c4 Anthropic API (failed: 401)',
    tenant: 'NexTI Internal',
  },
  {
    id: 'a5',
    time: '2026-09-27T21:05:00Z',
    actor: 'Ana Vélez',
    action: 'input.upload',
    target: 'p4 / onboarding.fig',
    tenant: 'Pacific Credit Union',
  },
  {
    id: 'a6',
    time: '2026-09-27T18:20:00Z',
    actor: 'System',
    action: 'budget.alert80',
    target: 'p1 (80% of budget)',
    tenant: 'Andes Bank',
  },
  {
    id: 'a7',
    time: '2026-09-27T17:02:00Z',
    actor: 'María Torres',
    action: 'user.invite',
    target: 'jmena@andesbank.example (auditor)',
    tenant: 'Andes Bank',
  },
]

export const identityProviders = [
  {
    id: 'idp1',
    tenant: 'Andes Bank',
    type: 'Microsoft Entra ID (OIDC)',
    domains: ['andesbank.example'],
    enforced: true,
    status: 'active',
  },
  {
    id: 'idp2',
    tenant: 'Pacific Credit Union',
    type: 'Okta (SAML 2.0)',
    domains: ['pacificcu.example'],
    enforced: false,
    status: 'active',
  },
  {
    id: 'idp3',
    tenant: 'NexTI Internal',
    type: 'Google Workspace (OIDC)',
    domains: ['nexti.example'],
    enforced: false,
    status: 'active',
  },
]

export const workers = [
  { id: 'w-analysis-1', pool: 'analysis', status: 'busy', jobs: 12, cpu: 71 },
  { id: 'w-analysis-2', pool: 'analysis', status: 'busy', jobs: 9, cpu: 64 },
  { id: 'w-codegen-1', pool: 'codegen', status: 'idle', jobs: 0, cpu: 4 },
  { id: 'w-sandbox-linux-1', pool: 'sandbox', status: 'busy', jobs: 3, cpu: 88 },
  { id: 'w-sandbox-win-1', pool: 'sandbox-windows', status: 'offline', jobs: 0, cpu: 0 },
]

export const deployments = [
  { id: 'd1', name: 'Shared SaaS (us-east)', model: 'sharedSaas', version: '0.1.0', tenants: 2, status: 'healthy' },
  {
    id: 'd2',
    name: 'Andes Bank data plane (customer AWS)',
    model: 'customerCloud',
    version: '0.1.0',
    tenants: 1,
    status: 'healthy',
  },
  { id: 'd3', name: 'Staging', model: 'sharedSaas', version: '0.2.0-rc.1', tenants: 0, status: 'updating' },
]

// ---- Specification: screens, contracts and open questions (spec section 4.1) ----

export const screenSpecs = [
  {
    id: 'SCR-001',
    name: 'Update account',
    source: 'COACTUP.bms (map COACTUP)',
    status: 'approved' as const,
    fields: [
      {
        name: 'accountNumber',
        label: 'Account number',
        type: 'text(fixed, 11)',
        required: true,
        validation: 'Numeric, 11 digits',
        readOnly: true,
      },
      { name: 'status', label: 'Active Y/N', type: 'enum(Y,N)', required: true, validation: 'Y or N', readOnly: false },
      {
        name: 'creditLimit',
        label: 'Credit limit',
        type: 'decimal(11,2,signed)',
        required: true,
        validation: '0.00 – 99,999,999.99',
        readOnly: false,
      },
      {
        name: 'currentBalance',
        label: 'Current balance',
        type: 'decimal(11,2,signed)',
        required: false,
        validation: '—',
        readOnly: true,
      },
      {
        name: 'firstName',
        label: 'First name',
        type: 'text(var, 25)',
        required: true,
        validation: 'Alphabetic',
        readOnly: false,
      },
      {
        name: 'lastName',
        label: 'Last name',
        type: 'text(var, 25)',
        required: true,
        validation: 'Alphabetic (RULE-006)',
        readOnly: false,
      },
    ],
    actions: ['ENTER → Save', 'F3 → Exit', 'F5 → Refresh', 'F12 → Cancel'],
    states: ['empty', 'loading', 'error', 'success'],
  },
  {
    id: 'SCR-002',
    name: 'Card detail',
    source: 'COCRDUP.bms (map COCRDUP)',
    status: 'inReview' as const,
    fields: [
      {
        name: 'cardNumber',
        label: 'Card number',
        type: 'text(fixed, 16)',
        required: true,
        validation: 'Masked except last 4',
        readOnly: true,
      },
      {
        name: 'expiry',
        label: 'Expiry',
        type: 'date(YYYY-MM)',
        required: true,
        validation: 'RULE-003 (open question)',
        readOnly: false,
      },
      {
        name: 'embossedName',
        label: 'Name on card',
        type: 'text(var, 50)',
        required: true,
        validation: 'Uppercase letters and spaces',
        readOnly: false,
      },
    ],
    actions: ['ENTER → Save', 'F3 → Exit'],
    states: ['loading', 'error', 'success'],
  },
]

export const contracts = [
  {
    id: 'API-001',
    method: 'GET',
    path: '/accounts/{accountId}',
    service: 'account-service',
    rules: ['RULE-005'],
    status: 'approved' as const,
  },
  {
    id: 'API-002',
    method: 'PATCH',
    path: '/accounts/{accountId}',
    service: 'account-service',
    rules: ['RULE-001', 'RULE-006'],
    status: 'approved' as const,
  },
  {
    id: 'API-003',
    method: 'POST',
    path: '/authorizations',
    service: 'authorization-service',
    rules: ['RULE-001'],
    status: 'inReview' as const,
  },
  {
    id: 'API-004',
    method: 'GET',
    path: '/cards/{cardNumber}',
    service: 'card-service',
    rules: ['RULE-003'],
    status: 'draft' as const,
  },
  {
    id: 'API-005',
    method: 'POST',
    path: '/statements/{statementId}/late-fee',
    service: 'billing-service',
    rules: ['RULE-004'],
    status: 'draft' as const,
  },
]

export interface DecisionOption {
  id: string
  label: string
  rationale: string
  confidence: 'high' | 'medium' | 'low'
}

export interface Decision {
  id: string
  projectId: string
  question: string
  context: string
  raisedBy: string
  reason: 'lowConfidence' | 'contradiction' | 'judgesDisagree' | 'missingInfo'
  risk: 'high' | 'low'
  evidence: { label: string; ref: string }[]
  affects: string[]
  options: DecisionOption[]
  recommended: string
  owner: string
  status: 'open' | 'answered'
  answer?: string
  answeredBy?: string
}

// Questions raised by agents (spec 10.4 / 11.1). The first option is the platform's recommendation.
export const openQuestions: Decision[] = [
  {
    id: 'Q-001',
    projectId: 'p1',
    question: 'Is the card expiry inclusive of the last day of the month?',
    context:
      'COCRDUPC compares the expiry month with the current month using ">" — a card expiring 2026-08 is rejected from 2026-09-01.',
    raisedBy: 'Business rules extractor',
    reason: 'lowConfidence',
    risk: 'low',
    evidence: [
      { label: 'COCRDUPC.cbl:510-527', ref: 'code' },
      { label: 'RULE-003', ref: 'rule' },
    ],
    affects: ['RULE-003', 'SCR-002', 'API-004'],
    options: [
      {
        id: 'a',
        label: 'Yes — the card is valid until the last day of its expiry month',
        rationale: 'Matches the legacy comparison and the card network convention.',
        confidence: 'high',
      },
      {
        id: 'b',
        label: 'No — the card expires on the first day of its expiry month',
        rationale: 'Would change current behavior; needs a business decision.',
        confidence: 'low',
      },
    ],
    recommended: 'a',
    owner: 'María Torres',
    status: 'open',
  },
  {
    id: 'Q-002',
    projectId: 'p1',
    question: 'Which rounding mode must daily interest use?',
    context:
      'Two judges disagree: the ROUNDED clause implies HALF_UP, but the compiler option TRUNC(STD) could change it. The golden master was recorded with HALF_UP.',
    raisedBy: 'Rules verifier',
    reason: 'judgesDisagree',
    risk: 'high',
    evidence: [
      { label: 'CBACT04C.cbl:233-260', ref: 'code' },
      { label: 'Golden master case C14', ref: 'test' },
      { label: 'RULE-002, RULE-031', ref: 'rule' },
    ],
    affects: ['RULE-002', 'RULE-031', '12 tests'],
    options: [
      {
        id: 'a',
        label: 'HALF_UP (round half away from zero)',
        rationale: 'Consistent with the ROUNDED clause and the recorded golden master outputs.',
        confidence: 'high',
      },
      {
        id: 'b',
        label: 'HALF_EVEN (banker’s rounding)',
        rationale: 'Common in finance, but differs from 3 recorded outputs.',
        confidence: 'low',
      },
      {
        id: 'c',
        label: 'Truncate to 2 decimals',
        rationale: 'Only if the compiler option applies; no evidence in the traces.',
        confidence: 'low',
      },
    ],
    recommended: 'a',
    owner: 'Luis Andrade',
    status: 'open',
  },
  {
    id: 'Q-003',
    projectId: 'p1',
    question: 'Should the late fee be waived when the account is suspended?',
    context:
      'CBSTM03A charges the fee without checking the account status. The user manual (p. 18) says suspended accounts are not charged.',
    raisedBy: 'Business rules extractor',
    reason: 'contradiction',
    risk: 'high',
    evidence: [
      { label: 'CBSTM03A.cbl:118-141', ref: 'code' },
      { label: 'User manual p. 18', ref: 'doc' },
    ],
    affects: ['RULE-004', 'API-005'],
    options: [
      {
        id: 'a',
        label: 'Keep legacy behavior: charge the fee (flag as suspected defect)',
        rationale: 'Equivalence first; the manual can be fixed or the change done after go-live.',
        confidence: 'medium',
      },
      {
        id: 'b',
        label: 'Follow the manual: waive the fee for suspended accounts',
        rationale: 'Changes behavior; requires an approved difference in the verification.',
        confidence: 'medium',
      },
    ],
    recommended: 'a',
    owner: 'María Torres',
    status: 'open',
  },
  {
    id: 'Q-004',
    projectId: 'p1',
    question: 'Who can see the FICO score on the account screen?',
    context: 'The BMS map shows FICO to every user of the transaction. There is no role check in COACTUPC.',
    raisedBy: 'UI analyst',
    reason: 'missingInfo',
    risk: 'low',
    evidence: [{ label: 'COACTUP.bms: field FICOSCR', ref: 'code' }],
    affects: ['SCR-001'],
    options: [
      {
        id: 'a',
        label: 'Only credit analysts and supervisors',
        rationale: 'Least privilege for sensitive data.',
        confidence: 'medium',
      },
      {
        id: 'b',
        label: 'Everyone with access to the screen (as today)',
        rationale: 'Keeps current behavior.',
        confidence: 'medium',
      },
    ],
    recommended: 'a',
    owner: 'María Torres',
    status: 'answered',
    answer: 'Only credit analysts and supervisors',
    answeredBy: 'María Torres',
  },
]

// ---- Flow 2 (new feature): Figma frames and detected gaps ----

export const figmaFrames = [
  { id: 'F-01', name: 'Welcome', node: '12:340', mapped: 'SCR-101', gaps: 0 },
  { id: 'F-02', name: 'Personal data', node: '12:512', mapped: 'SCR-102', gaps: 2 },
  { id: 'F-03', name: 'ID document upload', node: '14:088', mapped: 'SCR-103', gaps: 1 },
  { id: 'F-04', name: 'Selfie check', node: '14:230', mapped: 'SCR-104', gaps: 1 },
  { id: 'F-05', name: 'Product selection', node: '15:002', mapped: 'SCR-105', gaps: 0 },
  { id: 'F-06', name: 'Terms and signature', node: '15:190', mapped: 'SCR-106', gaps: 0 },
  { id: 'F-07', name: 'Success', node: '16:010', mapped: 'SCR-107', gaps: 0 },
  { id: 'F-08', name: 'Error / retry', node: '—', mapped: '—', gaps: 1 },
]

export const detectedGaps = [
  {
    id: 'G-01',
    kind: 'missingValidation',
    target: 'F-02 · Date of birth',
    detail: 'No minimum age in the stories; the manual says 18.',
  },
  {
    id: 'G-02',
    kind: 'missingState',
    target: 'F-02 · Personal data',
    detail: 'No error state for an invalid national ID.',
  },
  {
    id: 'G-03',
    kind: 'deadEnd',
    target: 'F-03 · "Upload later"',
    detail: 'The button does not navigate anywhere in the prototype.',
  },
  {
    id: 'G-04',
    kind: 'contradiction',
    target: 'ONB-118 vs manual p. 12',
    detail: 'The story allows passports; the manual only national ID.',
  },
  { id: 'G-05', kind: 'missingFrame', target: 'Error / retry', detail: 'Referenced by ONB-131 but no frame exists.' },
]

// ---- Notifications ----

export const notifications = [
  {
    id: 'n1',
    kind: 'gate',
    text: 'Gate C1 is waiting for your approval in Card Management.',
    time: '2026-09-28T09:41:00Z',
    unread: true,
    projectId: 'p1',
    tab: 'specification',
  },
  {
    id: 'n2',
    kind: 'escalation',
    text: 'RULE-031 was escalated: judges disagree on the rounding mode.',
    time: '2026-09-28T09:30:00Z',
    unread: true,
    projectId: 'p1',
    tab: 'runs',
  },
  {
    id: 'n3',
    kind: 'budget',
    text: 'Card Management reached 80% of its budget.',
    time: '2026-09-27T18:20:00Z',
    unread: true,
    projectId: 'p1',
    tab: 'costs',
  },
  {
    id: 'n4',
    kind: 'verdict',
    text: 'Interest Accrual SP: verification finished — PARTLY PROVEN.',
    time: '2026-09-27T16:00:00Z',
    unread: false,
    projectId: 'p2',
    tab: 'validation',
  },
  {
    id: 'n5',
    kind: 'connection',
    text: 'Connection "NexTI — Anthropic API" failed its last check (401).',
    time: '2026-09-28T06:58:00Z',
    unread: false,
    projectId: null,
    tab: null,
  },
]

// ---- Agent invocation detail (Runs tab) ----

export const invocationDetails: Record<
  string,
  {
    profile: string
    model: string
    iteration: string
    durationS: number
    inputTokens: number
    outputTokens: number
    costUsd: number
    prompt: string
    response: string
    verification: string
  }
> = {
  e2: {
    profile: 'Deep analysis',
    model: 'Claude Sonnet 5 — Andes — Azure AI Foundry',
    iteration: '1 / 3',
    durationS: 458,
    inputTokens: 1_120_000,
    outputTokens: 120_000,
    costUsd: 5.16,
    prompt:
      'System: business-rules-extractor v2.1.0 (+ skills: COBOL data semantics, EXEC CICS, Gherkin)\nContext: graph slice for shard AUTH — 9 programs, 14 copybooks, 3 files\nTask: extract business rules with exact file:line citations and concrete Given/When/Then.',
    response: '23 candidate rules returned as structured JSON (rule cards). 2 flagged with medium confidence.',
    verification: 'Deterministic checks passed (schema, citations exist). Sent to the rules verifier.',
  },
  e3: {
    profile: 'Independent review',
    model: 'GPT (large) — NexTI — OpenAI API',
    iteration: '1 / 3',
    durationS: 41,
    inputTokens: 38_000,
    outputTokens: 2_100,
    costUsd: 0.23,
    prompt:
      'System: rules-verifier v1.3.0\nTask: check that RULE-017 is supported by its citation and explains the whole slice.',
    response: 'FAIL — the cited line COCRDUPC.cbl:980 moves a status code; the threshold 500.00 is set at 1004-1011.',
    verification: 'Verdict returned to the extractor for self-correction.',
  },
  e4: {
    profile: 'Deep analysis',
    model: 'Claude Sonnet 5 — Andes — Azure AI Foundry',
    iteration: '2 / 3',
    durationS: 46,
    inputTokens: 80_000,
    outputTokens: 4_000,
    costUsd: 0.3,
    prompt: 'System: business-rules-extractor v2.1.0\nTask: correct RULE-017 using the verifier finding.',
    response: 'RULE-017 now cites COCRDUPC.cbl:1004-1011 with threshold 500.00.',
    verification: 'Verifier re-check: PASS.',
  },
  e5: {
    profile: 'Independent review',
    model: 'GPT (large) — NexTI — OpenAI API',
    iteration: '3 / 3',
    durationS: 63,
    inputTokens: 52_000,
    outputTokens: 3_300,
    costUsd: 0.33,
    prompt: 'System: rules-verifier v1.3.0 (two-judge panel for P0)\nTask: confirm the rounding mode of RULE-031.',
    response: 'Judge A: HALF_UP (ROUNDED clause). Judge B: HALF_EVEN (compiler option). No agreement.',
    verification: 'Max iterations reached → escalated to a person (question Q-002).',
  },
}

// ---- Generated code (Code tab) ----

export const codeFiles: Record<string, string> = {
  'Account.java': `package com.andesbank.account.domain;

/** Aggregate root for an account. RULE-005 (status transitions). */
public final class Account {
  private final AccountId id;
  private AccountStatus status;
  private Money creditLimit;
  private Money currentBalance;

  public void suspend() {
    if (status != AccountStatus.ACTIVE) throw new DomainException("ACCOUNT_NOT_ACTIVE");
    status = AccountStatus.SUSPENDED;
  }

  public void reactivate() {
    if (status != AccountStatus.SUSPENDED) throw new DomainException("ACCOUNT_NOT_SUSPENDED");
    status = AccountStatus.ACTIVE;
  }
}`,
  'CreditLimitPolicy.java': `package com.andesbank.account.domain;

/**
 * RULE-001 Credit limit check on purchase.
 * Source: COCRDUPC.cbl:412-438
 */
public final class CreditLimitPolicy {

  public Decision evaluate(Money balance, Money limit, Money purchase) {
    if (balance.plus(purchase).isGreaterThan(limit)) {
      return Decision.decline(ReasonCode.OVER_LIMIT); // 51
    }
    return Decision.approve();
  }
}`,
  'UpdateAccountUseCase.java': `package com.andesbank.account.application;

/** Use case behind PATCH /accounts/{accountId} (API-002). RULE-001, RULE-006. */
public final class UpdateAccountUseCase {
  private final AccountRepository accounts;
  private final AuditPort audit;

  public Account handle(UpdateAccountCommand command) {
    Account account = accounts.findById(command.accountId()).orElseThrow(AccountNotFound::new);
    account.rename(PersonName.of(command.firstName(), command.lastName())); // RULE-006
    account.changeCreditLimit(command.creditLimit());
    accounts.save(account);
    audit.record("account.update", command.accountId());
    return account;
  }
}`,
  'AccountController.java': `package com.andesbank.account.adapters.web;

@RestController
@RequestMapping("/accounts")
class AccountController {
  private final UpdateAccountUseCase updateAccount;

  @PatchMapping("/{accountId}")
  AccountResponse update(@PathVariable String accountId, @Valid @RequestBody UpdateAccountRequest body) {
    return AccountResponse.from(updateAccount.handle(body.toCommand(accountId)));
  }
}`,
  'AccountJpaRepository.java': `package com.andesbank.account.adapters.persistence;

/** PostgreSQL adapter for AccountRepository. ACCTDAT (VSAM) → table account (ADR-003). */
interface AccountJpaRepository extends JpaRepository<AccountEntity, String> {}`,
  'CreditLimitPolicyTest.java': `package com.andesbank.account.domain;

class CreditLimitPolicyTest {

  @Test
  void rule001_declinesPurchaseOverLimit() {
    var decision = new CreditLimitPolicy().evaluate(money("4900.00"), money("5000.00"), money("150.00"));
    assertThat(decision.reason()).isEqualTo(ReasonCode.OVER_LIMIT);
  }

  @Test
  void rule001_approvesPurchaseAtLimit() {
    var decision = new CreditLimitPolicy().evaluate(money("4900.00"), money("5000.00"), money("100.00"));
    assertThat(decision.approved()).isTrue();
  }
}`,
}

// ---- Knowledge graph sample (Inventory tab). The real view queries Neo4j through the API. ----

export type GraphNodeType = 'transaction' | 'program' | 'map' | 'copybook' | 'file' | 'job'
export type MigrationState = 'verified' | 'generated' | 'inProgress' | 'pending'

export interface GraphNode {
  id: string
  type: GraphNodeType
  domain: 'Accounts' | 'Cards' | 'Authorizations'
  state: MigrationState
  loc?: number
  rules: string[]
  target?: string
  source?: string
  // Business-language summary written by the legacy analyst agent from a source excerpt and the node's connections.
  description?: string
}

export const graphNodes: GraphNode[] = [
  {
    id: 'CAUP',
    type: 'transaction',
    domain: 'Accounts',
    state: 'inProgress',
    rules: [],
    source: 'CSD: transaction CAUP',
    description:
      'Online transaction that opens the update-account screen. It starts program COACTUPC with an empty COMMAREA and returns to the menu on F3.',
  },
  { id: 'CCUP', type: 'transaction', domain: 'Cards', state: 'pending', rules: [] },
  { id: 'CAUT', type: 'transaction', domain: 'Authorizations', state: 'generated', rules: [] },
  {
    id: 'COACTUPC',
    type: 'program',
    domain: 'Accounts',
    state: 'inProgress',
    loc: 4210,
    rules: ['RULE-005', 'RULE-006'],
    target: 'account-service',
    source: 'COACTUPC.cbl lines 1-4210',
    description:
      'Handles the update-account screen in pseudo-conversational mode: sends map COACTUP, receives the edited fields, validates names (RULE-006) and status changes (RULE-005), and rewrites ACCTDAT. On a validation error it re-sends the map with the message in line 24; on success it commits with SYNCPOINT. Called from COAUTHPC to hold authorized amounts.',
  },
  {
    id: 'COCRDUPC',
    type: 'program',
    domain: 'Cards',
    state: 'pending',
    loc: 1830,
    rules: ['RULE-003'],
    target: 'card-service',
  },
  {
    id: 'COAUTHPC',
    type: 'program',
    domain: 'Authorizations',
    state: 'generated',
    loc: 2690,
    rules: ['RULE-001'],
    target: 'authorization-service',
    source: 'COAUTHPC.cbl lines 1-2690',
    description:
      'Authorizes a card purchase: reads the card in CARDDAT and rejects expired cards (RULE-003), reads the account balance and limit from ACCTDAT through copybook CVACT01Y, and declines with code 51 when balance + amount exceeds the limit (RULE-001). On approval it links to COACTUPC to hold the amount.',
  },
  {
    id: 'CBACT04C',
    type: 'program',
    domain: 'Accounts',
    state: 'verified',
    loc: 980,
    rules: ['RULE-002'],
    target: 'interest-batch',
    source: 'CBACT04C.cbl lines 1-980',
    description:
      'Nightly batch that reads every account, computes daily interest as balance × rate ÷ 360 rounded half-up to two decimals (RULE-002) and rewrites the balance. Runs from job INTCALC.',
  },
  { id: 'COACTUP', type: 'map', domain: 'Accounts', state: 'inProgress', rules: [], target: 'UpdateAccountPage' },
  { id: 'COCRDUP', type: 'map', domain: 'Cards', state: 'pending', rules: [], target: 'CardDetailPage' },
  { id: 'CVACT01Y', type: 'copybook', domain: 'Accounts', state: 'verified', rules: [], target: 'Account (entity)' },
  { id: 'CVCRD01Y', type: 'copybook', domain: 'Cards', state: 'pending', rules: [], target: 'Card (entity)' },
  {
    id: 'ACCTDAT',
    type: 'file',
    domain: 'Accounts',
    state: 'verified',
    rules: [],
    target: 'table account',
    source: 'VSAM KSDS ACCTDAT (layout CVACT01Y)',
    description:
      'Account master file keyed by account number. Written by COACTUPC, CBACT04C and read by COAUTHPC, CBSTM03A and COUTIL01. Target: table account in PostgreSQL (ADR-003).',
  },
  { id: 'CARDDAT', type: 'file', domain: 'Cards', state: 'pending', rules: [], target: 'table card' },
  {
    id: 'INTCALC',
    type: 'job',
    domain: 'Accounts',
    state: 'verified',
    rules: ['RULE-002'],
    target: 'Step Functions: interest-accrual',
  },
  {
    id: 'STMTJOB',
    type: 'job',
    domain: 'Accounts',
    state: 'pending',
    rules: ['RULE-004'],
    target: 'Step Functions: monthly-statement',
  },
  {
    id: 'CBSTM03A',
    type: 'program',
    domain: 'Accounts',
    state: 'pending',
    loc: 1460,
    rules: ['RULE-004'],
    target: 'billing-service',
    source: 'CBSTM03A.cbl lines 1-1460',
    description:
      'Monthly statement program: reads each account and its payments, charges a 25.00 late fee when the minimum payment was not received by the due date (RULE-004) and writes the statement record to STMTFILE. It does not check the account status (see question Q-003).',
  },
  { id: 'STMTFILE', type: 'file', domain: 'Accounts', state: 'pending', rules: [], target: 'table statement' },
  // Orphans and isolated nodes: candidates for dead code (nobody calls them) or unused data.
  {
    id: 'COUTIL01',
    type: 'program',
    domain: 'Accounts',
    state: 'pending',
    loc: 620,
    rules: [],
    target: undefined,
    source: 'COUTIL01.cbl lines 1-620',
    description:
      'Utility that dumps accounts to the spool. No transaction, job or program calls it: likely dead code kept from an old reconciliation process.',
  },
  {
    id: 'CVOLD01Y',
    type: 'copybook',
    domain: 'Cards',
    state: 'pending',
    rules: [],
    target: undefined,
    source: 'CVOLD01Y.cpy lines 1-48',
    description: 'Old card record layout. No program copies it; CVCRD01Y replaced it.',
  },
  {
    id: 'TMPWORK',
    type: 'file',
    domain: 'Authorizations',
    state: 'pending',
    rules: [],
    target: undefined,
    source: 'VSAM ESDS TMPWORK',
    description: 'Temporary work file defined in the CSD but never opened by any program in the inventory.',
  },
]

export const graphEdges: { from: string; to: string; kind: string }[] = [
  { from: 'CAUP', to: 'COACTUPC', kind: 'STARTS' },
  { from: 'CCUP', to: 'COCRDUPC', kind: 'STARTS' },
  { from: 'CAUT', to: 'COAUTHPC', kind: 'STARTS' },
  { from: 'COACTUPC', to: 'COACTUP', kind: 'USES_MAP' },
  { from: 'COACTUPC', to: 'CVACT01Y', kind: 'COPIES' },
  { from: 'COCRDUPC', to: 'COCRDUP', kind: 'USES_MAP' },
  { from: 'COCRDUPC', to: 'CVCRD01Y', kind: 'COPIES' },
  { from: 'COACTUPC', to: 'ACCTDAT', kind: 'WRITES' },
  { from: 'COCRDUPC', to: 'CARDDAT', kind: 'WRITES' },
  { from: 'COAUTHPC', to: 'ACCTDAT', kind: 'READS' },
  { from: 'COAUTHPC', to: 'CARDDAT', kind: 'READS' },
  { from: 'COAUTHPC', to: 'CVACT01Y', kind: 'COPIES' },
  { from: 'INTCALC', to: 'CBACT04C', kind: 'RUNS' },
  { from: 'CBACT04C', to: 'ACCTDAT', kind: 'WRITES' },
  { from: 'CBACT04C', to: 'CVACT01Y', kind: 'COPIES' },
  { from: 'COAUTHPC', to: 'COACTUPC', kind: 'CALLS' },
  { from: 'STMTJOB', to: 'CBSTM03A', kind: 'RUNS' },
  { from: 'CBSTM03A', to: 'ACCTDAT', kind: 'READS' },
  { from: 'CBSTM03A', to: 'STMTFILE', kind: 'WRITES' },
  { from: 'CBSTM03A', to: 'CVACT01Y', kind: 'COPIES' },
  { from: 'COUTIL01', to: 'ACCTDAT', kind: 'READS' },
]

// Edge kinds grouped for the relation filters.
export const edgeGroup: Record<string, 'calls' | 'reads' | 'writes' | 'includes'> = {
  STARTS: 'calls',
  RUNS: 'calls',
  CALLS: 'calls',
  READS: 'reads',
  WRITES: 'writes',
  COPIES: 'includes',
  USES_MAP: 'includes',
}

export interface BusinessFlow {
  id: string
  name: string
  persona: string
  summary: string
  rules: string[]
  steps: { title: string; nodes: string[]; rule?: string }[]
}

// Business flows reconstructed from the graph and the extracted rules (walkthrough in the Inventory tab).
export const businessFlows: BusinessFlow[] = [
  {
    id: 'BF-01',
    name: 'Authorize a card purchase',
    persona: 'Cardholder paying at a merchant',
    summary:
      'The authorization transaction validates the card, checks the balance against the credit limit and answers approve (00) or decline (51).',
    rules: ['RULE-003', 'RULE-001'],
    steps: [
      { title: 'Receive the authorization request', nodes: ['CAUT', 'COAUTHPC'] },
      { title: 'Validate the card and its expiry', nodes: ['COAUTHPC', 'CARDDAT'], rule: 'RULE-003' },
      { title: 'Read the account balance and limit', nodes: ['COAUTHPC', 'CVACT01Y', 'ACCTDAT'] },
      { title: 'Apply the credit limit check', nodes: ['COAUTHPC'], rule: 'RULE-001' },
      { title: 'Update the account (hold the amount)', nodes: ['COAUTHPC', 'COACTUPC', 'ACCTDAT'] },
    ],
  },
  {
    id: 'BF-02',
    name: 'Update customer and account data',
    persona: 'Branch officer at the account screen',
    summary:
      'The officer edits names, limits and status on the COACTUP screen; the program validates and saves the account.',
    rules: ['RULE-006', 'RULE-005'],
    steps: [
      { title: 'Open the update account screen', nodes: ['CAUP', 'COACTUPC', 'COACTUP'] },
      { title: 'Validate mandatory names', nodes: ['COACTUPC', 'COACTUP'], rule: 'RULE-006' },
      { title: 'Apply the status transition', nodes: ['COACTUPC', 'CVACT01Y'], rule: 'RULE-005' },
      { title: 'Save the account', nodes: ['COACTUPC', 'ACCTDAT'] },
    ],
  },
  {
    id: 'BF-03',
    name: 'Nightly interest accrual',
    persona: 'Operations (batch schedule)',
    summary: 'Every night the batch job computes daily interest on each account and posts it.',
    rules: ['RULE-002'],
    steps: [
      { title: 'Start the nightly job', nodes: ['INTCALC', 'CBACT04C'] },
      { title: 'Read every account', nodes: ['CBACT04C', 'CVACT01Y', 'ACCTDAT'] },
      { title: 'Compute and round daily interest', nodes: ['CBACT04C'], rule: 'RULE-002' },
      { title: 'Post the interest', nodes: ['CBACT04C', 'ACCTDAT'] },
    ],
  },
  {
    id: 'BF-04',
    name: 'Monthly statement and late fee',
    persona: 'Customer receiving the statement',
    summary:
      'The statement job reads accounts, charges the late fee when the minimum payment was missed and writes the statement.',
    rules: ['RULE-004'],
    steps: [
      { title: 'Start the statement job', nodes: ['STMTJOB', 'CBSTM03A'] },
      { title: 'Read the account and its payments', nodes: ['CBSTM03A', 'CVACT01Y', 'ACCTDAT'] },
      { title: 'Charge the late fee if the minimum was missed', nodes: ['CBSTM03A'], rule: 'RULE-004' },
      { title: 'Write the statement', nodes: ['CBSTM03A', 'STMTFILE'] },
    ],
  },
]

// ---- Source ↔ target comparison (Traceability tab) ----

export interface CompareItem {
  ruleId: string
  program: string
  legacyRef: string
  legacy: string[]
  legacyHighlight: number[]
  targetRef: string
  target: string[]
  targetHighlight: number[]
  outputs: { caseId: string; input: string; legacy: string; next: string; same: boolean }[]
}

export const compareItems: CompareItem[] = [
  {
    ruleId: 'RULE-001',
    program: 'COAUTHPC',
    legacyRef: 'COAUTHPC.cbl:412-422',
    legacy: [
      '       2100-CHECK-LIMIT.',
      '           COMPUTE WS-NEW-BAL =',
      '               ACCT-CURR-BAL + WS-TRAN-AMT',
      '           IF WS-NEW-BAL > ACCT-CREDIT-LIMIT',
      "               MOVE '51' TO WS-RESP-CODE",
      '               SET TRAN-DECLINED TO TRUE',
      '               GO TO 2100-EXIT',
      '           END-IF.',
      "           MOVE '00' TO WS-RESP-CODE.",
    ],
    legacyHighlight: [1, 2, 3, 4],
    targetRef: 'CreditLimitPolicy.java:9-15',
    target: [
      'public Decision evaluate(Money balance,',
      '    Money limit, Money purchase) {',
      '  if (balance.plus(purchase).isGreaterThan(limit)) {',
      '    return Decision.decline(ReasonCode.OVER_LIMIT); // 51',
      '  }',
      '  return Decision.approve(); // 00',
      '}',
    ],
    targetHighlight: [2, 3],
    outputs: [
      {
        caseId: 'C01',
        input: 'balance 4,900.00 · limit 5,000.00 · purchase 150.00',
        legacy: 'RESP=51 DECLINED',
        next: 'RESP=51 DECLINED',
        same: true,
      },
      {
        caseId: 'C02',
        input: 'balance 4,900.00 · limit 5,000.00 · purchase 100.00',
        legacy: 'RESP=00 APPROVED',
        next: 'RESP=00 APPROVED',
        same: true,
      },
      {
        caseId: 'F07',
        input: 'balance 0.00 · limit 0.00 · purchase 0.01',
        legacy: 'RESP=51 DECLINED',
        next: 'RESP=51 DECLINED',
        same: true,
      },
    ],
  },
  {
    ruleId: 'RULE-002',
    program: 'CBACT04C',
    legacyRef: 'CBACT04C.cbl:233-241',
    legacy: [
      '       1300-COMPUTE-INTEREST.',
      '           COMPUTE WS-DAILY-INT ROUNDED =',
      '               ACCT-CURR-BAL * DIS-INT-RATE / 36000',
      '           ADD WS-DAILY-INT TO WS-TOTAL-INT.',
    ],
    legacyHighlight: [1, 2],
    targetRef: 'InterestCalculator.java:18-22',
    target: [
      'Money dailyInterest(Money balance, Rate annual) {',
      '  return balance.multiply(annual.asDecimal())',
      '      .divide(DAYS_IN_YEAR, 2, RoundingMode.HALF_UP); // Q-002',
      '}',
    ],
    targetHighlight: [1, 2],
    outputs: [
      { caseId: 'C14', input: 'balance 12,345.67 · rate 18.50%', legacy: 'INT=6.34', next: 'INT=6.34', same: true },
      { caseId: 'C15', input: 'balance 1,000.05 · rate 12.00%', legacy: 'INT=0.33', next: 'INT=0.33', same: true },
      { caseId: 'F03', input: 'balance 2,500.25 · rate 7.30%', legacy: 'INT=0.51', next: 'INT=0.50', same: false },
    ],
  },
  {
    ruleId: 'RULE-005',
    program: 'COACTUPC',
    legacyRef: 'COACTUPC.cbl:640-652',
    legacy: [
      '       3200-CHANGE-STATUS.',
      '           EVALUATE TRUE ALSO WS-NEW-STATUS',
      "             WHEN ACCT-ACTIVE ALSO 'S'",
      "               MOVE 'S' TO ACCT-ACTIVE-STATUS",
      "             WHEN ACCT-SUSPENDED ALSO 'A'",
      "               MOVE 'Y' TO ACCT-ACTIVE-STATUS",
      '             WHEN OTHER',
      "               MOVE 'INVALID STATUS CHANGE' TO WS-MESSAGE",
      '           END-EVALUATE.',
    ],
    legacyHighlight: [2, 3, 4, 5, 6, 7],
    targetRef: 'Account.java:10-18',
    target: [
      'public void suspend() {',
      '  if (status != AccountStatus.ACTIVE) throw new DomainException("ACCOUNT_NOT_ACTIVE");',
      '  status = AccountStatus.SUSPENDED;',
      '}',
      'public void reactivate() {',
      '  if (status != AccountStatus.SUSPENDED) throw new DomainException("ACCOUNT_NOT_SUSPENDED");',
      '  status = AccountStatus.ACTIVE;',
      '}',
    ],
    targetHighlight: [1, 2, 5, 6],
    outputs: [
      {
        caseId: 'C22',
        input: 'suspended account · reactivate',
        legacy: 'STATUS=Y',
        next: 'STATUS=ACTIVE (mapped Y)',
        same: true,
      },
    ],
  },
]

// ---- Work items synced with Jira / Azure DevOps (Backlog tab) ----

export type WorkItemType = 'feature' | 'story' | 'task' | 'bug'
export type WorkItemStatus = 'todo' | 'inProgress' | 'inReview' | 'done' | 'failed'

export interface WorkItem {
  key: string
  type: WorkItemType
  title: string
  parent?: string
  status: WorkItemStatus
  createdBy: string
  assignee: string
  rules: string[]
  synced: boolean
  updated: string
}

export const workItems: WorkItem[] = [
  {
    key: 'CARDS-101',
    type: 'feature',
    title: 'Authorizations service (CICS CAUT → REST)',
    status: 'inProgress',
    createdBy: 'Solution architect',
    assignee: 'María Torres',
    rules: ['RULE-001', 'RULE-003'],
    synced: true,
    updated: '2026-09-28T09:20:00Z',
  },
  {
    key: 'CARDS-102',
    type: 'story',
    parent: 'CARDS-101',
    title: 'As a cardholder, my purchase is declined when it exceeds my credit limit',
    status: 'done',
    createdBy: 'Functional analyst',
    assignee: 'Backend developer',
    rules: ['RULE-001'],
    synced: true,
    updated: '2026-09-28T09:05:00Z',
  },
  {
    key: 'CARDS-103',
    type: 'task',
    parent: 'CARDS-102',
    title: 'Implement CreditLimitPolicy in the domain layer',
    status: 'done',
    createdBy: 'Backend developer',
    assignee: 'Backend developer',
    rules: ['RULE-001'],
    synced: true,
    updated: '2026-09-28T08:40:00Z',
  },
  {
    key: 'CARDS-104',
    type: 'task',
    parent: 'CARDS-102',
    title: 'Characterization tests for RULE-001 (golden master C01, C02)',
    status: 'done',
    createdBy: 'Test engineer',
    assignee: 'Test engineer',
    rules: ['RULE-001'],
    synced: true,
    updated: '2026-09-28T08:55:00Z',
  },
  {
    key: 'CARDS-105',
    type: 'story',
    parent: 'CARDS-101',
    title: 'As a cardholder, an expired card cannot be used',
    status: 'inProgress',
    createdBy: 'Functional analyst',
    assignee: 'Backend developer',
    rules: ['RULE-003'],
    synced: true,
    updated: '2026-09-28T09:25:00Z',
  },
  {
    key: 'CARDS-106',
    type: 'task',
    parent: 'CARDS-105',
    title: 'Validate card expiry (waiting for Q-001)',
    status: 'todo',
    createdBy: 'Backend developer',
    assignee: 'Backend developer',
    rules: ['RULE-003'],
    synced: true,
    updated: '2026-09-28T09:25:00Z',
  },
  {
    key: 'CARDS-107',
    type: 'bug',
    parent: 'CARDS-102',
    title: 'Purchase exactly at the limit is declined (expected approve)',
    status: 'inReview',
    createdBy: 'Test engineer',
    assignee: 'Backend developer',
    rules: ['RULE-001'],
    synced: true,
    updated: '2026-09-28T09:31:00Z',
  },
  {
    key: 'CARDS-110',
    type: 'feature',
    title: 'Interest accrual batch (CBACT04C → Spring Batch)',
    status: 'inProgress',
    createdBy: 'Solution architect',
    assignee: 'Luis Andrade',
    rules: ['RULE-002'],
    synced: true,
    updated: '2026-09-28T09:10:00Z',
  },
  {
    key: 'CARDS-111',
    type: 'story',
    parent: 'CARDS-110',
    title: 'As operations, daily interest is posted every night',
    status: 'inProgress',
    createdBy: 'Functional analyst',
    assignee: 'Backend developer',
    rules: ['RULE-002'],
    synced: true,
    updated: '2026-09-28T09:12:00Z',
  },
  {
    key: 'CARDS-112',
    type: 'bug',
    parent: 'CARDS-111',
    title: 'Fresh input F03: interest 0.50 vs legacy 0.51 (rounding)',
    status: 'failed',
    createdBy: 'Equivalence validator',
    assignee: 'Backend developer',
    rules: ['RULE-002'],
    synced: false,
    updated: '2026-09-28T09:36:00Z',
  },
]

// Timeline of the automated bug loop for CARDS-107 (tester → bug → developer → re-test → close).
export const bugLoop = [
  {
    time: '09:28:10',
    agent: 'Test engineer',
    step: 'detected',
    detail: 'CreditLimitPolicyTest.rule001_approvesPurchaseAtLimit failed: expected APPROVED, got DECLINED.',
  },
  {
    time: '09:28:12',
    agent: 'Test engineer',
    step: 'bugCreated',
    detail: 'Bug CARDS-107 created in Jira with the failing test, the rule and the golden master case.',
  },
  {
    time: '09:28:15',
    agent: 'Supervisor',
    step: 'developerTriggered',
    detail: 'Automation rule "Fix bugs automatically" started the Backend developer (iteration 1 of 3).',
  },
  {
    time: '09:30:40',
    agent: 'Backend developer',
    step: 'fixProposed',
    detail: 'Changed isGreaterThan to strictly greater, matching COBOL ">" (COAUTHPC.cbl:415). Commit a91c2e4.',
  },
  {
    time: '09:31:05',
    agent: 'Test engineer',
    step: 'retested',
    detail: '412 tests from clean: all passed. Golden master C01, C02, F07: same.',
  },
  {
    time: '09:31:06',
    agent: 'Supervisor',
    step: 'waitingReview',
    detail: 'Moved to In review. Closes automatically when the code reviewer approves (policy: balanced).',
  },
]

// ---- Live agent activity (floating activity panel) ----

export type ActivityStatus = 'running' | 'succeeded' | 'failed' | 'waiting'

export interface ActivityEvent {
  id: string
  startedAt: string
  endedAt?: string
  agent: string
  projectId: string
  message: string
  status: ActivityStatus
  costUsd: number
  tokens: number
  error?: { code: string; message: string; detail: string }
}

export const activitySeed: ActivityEvent[] = [
  {
    id: 'ev-1',
    startedAt: '2026-09-28T09:20:02Z',
    endedAt: '2026-09-28T09:27:40Z',
    agent: 'Business rules extractor',
    projectId: 'p1',
    message: 'Extracted 23 rules from shard AUTH',
    status: 'succeeded',
    costUsd: 5.16,
    tokens: 1_240_000,
  },
  {
    id: 'ev-2',
    startedAt: '2026-09-28T09:28:10Z',
    endedAt: '2026-09-28T09:28:12Z',
    agent: 'Test engineer',
    projectId: 'p1',
    message: 'Test failed → bug CARDS-107 created in Jira',
    status: 'succeeded',
    costUsd: 0.04,
    tokens: 9_000,
  },
  {
    id: 'ev-3',
    startedAt: '2026-09-28T09:32:00Z',
    endedAt: '2026-09-28T09:33:10Z',
    agent: 'Equivalence validator',
    projectId: 'p2',
    message: 'Fresh input F03 differs from legacy',
    status: 'failed',
    costUsd: 0.31,
    tokens: 41_000,
    error: {
      code: 'EQUIVALENCE_DIFF',
      message: 'Output differs at line 1, byte 4',
      detail: 'legacy INT=0.51, new INT=0.50 (mask: none, tolerance: none)',
    },
  },
]

// User stories derived from the specification (spec 7.2, 7.7). In flow 1 they are built from the rules,
// screens and contracts extracted from the legacy; in flow 2 from documents, Figma and Jira. People can edit,
// create, split, merge and discard them before gate C1; after C1 every change is a scope change.
export type StoryStatus = 'draft' | 'inReview' | 'approved' | 'question' | 'discarded' | 'merged'
export type StoryOrigin = 'extracted' | 'document' | 'jira' | 'user'
export type DependencyKind = 'hard' | 'soft'

export interface StoryDependency {
  story: string
  kind: DependencyKind
  reason: string
}

export interface UserStory {
  id: string
  feature: string
  title: string
  asA: string
  iWant: string
  soThat: string
  criteria: string[]
  rules: string[]
  screens: string[]
  contracts: string[]
  nodes: string[]
  origin: StoryOrigin
  source: string
  status: StoryStatus
  priority: 'P0' | 'P1' | 'P2'
  points: number
  dependsOn: StoryDependency[]
  version: number
  discardReason?: string
  outOfScope?: boolean
  mergedInto?: string
}

export const storyFeatures = [
  { id: 'FEAT-DATA', name: 'Data foundation' },
  { id: 'FEAT-ACC', name: 'Account maintenance' },
  { id: 'FEAT-AUTH', name: 'Card authorizations' },
  { id: 'FEAT-CARD', name: 'Card management' },
  { id: 'FEAT-BILL', name: 'Interest and billing' },
]

export const userStories: UserStory[] = [
  {
    id: 'US-001',
    feature: 'FEAT-DATA',
    title: 'Account master data in PostgreSQL',
    asA: 'platform operator',
    iWant: 'the account master file migrated to the account table with the same keys and values',
    soThat: 'every new service reads the same accounts the legacy reads',
    criteria: [
      'Scenario: Every account is migrated\n  Given the ACCTDAT extract of 2026-09-18\n  When the migration job runs\n  Then the account table has the same number of rows and the same checksum per column',
    ],
    rules: [],
    screens: [],
    contracts: [],
    nodes: ['ACCTDAT', 'CVACT01Y'],
    origin: 'extracted',
    source: 'ACCTDAT (VSAM KSDS), copybook CVACT01Y',
    status: 'approved',
    priority: 'P0',
    points: 5,
    dependsOn: [],
    version: 2,
  },
  {
    id: 'US-002',
    feature: 'FEAT-DATA',
    title: 'Card master data in PostgreSQL',
    asA: 'platform operator',
    iWant: 'the card file migrated to the card table linked to its account',
    soThat: 'card services can validate cards without calling the mainframe',
    criteria: [
      'Scenario: Cards keep their account\n  Given a card 4000 0000 0000 0002 of account 00000000011\n  When the migration job runs\n  Then the card row references account 00000000011',
    ],
    rules: [],
    screens: [],
    contracts: [],
    nodes: ['CARDDAT', 'CVCRD01Y'],
    origin: 'extracted',
    source: 'CARDDAT (VSAM KSDS), copybook CVCRD01Y',
    status: 'inReview',
    priority: 'P0',
    points: 3,
    dependsOn: [{ story: 'US-001', kind: 'hard', reason: 'The card table has a foreign key to account.' }],
    version: 1,
  },
  {
    id: 'US-003',
    feature: 'FEAT-ACC',
    title: 'View and update an account',
    asA: 'back-office agent',
    iWant: 'to open an account, edit its limit, status and holder names and save them',
    soThat: 'I can serve customers without the 3270 screen',
    criteria: [
      'Scenario: Save a valid change\n  Given account 00000000011 is active\n  When I change the credit limit to 6,000.00 and save\n  Then the account shows a credit limit of 6,000.00',
      'Scenario: Reject a non-alphabetic last name\n  Given the update-account screen\n  When I enter last name "O2" and save\n  Then I see "Last name must be alphabetic"',
    ],
    rules: ['RULE-006'],
    screens: ['SCR-001'],
    contracts: ['API-001', 'API-002'],
    nodes: ['CAUP', 'COACTUPC', 'COACTUP'],
    origin: 'extracted',
    source: 'Transaction CAUP → COACTUPC → map COACTUP',
    status: 'approved',
    priority: 'P0',
    points: 8,
    dependsOn: [{ story: 'US-001', kind: 'hard', reason: 'Reads and rewrites the account table.' }],
    version: 3,
  },
  {
    id: 'US-004',
    feature: 'FEAT-ACC',
    title: 'Suspend, reactivate or close an account',
    asA: 'back-office agent',
    iWant: 'to change the status of an account following the allowed transitions',
    soThat: 'accounts never reach an invalid state',
    criteria: [
      'Scenario: Reactivate a suspended account\n  Given a suspended account\n  When a reactivation is requested\n  Then the account becomes active',
    ],
    rules: ['RULE-005'],
    screens: ['SCR-001'],
    contracts: ['API-002'],
    nodes: ['COACTUPC'],
    origin: 'extracted',
    source: 'COACTUPC.cbl:640-702',
    status: 'inReview',
    priority: 'P1',
    points: 3,
    dependsOn: [
      {
        story: 'US-003',
        kind: 'soft',
        reason: 'Uses the update-account screen; a status-only endpoint works without it.',
      },
    ],
    version: 1,
  },
  {
    id: 'US-005',
    feature: 'FEAT-AUTH',
    title: 'Authorize a card purchase',
    asA: 'card holder',
    iWant: 'my purchase approved or declined in real time against my credit limit',
    soThat: 'I can pay without exceeding my limit',
    criteria: [
      'Scenario: Decline over the limit\n  Given an account with limit 5,000.00 and balance 4,900.00\n  When a purchase of 150.00 is authorized\n  Then the purchase is declined with reason code 51',
    ],
    rules: ['RULE-001'],
    screens: [],
    contracts: ['API-003'],
    nodes: ['CAUT', 'COAUTHPC'],
    origin: 'extracted',
    source: 'Transaction CAUT → COAUTHPC',
    status: 'approved',
    priority: 'P0',
    points: 8,
    dependsOn: [
      { story: 'US-001', kind: 'hard', reason: 'Reads balance and limit from the account table.' },
      { story: 'US-002', kind: 'hard', reason: 'Reads the card to reject expired cards.' },
      {
        story: 'US-003',
        kind: 'soft',
        reason: 'Holds the authorized amount through COACTUPC; an ACL can call the legacy meanwhile.',
      },
    ],
    version: 2,
  },
  {
    id: 'US-006',
    feature: 'FEAT-CARD',
    title: 'Card detail and activation',
    asA: 'back-office agent',
    iWant: 'to see a card, change the name on it and activate it before it expires',
    soThat: 'customers can use their new cards',
    criteria: [
      'Scenario: Reject activation after expiry\n  Given a card expiring 2026-08\n  When activation is requested on 2026-09-02\n  Then activation is rejected',
    ],
    rules: ['RULE-003'],
    screens: ['SCR-002'],
    contracts: ['API-004'],
    nodes: ['CCUP', 'COCRDUPC', 'COCRDUP'],
    origin: 'extracted',
    source: 'Transaction CCUP → COCRDUPC → map COCRDUP',
    status: 'question',
    priority: 'P1',
    points: 5,
    dependsOn: [{ story: 'US-002', kind: 'hard', reason: 'Reads and rewrites the card table.' }],
    version: 1,
  },
  {
    id: 'US-007',
    feature: 'FEAT-BILL',
    title: 'Nightly interest accrual',
    asA: 'finance operator',
    iWant: 'daily interest posted on every account each night',
    soThat: 'balances match the legacy to the cent',
    criteria: [
      'Scenario: Accrue daily interest\n  Given a balance of 12,345.67 and an annual rate of 18.5%\n  When the nightly accrual runs\n  Then interest of 6.34 is posted',
    ],
    rules: ['RULE-002'],
    screens: [],
    contracts: [],
    nodes: ['INTCALC', 'CBACT04C'],
    origin: 'extracted',
    source: 'Job INTCALC → CBACT04C',
    status: 'approved',
    priority: 'P0',
    points: 5,
    dependsOn: [{ story: 'US-001', kind: 'hard', reason: 'Reads and rewrites every account balance.' }],
    version: 1,
  },
  {
    id: 'US-008',
    feature: 'FEAT-BILL',
    title: 'Late fee on missed minimum payment',
    asA: 'finance operator',
    iWant: 'a late fee charged when the minimum payment is not received by the due date',
    soThat: 'the billing policy is applied the same way as today',
    criteria: [
      'Scenario: Charge the late fee\n  Given a statement with minimum payment 80.00 due 2026-09-10\n  When no payment is received by 2026-09-10\n  Then a late fee of 25.00 is posted on 2026-09-11',
      // Imported from a workshop note; it has no When step, so the Gherkin check flags it (spec 7.7).
      'Scenario: No fee when the minimum is paid\n  Given a statement with minimum payment 80.00 paid on 2026-09-09\n  Then no late fee is posted',
    ],
    rules: ['RULE-004'],
    screens: [],
    contracts: ['API-005'],
    nodes: ['STMTJOB', 'CBSTM03A', 'STMTFILE'],
    origin: 'extracted',
    source: 'Job STMTJOB → CBSTM03A',
    status: 'inReview',
    priority: 'P0',
    points: 5,
    dependsOn: [
      { story: 'US-001', kind: 'hard', reason: 'Reads accounts and payments.' },
      { story: 'US-007', kind: 'soft', reason: 'The statement uses the balance after the nightly interest.' },
    ],
    version: 1,
  },
  {
    id: 'US-009',
    feature: 'FEAT-ACC',
    title: 'Export accounts for reconciliation',
    asA: 'auditor',
    iWant: 'a CSV export of accounts with balance and status',
    soThat: 'I can reconcile balances with the general ledger',
    criteria: [],
    rules: [],
    screens: [],
    contracts: [],
    nodes: [],
    origin: 'user',
    source: 'Created by María Torres (PO) on 2026-09-27',
    status: 'draft',
    priority: 'P2',
    points: 2,
    dependsOn: [{ story: 'US-001', kind: 'hard', reason: 'Reads the account table.' }],
    version: 1,
  },
]

// Suggestions from the functional analyst agent. They are never applied without a person accepting them.
export const storySuggestions = [
  {
    id: 'SG-1',
    story: 'US-009',
    kind: 'missingCriterion',
    text: 'Scenario: Export only active accounts\n  Given 3 active and 1 closed account\n  When I export accounts\n  Then the file has 3 rows',
  },
  {
    id: 'SG-2',
    story: 'US-003',
    kind: 'tooBig',
    text: 'Split "View and update an account" into "View an account" and "Update an account": 8 points and two screens actions.',
  },
  {
    id: 'SG-3',
    story: 'US-006',
    kind: 'missingCriterion',
    text: 'Scenario: Card detail masks the number\n  Given card 4000 0000 0000 0002\n  When I open the card detail\n  Then I see **** **** **** 0002',
  },
]

export const storyHistorySeed = [
  {
    story: 'US-003',
    version: 3,
    by: 'María Torres',
    at: '2026-09-27T16:20:00Z',
    change: 'Added the scenario for non-alphabetic last names.',
  },
  {
    story: 'US-003',
    version: 2,
    by: 'Functional analyst (agent)',
    at: '2026-09-26T10:05:00Z',
    change: 'Linked contract API-001.',
  },
  {
    story: 'US-001',
    version: 2,
    by: 'Carlos Rivas',
    at: '2026-09-26T09:12:00Z',
    change: 'Checksum per column instead of per row.',
  },
  { story: 'US-005', version: 2, by: 'María Torres', at: '2026-09-25T18:40:00Z', change: 'Priority P1 → P0.' },
]
