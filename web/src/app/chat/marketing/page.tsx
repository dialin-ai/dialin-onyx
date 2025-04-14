'use client';

import React, { useState, useRef, useEffect } from 'react';
import { 
  Message, 
  AnalysisResponse, 
  RegulationItem,
  ArticleItem,
  CitationItem,
  SummaryContent,
  RelatedDocumentContent
} from '@/app/chat/marketing/types';
import { useUser } from '@/components/user/UserProvider';
import { fetchWithCredentials } from '@/lib/fetchUtils';
import { APP_BASE_URL } from '@/lib/constants';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useTheme } from 'next-themes';
import { Sidebar } from '@/components/navigation/Sidebar';

const API_URL = `${APP_BASE_URL}/regulation-analysis/analyze`;

function MarketingAnalysis() {
  const { user } = useUser();
  const { theme } = useTheme();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [relatedDocuments, setRelatedDocuments] = useState<RelatedDocumentContent[]>([]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const renderHighlightedText = (text: string, considerations: SummaryContent['summary']['considerations']) => {
    if (!considerations?.length) return text;

    // Sort considerations by text_segment length (longest first) to handle overlapping highlights
    const sortedConsiderations = [...considerations].sort(
      (a, b) => b.text_segment.length - a.text_segment.length
    );

    let result = text;
    let offset = 0;

    sortedConsiderations.forEach(consideration => {
      const segment = consideration.text_segment;
      const index = result.indexOf(segment, offset);
      if (index !== -1) {
        const before = result.slice(0, index);
        const after = result.slice(index + segment.length);
        const severityColor = 
          consideration.severity === 'high' ? 'bg-destructive/20 hover:bg-destructive/30' :
          consideration.severity === 'medium' ? 'bg-info/20 hover:bg-info/30' :
          'bg-info/20 hover:bg-info/30';
        
        const tooltip = `
          <div class="text-sm">
            <div class="font-semibold">${consideration.regulation} - ${consideration.article}</div>
            <div class="mt-1">${consideration.analysis}</div>
            <div class="mt-1 font-medium">Recommendation: ${consideration.recommended_action}</div>
          </div>
        `;

        result = `${before}<span 
          class="relative group ${severityColor} rounded px-0.5 cursor-help transition-colors"
          data-tooltip="${encodeURIComponent(tooltip)}"
        >${segment}<span 
          class="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 w-64 p-2 bg-popover text-popover-foreground text-sm rounded-lg opacity-0 group-hover:opacity-100 transition-opacity z-50 pointer-events-none shadow-lg"
          dangerouslySetInnerHTML={{ __html: tooltip }}
        ></span></span>${after}`;
        offset = index + result.length - after.length;
      }
    });

    return <div className="text-foreground" dangerouslySetInnerHTML={{ __html: result }} />;
  };

  const renderMessage = (message: Message) => {
    // Find summary data if it exists
    let summaryContent: SummaryContent | null = null;
    if (message.analysis) {
      const summaryResponse = message.analysis.find((item: AnalysisResponse) => item.type === 'summary');
      if (summaryResponse) {
        try {
          summaryContent = typeof summaryResponse.content === 'string' 
            ? JSON.parse(summaryResponse.content) 
            : summaryResponse.content as SummaryContent;
        } catch (e) {
          console.error('Error parsing summary:', e);
        }
      }
    }

    return (
      <Card key={message.id} className={`p-4 ${
        message.type === 'user' ? 'bg-primary/10' : 'bg-card'
      }`}>
        <div className="flex items-center justify-between mb-2">
          <span className="font-medium text-foreground">
            {message.type === 'user' ? 'You' : 'Analysis'}
          </span>
          <span className="text-sm text-muted-foreground">
            {message.timestamp.toLocaleTimeString()}
          </span>
        </div>
        {message.type === 'user' ? (
          summaryContent ? (
            renderHighlightedText(message.text, summaryContent.summary.considerations)
          ) : (
            <p className="text-foreground">{message.text}</p>
          )
        ) : (
          <div>
            <p className="text-foreground">{message.text}</p>
            {message.analysis && message.analysis.length > 0 && renderAnalysis(message.analysis)}
          </div>
        )}
      </Card>
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      text: input,
      type: 'user',
      timestamp: new Date(),
    };

    const analysisMessage: Message = {
      id: (Date.now() + 1).toString(),
      text: 'Analysis in progress...',
      type: 'analysis',
      timestamp: new Date(),
      analysis: [],
    };

    setMessages(prev => [...prev, userMessage, analysisMessage]);
    setInput('');
    setIsLoading(true);

    // Reset textarea height
    const textarea = document.querySelector('textarea');
    if (textarea) {
      textarea.style.height = '2.75rem';
    }

    try {
      const response = await fetchWithCredentials(API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({ text: input }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('No reader available');
      }

      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += new TextDecoder().decode(value);
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              console.log('Processing SSE line:', line.slice(6));
              const data = JSON.parse(line.slice(6));
              console.log('Parsed SSE data:', data);

              if (data.type === 'error') {
                throw new Error(data.content);
              }

              setMessages(prev => {
                const newMessages = [...prev];
                const analysisMessageIndex = newMessages.findIndex(m => m.id === analysisMessage.id);
                if (analysisMessageIndex !== -1) {
                  const currentMessage = newMessages[analysisMessageIndex];
                  const newAnalysis = [...(currentMessage.analysis || [])];

                  // Add the new data
                  newAnalysis.push(data);

                  // Process regulations first
                  const regulationMap = new Map<string, {
                    regulation: RegulationItem,
                    articles: Map<string, {
                      article: ArticleItem,
                      citations: CitationItem[],
                      relatedDocuments: RelatedDocumentContent[]
                    }>
                  }>();

                  // Process regulations
                  newAnalysis.filter(item => item.type === 'regulation').forEach(item => {
                    const content = typeof item.content === 'string' ? JSON.parse(item.content) : item.content;
                    content.regulations?.forEach((reg: RegulationItem) => {
                      regulationMap.set(reg.regulation, {
                        regulation: reg,
                        articles: new Map()
                      });
                    });
                  });

                  // Process articles
                  newAnalysis.filter(item => item.type === 'article').forEach(item => {
                    const content = typeof item.content === 'string' ? JSON.parse(item.content) : item.content;
                    content.articles?.forEach((art: ArticleItem) => {
                      const regData = regulationMap.get(art.regulation);
                      if (regData) {
                        regData.articles.set(art.article, {
                          article: art,
                          citations: [],
                          relatedDocuments: []
                        });
                      }
                    });
                  });

                  // Process citations
                  newAnalysis.filter(item => item.type === 'citation').forEach(item => {
                    const content = typeof item.content === 'string' ? JSON.parse(item.content) : item.content;
                    content.citations?.forEach((cit: CitationItem) => {
                      const regData = regulationMap.get(cit.regulation);
                      if (regData) {
                        const artData = regData.articles.get(cit.article);
                        if (artData) {
                          artData.citations.push(cit);
                        }
                      }
                    });
                  });

                  // Process related documents
                  newAnalysis.filter(item => item.type === 'related_document').forEach(item => {
                    try {
                      console.log('Processing related document:', item);
                      const content = typeof item.content === 'string' ? JSON.parse(item.content) : item.content as RelatedDocumentContent;
                      console.log('Parsed content:', content);
                      const regData = regulationMap.get(content.regulation);
                      console.log('Found regulation data:', regData);
                      if (regData) {
                        const artData = regData.articles.get(content.article);
                        console.log('Found article data:', artData);
                        if (artData) {
                          artData.relatedDocuments.push(content);
                          console.log('Added document to article. Current related documents:', artData.relatedDocuments);
                        }
                      }
                    } catch (error) {
                      console.error('Error processing related document:', error, item);
                    }
                  });

                  newMessages[analysisMessageIndex] = {
                    ...currentMessage,
                    analysis: newAnalysis,
                  };
                }
                return newMessages;
              });

              if (data.type === 'related_document') {
                const content = data as RelatedDocumentContent;
                setRelatedDocuments(prev => [...prev, content]);
              }
            } catch (e) {
              console.error('Error parsing SSE data:', e, 'Raw data:', line.slice(6));
              // Don't throw the error, just log it and continue processing other messages
            }
          }
        }
      }

      setMessages(prev => {
        const newMessages = [...prev];
        const analysisMessageIndex = newMessages.findIndex(m => m.id === analysisMessage.id);
        if (analysisMessageIndex !== -1) {
          newMessages[analysisMessageIndex] = {
            ...newMessages[analysisMessageIndex],
            text: 'Analysis complete',
          };
        }
        return newMessages;
      });
    } catch (error) {
      console.error('Error:', error);
      setMessages(prev => {
        const newMessages = [...prev];
        const analysisMessageIndex = newMessages.findIndex(m => m.id === analysisMessage.id);
        if (analysisMessageIndex !== -1) {
          newMessages[analysisMessageIndex] = {
            ...newMessages[analysisMessageIndex],
            text: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
          };
        }
        return newMessages;
      });
    } finally {
      setIsLoading(false);
    }
  };

  const renderAnalysis = (analysis: AnalysisResponse[]) => {
    // Group all items by regulation
    const regulationMap = new Map<string, {
      regulation: RegulationItem,
      articles: Map<string, {
        article: ArticleItem,
        citations: CitationItem[],
        relatedDocuments: RelatedDocumentContent[]
      }>
    }>();

    // Find summary response
    const summaryResponse = analysis.find(item => item.type === 'summary');
    let summaryContent: SummaryContent | null = null;
    if (summaryResponse) {
      try {
        summaryContent = typeof summaryResponse.content === 'string' 
          ? JSON.parse(summaryResponse.content) 
          : summaryResponse.content;
      } catch (e) {
        console.error('Error parsing summary:', e);
      }
    }

    // Process regulations first
    analysis.filter(item => item.type === 'regulation').forEach(item => {
      const content = typeof item.content === 'string' ? JSON.parse(item.content) : item.content;
      content.regulations?.forEach((reg: RegulationItem) => {
        regulationMap.set(reg.regulation, {
          regulation: reg,
          articles: new Map()
        });
      });
    });

    // Process articles
    analysis.filter(item => item.type === 'article').forEach(item => {
      const content = typeof item.content === 'string' ? JSON.parse(item.content) : item.content;
      content.articles?.forEach((art: ArticleItem) => {
        const regData = regulationMap.get(art.regulation);
        if (regData) {
          regData.articles.set(art.article, {
            article: art,
            citations: [],
            relatedDocuments: []
          });
        }
      });
    });

    // Process citations
    analysis.filter(item => item.type === 'citation').forEach(item => {
      const content = typeof item.content === 'string' ? JSON.parse(item.content) : item.content;
      content.citations?.forEach((cit: CitationItem) => {
        const regData = regulationMap.get(cit.regulation);
        if (regData) {
          const artData = regData.articles.get(cit.article);
          if (artData) {
            artData.citations.push(cit);
          }
        }
      });
    });

    // Process related documents
    analysis.filter(item => item.type === 'related_document').forEach(item => {
      try {
        console.log('Processing related document:', item);
        const content = typeof item.content === 'string' ? JSON.parse(item.content) : item.content as RelatedDocumentContent;
        console.log('Parsed content:', content);
        const regData = regulationMap.get(content.regulation);
        console.log('Found regulation data:', regData);
        if (regData) {
          const artData = regData.articles.get(content.article);
          console.log('Found article data:', artData);
          if (artData) {
            artData.relatedDocuments.push(content);
            console.log('Added document to article. Current related documents:', artData.relatedDocuments);
          }
        }
      } catch (error) {
        console.error('Error processing related document:', error, item);
      }
    });

    return (
      <div className="mt-2 space-y-4">
        {/* Summary Section */}
        {summaryContent && (
          <div className="bg-muted/50 border border-border rounded-lg p-4 mb-6">
            <h3 className="text-lg font-semibold text-foreground mb-4">Analysis Summary</h3>
            <div className="space-y-4">
              {summaryContent.summary.considerations.map((consideration: SummaryContent['summary']['considerations'][0], index: number) => (
                <div key={index} className={`p-3 rounded-lg border-l-4 ${
                  consideration.severity === 'high' ? 'border-destructive bg-destructive/10' :
                  consideration.severity === 'medium' ? 'border-warning bg-warning/10' :
                  'border-info bg-info/10'
                }`}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium text-foreground">
                      {consideration.regulation} - {consideration.article}
                    </span>
                    <span className={`px-2 py-1 rounded text-sm ${
                      consideration.severity === 'high' ? 'bg-destructive/20 text-destructive-foreground' :
                      consideration.severity === 'medium' ? 'bg-warning/20 text-warning-foreground' :
                      'bg-info/20 text-info-foreground'
                    }`}>
                      {consideration.severity.toUpperCase()}
                    </span>
                  </div>
                  <div className="mb-2">
                    <span className="font-medium text-foreground">Related Text:</span>
                    <p className="mt-1 p-2 bg-background rounded border border-border">&ldquo;{consideration.text_segment}&rdquo;</p>
                  </div>
                  <div className="mb-2">
                    <span className="font-medium text-foreground">Analysis:</span>
                    <p className="mt-1 text-foreground">{consideration.analysis}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Regulations Section */}
        {Array.from(regulationMap.entries()).map(([regName, regData]) => (
          <details key={regName} className="border rounded-lg p-4 shadow-sm hover:shadow-md transition-shadow bg-card">
            <summary className="cursor-pointer font-semibold text-primary flex items-center">
              <span className="flex-1">{regName}</span>
            </summary>
            <div className="mt-2">
              <p className="text-muted-foreground mb-4">{regData.regulation.description}</p>
              
              <div className="space-y-2 pl-4">
                {Array.from(regData.articles.entries()).map(([artName, artData]) => (
                  <details key={artName} className="border-l-2 border-primary/20 pl-4 py-2">
                    <summary className="cursor-pointer font-medium text-primary flex items-center">
                      <span className="flex-1">{artName}</span>
                    </summary>
                    <div className="mt-2">
                      <p className="text-muted-foreground mb-4">{artData.article.description}</p>
                      
                      <div className="space-y-2 pl-4">
                        {/* Related Documents Section */}
                        {artData.relatedDocuments.length > 0 && (
                          <div className="mb-6">
                            <h4 className="text-sm font-medium text-foreground mb-2">Source Documents</h4>
                            <div className="space-y-2">
                              {artData.relatedDocuments.map((doc, docIndex) => {
                                // Ensure the document has a valid source type
                                const document = doc.document;
                                // For web documents, just show a link
                                if ((document.source_type === 'regulation' || document.source_type === 'web') && document.link) {
                                  return (
                                    <div key={docIndex} className="p-3 rounded-lg border border-border">
                                      <a 
                                        href={document.link} 
                                        target="_blank" 
                                        rel="noopener noreferrer"
                                        className="text-primary hover:text-primary/80 flex items-center gap-2"
                                      >
                                        <span className="truncate">{document.semantic_identifier || document.document_id}</span>
                                        <span className="text-xs text-muted-foreground">↗</span>
                                      </a>
                                      {document.blurb && (
                                        <p className="mt-2 text-sm text-muted-foreground line-clamp-2">{document.blurb}</p>
                                      )}
                                    </div>
                                  );
                                }
                              })}
                            </div>
                          </div>
                        )}
                        
                        {/* Citations Section */}
                        {artData.citations.length > 0 && (
                          <div>
                            <h4 className="text-sm font-medium text-foreground mb-2">Relevant Citations</h4>
                            {artData.citations.map((cit, citIndex) => (
                              <div key={citIndex} className="border-l-2 border-secondary/20 pl-4 py-2">
                                <div className="font-medium text-secondary-foreground">{cit.citation}</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </details>
                ))}
              </div>
            </div>
          </details>
        ))}
      </div>
    );
  };

  return (
    <div className="flex h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <div className="flex-1 overflow-auto">
          <div className="container max-w-4xl mx-auto px-4 py-8">
            <div className="space-y-4">
              {messages.map(message => (
                <Card key={message.id} className={`p-4 ${
                  message.type === 'user' ? 'bg-primary/10' : 'bg-card'
                }`}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium text-foreground">
                      {message.type === 'user' ? 'You' : 'Analysis'}
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {message.timestamp.toLocaleTimeString()}
                    </span>
                  </div>
                  {message.type === 'user' ? (
                    message.analysis ? (
                      renderAnalysis(message.analysis)
                    ) : (
                      <p className="text-foreground">{message.text}</p>
                    )
                  ) : (
                    <div>
                      <p className="text-foreground">{message.text}</p>
                      {message.analysis && message.analysis.length > 0 && renderAnalysis(message.analysis)}
                    </div>
                  )}
                </Card>
              ))}
              <div ref={messagesEndRef} />
            </div>
          </div>
        </div>

        <div className="border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="container mx-auto px-8 py-6 flex justify-center">
            <form onSubmit={handleSubmit} className="w-[60%]">
              <div className="flex w-full gap-4">
                <Textarea
                  value={input}
                  onChange={e => {
                    setInput(e.target.value);
                    e.target.style.height = 'auto';
                    const newHeight = Math.max(44, e.target.scrollHeight);
                    e.target.style.height = `${newHeight}px`;
                  }}
                  placeholder="Enter text to analyze..."
                  disabled={isLoading}
                  className="flex-1 text-base px-4 py-2 min-w-0 h-[2.75rem] resize-none overflow-hidden leading-normal"
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSubmit(e);
                    }
                  }}
                />
                <Button 
                  type="submit" 
                  disabled={isLoading}
                  variant="default"
                  size="lg"
                  className="px-8 whitespace-nowrap self-end h-[2.75rem]"
                >
                  {isLoading ? 'Analyzing...' : 'Analyze'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

export default MarketingAnalysis; 