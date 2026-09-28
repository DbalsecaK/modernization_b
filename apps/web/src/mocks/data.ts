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
  { id: 't1', name: 'Andes Bank', deployment: 'customerCloud', projects: 3, users: 24, monthCostUsd: 4210, defaultLanguage: 'es' },
  { id: 't2', name: 'Pacific Credit Union', deployment: 'sharedSaas', projects: 1, users: 9, monthCostUsd: 960, defaultLanguage: 'es' },
  { id: 't3', name: 'NexTI Internal', deployment: 'sharedSaas', projects: 1, users: 14, monthCostUsd: 530, defaultLanguage: 'en' },
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
    target: { architecture: 'Microservices (hexagonal)', backend: 'Java Spring Boot', frontend: 'Angular', database: 'PostgreSQL', cloud: 'AWS' },
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
    target: { architecture: 'Modular monolith (hexagonal)', backend: '.NET 10', frontend: '—', database: 'PostgreSQL', cloud: 'Azure' },
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
    target: { architecture: 'BFF + microservices', backend: '.NET 10', frontend: 'React', database: 'SQL Server', cloud: 'Azure' },
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
    target: { architecture: 'Microservices (hexagonal)', backend: 'Java Quarkus', frontend: 'React', database: 'PostgreSQL', cloud: 'AWS' },
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
  { id: 'legacy-analyst', name: 'Legacy analyst', nameEs: 'Analista legacy', group: 'analysis', description: 'Builds the inventory and dependency map of the legacy system and flags risky areas.', descriptionEs: 'Construye el inventario y el mapa de dependencias del legacy y señala las zonas de riesgo.', phases: ['inventory', 'domains', 'classification'], capabilities: ['longContext', 'structuredOutput'], tools: ['readGraph', 'readCode'], mandatory: false, level: 'certified', version: '1.4.0', defaultProfile: 'fast-analysis', relativeCost: 1 },
  { id: 'rules-extractor', name: 'Business rules extractor', nameEs: 'Extractor de reglas de negocio', group: 'analysis', description: 'Turns program slices into business rules with concrete Given/When/Then and exact source citations.', descriptionEs: 'Convierte slices de programa en reglas de negocio con Given/When/Then concretos y citas exactas al fuente.', phases: ['ruleExtraction'], capabilities: ['longContext', 'structuredOutput'], tools: ['readGraph', 'readCode'], mandatory: false, level: 'certified', version: '2.1.0', defaultProfile: 'deep-analysis', relativeCost: 3 },
  { id: 'data-analyst', name: 'Data analyst', nameEs: 'Analista de datos', group: 'analysis', description: 'Maps copybooks, tables and files to neutral types, including COMP-3, zoned and EBCDIC semantics.', descriptionEs: 'Mapea copybooks, tablas y archivos a tipos neutrales, incluida la semántica COMP-3, zoned y EBCDIC.', phases: ['inventory', 'design'], capabilities: ['structuredOutput'], tools: ['readGraph', 'readCode'], mandatory: false, level: 'certified', version: '1.2.0', defaultProfile: 'fast-analysis', relativeCost: 1 },
  { id: 'ui-analyst', name: 'UI analyst', nameEs: 'Analista de UI', group: 'analysis', description: 'Reads BMS maps, ASPX pages, Figma files and screenshots into screen specifications.', descriptionEs: 'Lee mapas BMS, páginas ASPX, Figma y capturas y los convierte en especificaciones de pantalla.', phases: ['ui', 'normalization'], capabilities: ['vision', 'structuredOutput'], tools: ['readGraph', 'readInputs'], mandatory: false, level: 'certified', version: '1.1.0', defaultProfile: 'vision', relativeCost: 2 },
  { id: 'functional-analyst', name: 'Functional analyst', nameEs: 'Analista funcional', group: 'analysis', description: 'Normalizes user stories, manuals and documents, and detects gaps and contradictions.', descriptionEs: 'Normaliza historias de usuario, manuales y documentos, y detecta huecos y contradicciones.', phases: ['ingestion', 'normalization', 'consolidation'], capabilities: ['longContext', 'vision', 'structuredOutput'], tools: ['readInputs', 'readGraph'], mandatory: false, level: 'assisted', version: '0.9.0', defaultProfile: 'deep-analysis', relativeCost: 2 },
  { id: 'solution-architect', name: 'Solution architect', nameEs: 'Arquitecto de soluciones', group: 'design', description: 'Proposes bounded contexts, contracts and ADRs, and checks the compatibility matrix.', descriptionEs: 'Propone bounded contexts, contratos y ADR, y revisa la matriz de compatibilidad.', phases: ['domains', 'design'], capabilities: ['longContext', 'structuredOutput'], tools: ['readGraph'], mandatory: false, level: 'certified', version: '1.3.0', defaultProfile: 'deep-analysis', relativeCost: 2 },
  { id: 'data-architect', name: 'Data architect', nameEs: 'Arquitecto de datos', group: 'design', description: 'Designs the target data model, aggregates and the data migration plan.', descriptionEs: 'Diseña el modelo de datos destino, los agregados y el plan de migración de datos.', phases: ['design'], capabilities: ['structuredOutput'], tools: ['readGraph'], mandatory: false, level: 'certified', version: '1.0.0', defaultProfile: 'deep-analysis', relativeCost: 2 },
  { id: 'ux-designer', name: 'UX/UI designer', nameEs: 'Diseñador UX/UI', group: 'design', description: 'Proposes a design system and clickable prototypes when no Figma is provided.', descriptionEs: 'Propone un design system y prototipos navegables cuando no hay Figma.', phases: ['ui'], capabilities: ['vision', 'toolCalling'], tools: ['writeWorkspace', 'sandbox'], mandatory: false, level: 'assisted', version: '0.8.0', defaultProfile: 'codegen', relativeCost: 2 },
  { id: 'backend-dev', name: 'Backend developer', nameEs: 'Desarrollador backend', group: 'build', description: 'Generates domain, adapters and APIs from the approved specification, layer by layer.', descriptionEs: 'Genera dominio, adaptadores y APIs desde la especificación aprobada, capa por capa.', phases: ['generation'], capabilities: ['toolCalling', 'longContext'], tools: ['writeWorkspace', 'sandbox'], mandatory: false, level: 'certified', version: '1.5.0', defaultProfile: 'codegen', relativeCost: 3 },
  { id: 'frontend-dev', name: 'Frontend developer', nameEs: 'Desarrollador frontend', group: 'build', description: 'Builds screens with the approved design system and the typed API client.', descriptionEs: 'Construye las pantallas con el design system aprobado y el cliente tipado de la API.', phases: ['generation'], capabilities: ['toolCalling', 'vision'], tools: ['writeWorkspace', 'sandbox'], mandatory: false, level: 'certified', version: '1.2.0', defaultProfile: 'codegen', relativeCost: 2 },
  { id: 'fullstack-dev', name: 'Full stack developer', nameEs: 'Desarrollador full stack', group: 'build', description: 'Covers backend and frontend with one shared context. Less parallelism, fewer hand-offs.', descriptionEs: 'Cubre backend y frontend con un solo contexto. Menos paralelismo, menos traspasos.', phases: ['generation'], capabilities: ['toolCalling', 'longContext', 'vision'], tools: ['writeWorkspace', 'sandbox'], mandatory: false, level: 'assisted', version: '0.9.0', defaultProfile: 'codegen', relativeCost: 3 },
  { id: 'data-migration', name: 'Data migration engineer', nameEs: 'Ingeniero de migración de datos', group: 'build', description: 'Generates and tests the data conversion from VSAM or legacy tables to the target database.', descriptionEs: 'Genera y prueba la conversión de datos desde VSAM o tablas legacy hacia la base destino.', phases: ['generation'], capabilities: ['toolCalling'], tools: ['writeWorkspace', 'sandbox'], mandatory: false, level: 'assisted', version: '0.7.0', defaultProfile: 'codegen', relativeCost: 2 },
  { id: 'devops', name: 'DevOps / cloud engineer', nameEs: 'Ingeniero DevOps / cloud', group: 'build', description: 'Produces IaC, pipelines and the strangler-fig routing plan for the chosen cloud.', descriptionEs: 'Produce IaC, pipelines y el plan de enrutamiento strangler fig para la nube elegida.', phases: ['delivery'], capabilities: ['toolCalling'], tools: ['writeWorkspace', 'sandbox'], mandatory: false, level: 'assisted', version: '0.8.0', defaultProfile: 'codegen', relativeCost: 1 },
  { id: 'test-engineer', name: 'Test engineer', nameEs: 'Ingeniero de pruebas', group: 'quality', description: 'Writes characterization and acceptance tests that pin every rule id before code is generated.', descriptionEs: 'Escribe pruebas de caracterización y aceptación que fijan cada regla antes de generar código.', phases: ['characterization', 'validation'], capabilities: ['toolCalling'], tools: ['writeWorkspace', 'sandbox'], mandatory: false, level: 'certified', version: '1.6.0', defaultProfile: 'codegen', relativeCost: 2 },
  { id: 'code-reviewer', name: 'Code reviewer', nameEs: 'Revisor de código', group: 'quality', description: 'Reviews generated code against the target conventions and the customer constitution.', descriptionEs: 'Revisa el código generado contra las convenciones del destino y la constitución del cliente.', phases: ['generation'], capabilities: ['longContext'], tools: ['readWorkspace'], mandatory: false, level: 'certified', version: '1.1.0', defaultProfile: 'review', relativeCost: 1 },
  { id: 'security-auditor', name: 'Security auditor', nameEs: 'Auditor de seguridad', group: 'quality', description: 'Scans legacy and generated code for OWASP issues, secrets and vulnerable dependencies.', descriptionEs: 'Analiza el código legacy y el generado en busca de problemas OWASP, secretos y dependencias vulnerables.', phases: ['hardening'], capabilities: ['toolCalling'], tools: ['readWorkspace', 'sandbox'], mandatory: false, level: 'certified', version: '1.2.0', defaultProfile: 'review', relativeCost: 1 },
  { id: 'rules-verifier', name: 'Rules verifier', nameEs: 'Verificador de reglas', group: 'control', description: 'Independently checks every citation and that each rule explains its whole slice.', descriptionEs: 'Verifica de forma independiente cada cita y que cada regla explique todo su slice.', phases: ['ruleExtraction', 'consolidation'], capabilities: ['longContext', 'structuredOutput'], tools: ['readGraph', 'readCode'], mandatory: true, level: 'certified', version: '1.3.0', defaultProfile: 'review', relativeCost: 2 },
  { id: 'equivalence-validator', name: 'Equivalence validator', nameEs: 'Validador de equivalencia', group: 'control', description: 'Re-runs tests from clean, compares outputs, invents fresh inputs and runs the canary.', descriptionEs: 'Re-ejecuta las pruebas desde cero, compara salidas, inventa inputs nuevos y corre el canario.', phases: ['verification'], capabilities: ['toolCalling'], tools: ['readWorkspace', 'sandbox'], mandatory: true, level: 'certified', version: '1.4.0', defaultProfile: 'review', relativeCost: 2 },
  { id: 'acceptance-judge', name: 'Acceptance judge', nameEs: 'Juez de aceptación', group: 'control', description: 'Runs acceptance, contract and visual checks against the approved specification.', descriptionEs: 'Ejecuta las pruebas de aceptación, contrato y fidelidad visual contra la especificación aprobada.', phases: ['validation'], capabilities: ['toolCalling', 'vision'], tools: ['readWorkspace', 'sandbox'], mandatory: true, level: 'certified', version: '1.0.0', defaultProfile: 'review', relativeCost: 2 },
]

export const skills: SkillDefinition[] = [
  { id: 'cobol-data-semantics', name: 'COBOL data semantics', type: 'source', description: 'COMP-3, zoned decimals, EBCDIC, REDEFINES and sort-order pitfalls.', appliesTo: ['data-analyst', 'rules-extractor'], tags: ['COBOL', 'COBOL CICS'], conflictsWith: [], version: '1.3.0', evalScore: 0.95, status: 'published' },
  { id: 'exec-cics', name: 'EXEC CICS commands', type: 'source', description: 'LINK, XCTL, READ, SYNCPOINT and pseudo-conversational state.', appliesTo: ['legacy-analyst', 'rules-extractor'], tags: ['COBOL CICS'], conflictsWith: [], version: '1.1.0', evalScore: 0.91, status: 'published' },
  { id: 'bms-parsing', name: 'BMS map parsing', type: 'source', description: 'DFHMSD/DFHMDI/DFHMDF fields, positions, lengths and attributes.', appliesTo: ['ui-analyst'], tags: ['BMS maps'], conflictsWith: [], version: '1.0.2', evalScore: 0.99, status: 'published' },
  { id: 'sybase-tsql', name: 'Sybase T-SQL', type: 'source', description: 'Temp tables, cursors, @@error, chained mode and implicit conversions.', appliesTo: ['legacy-analyst', 'rules-extractor', 'data-analyst'], tags: ['Sybase ASE stored procedures'], conflictsWith: [], version: '0.9.0', evalScore: 0.88, status: 'published' },
  { id: 'webforms', name: 'ASP.NET WebForms', type: 'source', description: 'ViewState, postbacks, code-behind, server controls and web.config.', appliesTo: ['legacy-analyst', 'ui-analyst', 'rules-extractor'], tags: ['ASP.NET WebForms'], conflictsWith: [], version: '0.6.0', evalScore: null, status: 'evaluating' },
  { id: 'spring-hexagonal', name: 'Spring Boot hexagonal', type: 'target', description: 'Ports and adapters layout, conventions and test setup for Spring Boot.', appliesTo: ['backend-dev', 'fullstack-dev', 'code-reviewer'], tags: ['Java Spring Boot'], conflictsWith: ['quarkus'], version: '2.0.0', evalScore: 0.93, status: 'published' },
  { id: 'quarkus', name: 'Quarkus services', type: 'target', description: 'Quarkus layout, Panache persistence and native build settings.', appliesTo: ['backend-dev', 'fullstack-dev', 'code-reviewer'], tags: ['Java Quarkus'], conflictsWith: ['spring-hexagonal'], version: '1.0.0', evalScore: 0.86, status: 'published' },
  { id: 'dotnet10', name: '.NET 10 minimal APIs', type: 'target', description: 'Minimal APIs, EF Core and hexagonal layout for .NET 10.', appliesTo: ['backend-dev', 'fullstack-dev', 'code-reviewer'], tags: ['.NET 10'], conflictsWith: [], version: '1.1.0', evalScore: 0.9, status: 'published' },
  { id: 'angular-material', name: 'Angular + Material', type: 'target', description: 'Standalone components, typed forms and Angular Material.', appliesTo: ['frontend-dev', 'fullstack-dev'], tags: ['Angular'], conflictsWith: [], version: '1.2.0', evalScore: 0.89, status: 'published' },
  { id: 'react-ds', name: 'React + design system', type: 'target', description: 'React with the approved design system and a generated typed API client.', appliesTo: ['frontend-dev', 'fullstack-dev', 'ux-designer'], tags: ['React', 'Next.js'], conflictsWith: [], version: '1.3.0', evalScore: 0.9, status: 'published' },
  { id: 'postgres', name: 'PostgreSQL persistence', type: 'target', description: 'Schema, migrations, NUMERIC precision and collation rules.', appliesTo: ['data-architect', 'backend-dev', 'data-migration'], tags: ['PostgreSQL'], conflictsWith: [], version: '1.4.0', evalScore: 0.94, status: 'published' },
  { id: 'aws-iac', name: 'AWS IaC', type: 'target', description: 'Terraform modules for ECS/EKS, RDS, Step Functions and KMS.', appliesTo: ['devops'], tags: ['AWS'], conflictsWith: [], version: '0.9.0', evalScore: null, status: 'published' },
  { id: 'azure-iac', name: 'Azure IaC', type: 'target', description: 'Terraform modules for AKS, Azure Database, Logic Apps and Key Vault.', appliesTo: ['devops'], tags: ['Azure'], conflictsWith: [], version: '0.8.0', evalScore: null, status: 'published' },
  { id: 'cics-to-rest', name: 'CICS pseudo-conversational → REST', type: 'conversion', description: 'Maps COMMAREA state and transactions to stateless REST services.', appliesTo: ['solution-architect', 'backend-dev'], tags: ['COBOL CICS'], conflictsWith: [], version: '1.0.0', evalScore: 0.87, status: 'published' },
  { id: 'bms-to-forms', name: 'BMS → modern forms', type: 'conversion', description: 'Turns 3270 fields and attributes into accessible web form components.', appliesTo: ['ux-designer', 'frontend-dev'], tags: ['BMS maps'], conflictsWith: [], version: '0.9.0', evalScore: 0.92, status: 'published' },
  { id: 'sybase-to-service', name: 'Sybase SP → service layer', type: 'conversion', description: 'Moves stored procedure logic into domain services with equivalent transactions.', appliesTo: ['solution-architect', 'backend-dev'], tags: ['Sybase ASE stored procedures'], conflictsWith: [], version: '0.8.0', evalScore: 0.84, status: 'published' },
  { id: 'vsam-to-postgres', name: 'VSAM → PostgreSQL', type: 'conversion', description: 'Key design, record layouts and data conversion scripts.', appliesTo: ['data-architect', 'data-migration'], tags: ['COBOL', 'COBOL CICS'], conflictsWith: [], version: '0.7.0', evalScore: null, status: 'evaluating' },
  { id: 'owasp', name: 'OWASP secure coding', type: 'crossCutting', description: 'Input validation, authZ checks, secrets handling and dependency hygiene.', appliesTo: ['backend-dev', 'frontend-dev', 'fullstack-dev', 'security-auditor', 'code-reviewer'], tags: ['*'], conflictsWith: [], version: '1.5.0', evalScore: 0.9, status: 'published' },
  { id: 'gherkin', name: 'Gherkin specifications', type: 'crossCutting', description: 'Concrete Given/When/Then scenarios with real values.', appliesTo: ['rules-extractor', 'functional-analyst', 'test-engineer'], tags: ['*'], conflictsWith: [], version: '1.2.0', evalScore: 0.93, status: 'published' },
  { id: 'golden-master', name: 'Golden master testing', type: 'crossCutting', description: 'Recording legacy outputs, masks, tolerances and fresh inputs.', appliesTo: ['test-engineer', 'equivalence-validator'], tags: ['*'], conflictsWith: [], version: '1.1.0', evalScore: 0.96, status: 'published' },
  { id: 'wcag', name: 'WCAG 2.1 AA', type: 'crossCutting', description: 'Accessible forms, contrast, keyboard navigation and ARIA.', appliesTo: ['ux-designer', 'frontend-dev', 'acceptance-judge'], tags: ['*'], conflictsWith: [], version: '1.0.0', evalScore: 0.88, status: 'published' },
  { id: 'andes-conventions', name: 'Andes Bank conventions', type: 'customer', description: 'Naming, logging, error codes and audit fields required by the customer.', appliesTo: ['backend-dev', 'frontend-dev', 'fullstack-dev', 'code-reviewer'], tags: ['*'], conflictsWith: [], version: '1.0.0', evalScore: null, status: 'published' },
]

export const connections: ProviderConnection[] = [
  { id: 'c1', provider: 'azureFoundry', name: 'Andes — Azure AI Foundry', region: 'eastus2', auth: 'Entra ID service principal', status: 'connected', models: 6, lastCheck: '2026-09-28T07:00:00Z' },
  { id: 'c2', provider: 'awsBedrock', name: 'Andes — AWS Bedrock', region: 'us-east-1', auth: 'IAM role (cross-account)', status: 'connected', models: 9, lastCheck: '2026-09-28T07:00:00Z' },
  { id: 'c3', provider: 'openai', name: 'NexTI — OpenAI API', region: 'global', auth: 'API key (Vault)', status: 'connected', models: 5, lastCheck: '2026-09-28T07:00:00Z' },
  { id: 'c4', provider: 'anthropic', name: 'NexTI — Anthropic API', region: 'global', auth: 'API key (Vault)', status: 'error', models: 0, lastCheck: '2026-09-28T06:58:00Z' },
  { id: 'c5', provider: 'vertex', name: 'Google Vertex AI', region: '—', auth: '—', status: 'notConfigured', models: 0, lastCheck: '' },
]

export const offerings: ModelOffering[] = [
  { id: 'o1', family: 'Claude', model: 'Claude Opus', version: '5.5', connectionId: 'c2', providerModelId: 'bedrock/claude-opus-5-5 (sample)', region: 'us-east-1', contextK: 200, capabilities: ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'], inputPerMTokUsd: 15, outputPerMTokUsd: 75, status: 'available' },
  { id: 'o2', family: 'Claude', model: 'Claude Sonnet', version: '5', connectionId: 'c1', providerModelId: 'deployment: andes-sonnet-5', region: 'eastus2', contextK: 200, capabilities: ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'], inputPerMTokUsd: 3, outputPerMTokUsd: 15, status: 'available' },
  { id: 'o3', family: 'Claude', model: 'Claude Sonnet', version: '5', connectionId: 'c2', providerModelId: 'bedrock/claude-sonnet-5 (sample)', region: 'us-east-1', contextK: 200, capabilities: ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'], inputPerMTokUsd: 3, outputPerMTokUsd: 15, status: 'available' },
  { id: 'o4', family: 'Claude', model: 'Claude Haiku', version: '4.5', connectionId: 'c2', providerModelId: 'bedrock/claude-haiku-4-5 (sample)', region: 'us-east-1', contextK: 200, capabilities: ['toolCalling', 'vision', 'structuredOutput'], inputPerMTokUsd: 1, outputPerMTokUsd: 5, status: 'available' },
  { id: 'o5', family: 'GPT', model: 'GPT (large)', version: 'sample-2026-06', connectionId: 'c3', providerModelId: 'gpt-large-sample', region: 'global', contextK: 256, capabilities: ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'], inputPerMTokUsd: 5, outputPerMTokUsd: 20, status: 'available' },
  { id: 'o6', family: 'GPT', model: 'GPT (mini)', version: 'sample-2026-06', connectionId: 'c3', providerModelId: 'gpt-mini-sample', region: 'global', contextK: 128, capabilities: ['toolCalling', 'vision', 'structuredOutput'], inputPerMTokUsd: 0.5, outputPerMTokUsd: 2, status: 'available' },
  { id: 'o7', family: 'GPT', model: 'GPT (large)', version: 'sample-2026-06', connectionId: 'c1', providerModelId: 'deployment: andes-gpt-large', region: 'eastus2', contextK: 256, capabilities: ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'], inputPerMTokUsd: 5.5, outputPerMTokUsd: 22, status: 'available' },
]

export const profiles: ModelProfile[] = [
  { id: 'deep-analysis', name: 'Deep analysis', offeringId: 'o2', effort: 'high', providerParameter: 'effort = high', maxOutputTokens: 32000, fallbackOfferingId: 'o3' },
  { id: 'fast-analysis', name: 'Fast analysis', offeringId: 'o4', effort: 'low', providerParameter: 'effort = low', maxOutputTokens: 8000, fallbackOfferingId: 'o6' },
  { id: 'codegen', name: 'Code generation', offeringId: 'o3', effort: 'medium', providerParameter: 'effort = medium', maxOutputTokens: 64000, fallbackOfferingId: 'o2' },
  { id: 'review', name: 'Independent review', offeringId: 'o5', effort: 'high', providerParameter: 'reasoning_effort = high', maxOutputTokens: 16000, fallbackOfferingId: 'o7' },
  { id: 'vision', name: 'Vision', offeringId: 'o5', effort: 'medium', providerParameter: 'reasoning_effort = medium', maxOutputTokens: 16000, fallbackOfferingId: 'o2' },
  { id: 'max-reasoning', name: 'Maximum reasoning', offeringId: 'o1', effort: 'max', providerParameter: 'effort = max', maxOutputTokens: 64000, fallbackOfferingId: 'o2' },
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
  { id: 'RULE-001', name: 'Credit limit check on purchase', domain: 'Authorizations', category: 'validation', priority: 'P0', confidence: 'high', status: 'approved', statement: 'A purchase is declined when it would take the balance over the credit limit.', given: 'an account with limit 5,000.00 and balance 4,900.00', when: 'a purchase of 150.00 is authorized', then: 'the purchase is declined with reason code 51', source: 'COCRDUPC.cbl:412-438', testStatus: 'namedNotRun' },
  { id: 'RULE-002', name: 'Daily interest accrual', domain: 'Interest', category: 'calculation', priority: 'P0', confidence: 'high', status: 'approved', statement: 'Daily interest is balance × annual rate ÷ 360, rounded half-up to 2 decimals.', given: 'a balance of 12,345.67 and an annual rate of 18.5%', when: 'the nightly accrual runs', then: 'interest of 6.34 is posted', source: 'CBACT04C.cbl:233-260', testStatus: 'namedNotRun' },
  { id: 'RULE-003', name: 'Card expiry validation', domain: 'Cards', category: 'validation', priority: 'P1', confidence: 'medium', status: 'question', statement: 'A card cannot be activated after its expiry month.', given: 'a card expiring 2026-08', when: 'activation is requested on 2026-09-02', then: 'activation is rejected', source: 'COCRDUPC.cbl:510-527', smeQuestion: 'Is the expiry inclusive of the last day of the month?', testStatus: 'none' },
  { id: 'RULE-004', name: 'Late fee on missed minimum payment', domain: 'Billing', category: 'policy', priority: 'P0', confidence: 'medium', status: 'inReview', statement: 'A late fee of 25.00 is charged when the minimum payment is not received by the due date.', given: 'a statement with minimum payment 80.00 due 2026-09-10', when: 'no payment is received by 2026-09-10', then: 'a late fee of 25.00 is posted on 2026-09-11', source: 'CBSTM03A.cbl:118-141', testStatus: 'none' },
  { id: 'RULE-005', name: 'Account status transitions', domain: 'Accounts', category: 'lifecycle', priority: 'P1', confidence: 'high', status: 'approved', statement: 'Only active accounts can be suspended; suspended accounts can be reactivated or closed.', given: 'a suspended account', when: 'a reactivation is requested', then: 'the account becomes active', source: 'COACTUPC.cbl:640-702', testStatus: 'namedNotRun' },
  { id: 'RULE-006', name: 'Customer name mandatory fields', domain: 'Customers', category: 'validation', priority: 'P2', confidence: 'high', status: 'draft', statement: 'First and last names are mandatory and alphabetic.', given: 'a customer update with last name "O2"', when: 'the update is submitted', then: 'the field is rejected with message "Last name must be alphabetic"', source: 'COACTUPC.cbl:1102-1130', testStatus: 'none' },
]

export const runEvents: RunEvent[] = [
  { id: 'e1', time: '09:14:02', agent: 'Business rules extractor', phase: 'ruleExtraction', kind: 'fanOut', detail: '12 subagents launched, one per shard (ACCT, CARD, AUTH, BILL…).' },
  { id: 'e2', time: '09:21:40', agent: 'Business rules extractor', phase: 'ruleExtraction', kind: 'completed', detail: 'Shard AUTH: 23 candidate rules.', tokens: 1_240_000 },
  { id: 'e3', time: '09:22:05', agent: 'Rules verifier', phase: 'ruleExtraction', kind: 'verificationFailed', detail: 'RULE-017: citation COCRDUPC.cbl:980 does not support the stated threshold.' },
  { id: 'e4', time: '09:22:51', agent: 'Business rules extractor', phase: 'ruleExtraction', kind: 'selfCorrected', detail: 'RULE-017 corrected to cite COCRDUPC.cbl:1004-1011 (iteration 2 of 3).', tokens: 84_000 },
  { id: 'e5', time: '09:30:12', agent: 'Rules verifier', phase: 'ruleExtraction', kind: 'escalated', detail: 'RULE-031: two judges disagree on the rounding mode. Sent to the SME.' },
  { id: 'e6', time: '09:41:00', agent: 'Supervisor', phase: 'ruleReview', kind: 'gateWaiting', detail: 'Gate C1 — 148 rules waiting for business approval.' },
]

export const tasks: Task[] = [
  { id: 'k1', projectId: 'p1', kind: 'approveSpec', title: 'Approve 51 rules in Authorizations and Billing', due: '2026-09-30', priority: 'high' },
  { id: 'k2', projectId: 'p1', kind: 'answerQuestion', title: 'RULE-003: is card expiry inclusive of the last day?', due: '2026-09-29', priority: 'normal' },
  { id: 'k3', projectId: 'p1', kind: 'escalation', title: 'RULE-031: judges disagree on the rounding mode', due: '2026-09-29', priority: 'high' },
  { id: 'k4', projectId: 'p4', kind: 'reviewPrototype', title: 'Review 8 onboarding prototypes and the design system', due: '2026-10-02', priority: 'normal' },
  { id: 'k5', projectId: 'p2', kind: 'signOff', title: 'Sign off the verification of module ACCRUAL', due: '2026-10-01', priority: 'normal' },
  { id: 'k6', projectId: 'p4', kind: 'approveArchitecture', title: 'Approve bounded contexts and OpenAPI contracts', due: '2026-10-05', priority: 'normal' },
]

export const users: User[] = [
  { id: 'u1', name: 'David Balseca', email: 'david.balseca@nexti.example', tenant: 'NexTI Internal', roles: ['superAdmin'], mfa: true, lastSeen: '2026-09-28T09:40:00Z', status: 'active' },
  { id: 'u2', name: 'María Torres', email: 'mtorres@andesbank.example', tenant: 'Andes Bank', roles: ['tenantAdmin', 'projectOwner'], mfa: true, lastSeen: '2026-09-28T09:12:00Z', status: 'active' },
  { id: 'u3', name: 'Luis Andrade', email: 'landrade@andesbank.example', tenant: 'Andes Bank', roles: ['architect'], mfa: true, lastSeen: '2026-09-28T08:30:00Z', status: 'active' },
  { id: 'u4', name: 'Ana Vélez', email: 'avelez@pacificcu.example', tenant: 'Pacific Credit Union', roles: ['businessReviewer'], mfa: true, lastSeen: '2026-09-27T20:10:00Z', status: 'active' },
  { id: 'u5', name: 'Jorge Mena', email: 'jmena@andesbank.example', tenant: 'Andes Bank', roles: ['auditor'], mfa: false, lastSeen: '', status: 'invited' },
  { id: 'u6', name: 'Carlos Ruiz', email: 'cruiz@nexti.example', tenant: 'NexTI Internal', roles: ['analyst', 'developer'], mfa: true, lastSeen: '2026-09-26T15:00:00Z', status: 'active' },
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
  { id: 'a1', time: '2026-09-28T09:41:00Z', actor: 'Supervisor (agent)', action: 'gate.waiting', target: 'p1 / C1', tenant: 'Andes Bank' },
  { id: 'a2', time: '2026-09-28T09:12:00Z', actor: 'María Torres', action: 'rule.approve', target: 'p1 / RULE-001', tenant: 'Andes Bank' },
  { id: 'a3', time: '2026-09-28T08:55:00Z', actor: 'Luis Andrade', action: 'profile.update', target: 'p2 / codegen → effort medium', tenant: 'Andes Bank' },
  { id: 'a4', time: '2026-09-28T08:31:00Z', actor: 'David Balseca', action: 'connection.test', target: 'c4 Anthropic API (failed: 401)', tenant: 'NexTI Internal' },
  { id: 'a5', time: '2026-09-27T21:05:00Z', actor: 'Ana Vélez', action: 'input.upload', target: 'p4 / onboarding.fig', tenant: 'Pacific Credit Union' },
  { id: 'a6', time: '2026-09-27T18:20:00Z', actor: 'System', action: 'budget.alert80', target: 'p1 (80% of budget)', tenant: 'Andes Bank' },
  { id: 'a7', time: '2026-09-27T17:02:00Z', actor: 'María Torres', action: 'user.invite', target: 'jmena@andesbank.example (auditor)', tenant: 'Andes Bank' },
]

export const identityProviders = [
  { id: 'idp1', tenant: 'Andes Bank', type: 'Microsoft Entra ID (OIDC)', domains: ['andesbank.example'], enforced: true, status: 'active' },
  { id: 'idp2', tenant: 'Pacific Credit Union', type: 'Okta (SAML 2.0)', domains: ['pacificcu.example'], enforced: false, status: 'active' },
  { id: 'idp3', tenant: 'NexTI Internal', type: 'Google Workspace (OIDC)', domains: ['nexti.example'], enforced: false, status: 'active' },
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
  { id: 'd2', name: 'Andes Bank data plane (customer AWS)', model: 'customerCloud', version: '0.1.0', tenants: 1, status: 'healthy' },
  { id: 'd3', name: 'Staging', model: 'sharedSaas', version: '0.2.0-rc.1', tenants: 0, status: 'updating' },
]
