import { KnowledgeGraph } from '../graph/KnowledgeGraph'

// The Overview, Inputs and Settings tabs are connected in ../workspace (M2). The inventory graph keeps the prototype
// content until the inventory phase fills it (M4).
export function InventoryTab({ onCompare }: { onCompare: (ruleId: string) => void }) {
  return <KnowledgeGraph onCompare={onCompare} />
}
