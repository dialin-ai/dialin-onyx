'use client';

import React, { useState, useRef, useEffect } from 'react';
import { 
  Message, 
  AnalysisResponse, 
  RegulationContent, 
  ArticleContent, 
  CitationContent,
  RegulationItem,
  ArticleItem,
  CitationItem,
  SummaryContent
} from '@/app/chat/marketing/types';
import { useUser } from '@/components/user/UserProvider';
import { fetchWithCredentials } from '@/lib/fetchUtils';
import { APP_BASE_URL } from '@/lib/constants';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useTheme } from 'next-themes';

const API_URL = `${APP_BASE_URL}/regulation-analysis/analyze`;

function MarketingAnalysis() {
  const { user } = useUser();
  const { theme } = useTheme();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

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
          consideration.severity === 'medium' ? 'bg-warning/20 hover:bg-warning/30' :
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
              const data = JSON.parse(line.slice(6));
              if (data.type === 'error') {
                throw new Error(data.content);
              }

              setMessages(prev => {
                const newMessages = [...prev];
                const analysisMessageIndex = newMessages.findIndex(m => m.id === analysisMessage.id);
                if (analysisMessageIndex !== -1) {
                  const currentMessage = newMessages[analysisMessageIndex];
                  newMessages[analysisMessageIndex] = {
                    ...currentMessage,
                    analysis: [...(currentMessage.analysis || []), data],
                  };
                }
                return newMessages;
              });
            } catch (e) {
              console.error('Error parsing SSE data:', e);
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
        citations: CitationItem[]
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
            citations: []
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
                    <p className="mt-1 p-2 bg-background rounded border border-border">"{consideration.text_segment}"</p>
                  </div>
                  <div className="mb-2">
                    <span className="font-medium text-foreground">Analysis:</span>
                    <p className="mt-1 text-foreground">{consideration.analysis}</p>
                  </div>
                  <div>
                    <span className="font-medium text-foreground">Recommended Action:</span>
                    <div className="mt-1 p-2 bg-background rounded border border-border">
                      {consideration.recommended_action}
                    </div>
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
                        {artData.citations.map((cit, citIndex) => (
                          <div key={citIndex} className="border-l-2 border-secondary/20 pl-4 py-2">
                            <div className="font-medium text-secondary-foreground">{cit.citation}</div>
                          </div>
                        ))}
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
    <div className="flex flex-col h-screen bg-background">
      <div className="flex-1 overflow-auto">
        <div className="max-w-7xl mx-auto px-4 py-8">
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
        <div className="max-w-7xl min-w-[70%] mx-auto px-4 py-6">
          <form onSubmit={handleSubmit}>
            <div className="flex gap-4">
              <Input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder="Enter text to analyze..."
                disabled={isLoading}
                className="flex-1 text-lg py-6 min-w-[70em]"
              />
              <Button 
                type="submit" 
                disabled={isLoading}
                variant="default"
                size="lg"
                className="px-8"
              >
                {isLoading ? 'Analyzing...' : 'Analyze'}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

export default MarketingAnalysis; 