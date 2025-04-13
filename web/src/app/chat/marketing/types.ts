import { ValidSources } from '@/lib/types';
import { SearchOnyxDocument } from '@/lib/search/interfaces';

export interface Message {
  id: string;
  text: string;
  type: 'user' | 'analysis';
  timestamp: Date;
  analysis?: AnalysisResponse[];
}

export interface AnalysisResponse {
  type: 'regulation' | 'article' | 'citation' | 'summary' | 'related_document';
  content: string | RegulationContent | ArticleContent | CitationContent | SummaryContent | RelatedDocumentContent;
}

export interface RegulationContent {
  regulations: RegulationItem[];
}

export interface RegulationItem {
  regulation: string;
  description: string;
}

export interface ArticleContent {
  articles: ArticleItem[];
}

export interface ArticleItem {
  regulation: string;
  article: string;
  description: string;
}

export interface CitationContent {
  citations: CitationItem[];
}

export interface CitationItem {
  regulation: string;
  article: string;
  citation: string;
}

export interface SummaryContent {
  summary: {
    considerations: Array<{
      text_segment: string;
      regulation: string;
      article: string;
      analysis: string;
      severity: 'high' | 'medium' | 'low';
      recommended_action: string;
    }>;
  };
}

export interface RelatedDocumentContent {
  regulation: string;
  article: string;
  document: SearchOnyxDocument;
} 