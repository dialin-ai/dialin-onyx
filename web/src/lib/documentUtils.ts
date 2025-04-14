import { OnyxDocument } from "./search/interfaces";
import { DocumentSet } from "./types";
import { fetchWithCredentials } from "./fetchUtils";

export function removeDuplicateDocs(
  documents: OnyxDocument[],
  agentic?: boolean,
  relevance?: any
) {
  const seen = new Set<string>();
  const output: OnyxDocument[] = [];
  documents.forEach((document) => {
    if (
      document.document_id &&
      !seen.has(document.document_id) &&
      (!agentic || (agentic && relevance && relevance[document.document_id]))
    ) {
      output.push(document);
      seen.add(document.document_id);
    }
  });
  return output;
}

export async function getDocumentSetIdsByName(names: string[]): Promise<Map<string, number>> {
  try {
    const response = await fetchWithCredentials('/api/manage/document-set');
    if (!response.ok) {
      throw new Error(`Failed to fetch document sets: ${response.statusText}`);
    }
    
    const documentSets: DocumentSet[] = await response.json();
    const nameToIdMap = new Map<string, number>();
    
    names.forEach(name => {
      const documentSet = documentSets.find(ds => ds.name === name);
      if (documentSet) {
        nameToIdMap.set(name, documentSet.id);
      }
    });
    
    return nameToIdMap;
  } catch (error) {
    console.error('Error fetching document set IDs:', error);
    throw error;
  }
}
