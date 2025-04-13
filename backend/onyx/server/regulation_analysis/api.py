import asyncio
import json
import os
import logging
from typing import AsyncGenerator
from fastapi import FastAPI, Request, APIRouter, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.auth.users import User
from onyx.db.engine import get_session
from onyx.utils.logger import setup_logger
from onyx.llm.factory import get_default_llms
from onyx.llm.interfaces import LLM

# Configure logging
logger = setup_logger()

router = APIRouter(prefix="/regulation-analysis")

@router.options("/analyze")
async def options_handler(_: User | None = Depends(current_user)):
    return {"status": "ok"}

class AnalysisRequest(BaseModel):
    text: str

class RegulationDescriptor:
    def __init__(self):
        logger.info("Initializing RegulationDescriptor")
        # Get default LLMs from the system
        self.llm, self.fast_llm = get_default_llms()
        logger.info("LLM initialized")

    async def _call_llm_with_template(self, prompt: str, response_type: str) -> AsyncGenerator[str, None]:
        """
        Template method for making LLM API calls with standardized error handling and response formatting.
        """
        try:
            logger.info(f"Sending request to LLM for {response_type}")
            
            # Run the synchronous generator in a separate thread and collect content
            chunks = await asyncio.to_thread(lambda: [chunk.content for chunk in self.llm.stream(
                prompt,
                structured_response_format={"type": "json_object"}
            ) if chunk.content])
            
            if not chunks:
                logger.error(f"No content received from LLM for {response_type}")
                yield f"{json.dumps({'type': 'error', 'content': f'No response received for {response_type}'})}\n\n"
                return

            content = "".join(chunks)
            
            # Validate that we have valid JSON content
            try:
                json.loads(content)  # Just validate, we'll use the original string in the response
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON received from LLM for {response_type}: {str(e)}")
                yield f"{json.dumps({'type': 'error', 'content': f'Invalid response format for {response_type}'})}\n\n"
                return
                
            logger.info(f"Received complete {response_type} response")
            yield f"{json.dumps({'type': response_type, 'content': content})}\n\n"
            
        except Exception as e:
            logger.error(f"Error in {response_type} analysis: {str(e)}", exc_info=True)
            yield f"{json.dumps({'type': 'error', 'content': f'Error getting {response_type}: {str(e)}'})}\n\n"

    async def get_summary(self, user_input: str, regulations_data: dict, articles_data: list, citations_data: list) -> AsyncGenerator[str, None]:
        """
        Generates a summary of all regulations, articles, and citations with improved nuance.
        """
        summary_prompt = f"""
            You are an expert in the field of financial compliance and regulations, with understanding of both regulatory requirements and business context. 
            You are provided an original text, and related regulations/articles/citations.

            Original Text:
            ====================
            {user_input}
            ====================

            Regulations Found:
            {json.dumps(regulations_data, indent=2)}

            Articles Found:
            {json.dumps(articles_data, indent=2)}

            Citations Found:
            {json.dumps(citations_data, indent=2)}

            Given this information, please analyze the text in its full marketing and business context. Consider that:
            
            1. Marketing language often uses simplified terminology and shorthand that implies but doesn't state complete details
            2. Many compliance concerns may be addressed in other business documents or practices not visible in this text
            3. Not all regulatory considerations require explicit statements in marketing materials
            
            For each potential regulatory consideration, provide:
            1. The text segment that relates to regulatory considerations
            2. Which regulation and article is relevant
            3. A nuanced analysis that considers:
            - Whether this is truly problematic or just needs supporting documentation/procedures
            - The likely business context behind the statement
            - Whether this represents a true risk or merely an area to monitor
            4. The severity level using these guidelines:
            - HIGH: Clear violation with no reasonable interpretation otherwise
            - MEDIUM: Potential issue if certain business practices aren't in place
            - LOW: Area to monitor or document, but likely addressed through standard business practices
            5. Recommended action (which could include "No change needed, but ensure internal documentation exists")

            Provide your response as a JSON object with the following structure:
            {{
                "summary": {{
                    "considerations": [
                        {{
                            "text_segment": "The relevant text from the input",
                            "regulation": "Name of the regulation",
                            "article": "Specific article number/name",
                            "analysis": "Nuanced analysis considering context and business realities",
                            "severity": "high|medium|low",
                            "recommended_action": "Suggested action or documentation need"
                        }}
                    ]
                }}
            }} 
        """
        
        async for response in self._call_llm_with_template(summary_prompt, "summary"):
            yield response
    
    async def get_regulations(self, user_input: str) -> AsyncGenerator[str, None]:
        regulations_prompt = f"""
            You are an expert in the field of financial compliance and regulations with business context awareness. 
            Identify the regulations that may be relevant to the following marketing text:
            ====================
            {user_input}
            ====================
            
            Important: This is marketing text that necessarily simplifies complex business operations. When determining relevance:
            - Consider the likely underlying business processes, not just the exact wording
            - Include regulations that are relevant to the core business functions described, not just explicitly mentioned
            - Distinguish between regulations that would require explicit statements in marketing vs. those addressed in operational documents
            
            Provide a list of regulations that apply to the user input. Provide your response as a JSON array of objects. Each
            entry must contain a single, exact regulation name and a description of its relevance to the text. Provide all regulations
            you are aware of that apply to the text. 
            - Do not group regulations together in an entry. E.g. "Data Privacy Regulations e.g. GDPR, CCPA"
            is incorrect - this should be two separate entries "GDPR" and "CCPA". 
            - Do not list areas of regulations. E.g. "Know Your Customer (KYC) Regulations" is not itself a regulation, but an area covered by regulations such as CFPB.
            - Make your answer as complete as possible. If you miss any regulations, the user may be subject to penalties.
            {{"regulations": [
                {{
                    "regulation": "Regulation Name",
                    "description": "Description of how the user input relates to this regulation, considering business context"
                }},
                ...
            ]}}
        """
        async for response in self._call_llm_with_template(regulations_prompt, "regulation"):
            yield response

    async def get_articles_for_regulations(self, user_input: str, regulation: dict) -> AsyncGenerator[str, None]:
        articles_prompt = f"""
            You are an expert in the field of financial compliance and regulations with business context awareness. 
            Identify the articles from the regulation "{regulation['regulation']}" that may be relevant to the following marketing text:
            ====================
            {user_input}
            ====================
            
            Important: This is marketing text that necessarily simplifies complex business operations. When determining relevance:
            - Consider the likely underlying business processes, not just the exact wording
            - Distinguish between articles that would require explicit statements in marketing vs. those addressed in operational documents
            
            Provide a list of articles that apply to the regulation. Give exact article numbers, e.g. for CFPB consumer liability I would expect "§ 1005.6".
            - Make your answer as complete as possible. If you miss any articles, the user may be subject to penalties.
            Provide your response as a JSON array of objects:
            {{
                "articles": [
                    {{
                        "regulation": "Regulation Name",
                        "article": "Article Name / Article Number",  
                        "description": "Description of how the user input relates to this article, considering business context"
                    }},
                    ...
                ]
            }}
        """
        async for response in self._call_llm_with_template(articles_prompt, "article"):
            yield response

    async def get_citations_for_article(self, user_input: str, article: dict) -> AsyncGenerator[str, None]:
        citations_prompt = f"""
            You are an expert in the field of financial compliance and regulations with business context awareness. 
            Provide exact citation from {article["regulation"]} article "{article["article"]}" which are relevant for the following marketing text:
            ====================
            {user_input}
            ====================
            
            Important: This is marketing text that necessarily simplifies complex business operations. When determining relevance:
            - Consider the likely underlying business processes, not just the exact wording
            - Distinguish between citations that would require explicit statements in marketing vs. those addressed in operational documents
            
            - Do not include any other text outside the direct citations. Do not make up citations. 
            - Make your answer as complete as possible. If you miss any citations, the user may be subject to penalties.
            - Provide at least one citation per article. The best responses would have multiple relevant citations for every article.
            Provide your response as a valid-formatted JSON array of objects.
            {{
                "citations": [
                    {{
                        "regulation": "Regulation Name",
                        "article": "Article Name / Article Number",
                        "citation": "Citation from the article"
                    }},
                    ...
                ]
            }}
        """
        async for response in self._call_llm_with_template(citations_prompt, "citation"):
            yield response

descriptor = RegulationDescriptor()

@router.post("/analyze")
async def analyze(
    request: AnalysisRequest,
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    """
    Endpoint that streams the analysis results.
    """
    logger.info(f"Received analysis request with text length: {len(request.text)}")
    try:
        async def analyze_stream():
            try:
                # Get complete regulations response
                logger.info("Getting regulations")
                regulations_response = None
                async for chunk in descriptor.get_regulations(request.text):
                    data = json.loads(chunk)
                    yield f"data: {chunk}"
                    if data['type'] == 'regulation' and data.get('content'):
                        try:
                            regulations_response = json.loads(data['content'])
                            if not isinstance(regulations_response, dict) or 'regulations' not in regulations_response:
                                logger.error("Invalid regulations response format")
                                raise Exception("Invalid regulations response format")
                        except json.JSONDecodeError as e:
                            logger.error(f"Invalid JSON in regulations response: {str(e)}")
                            raise Exception("Invalid regulations response format")

                if not regulations_response or not regulations_response.get('regulations'):
                    logger.error("No valid regulations found in response")
                    yield f"data: {json.dumps({'type': 'error', 'content': 'No valid regulations found'})}\n\n"
                    return

                # Process all regulations in parallel to get articles
                logger.info(f"Processing {len(regulations_response.get('regulations', []))} regulations in parallel")
                regulations = regulations_response.get('regulations', [])
                
                async def process_regulation_articles(regulation):
                    articles_response = None
                    try:
                        # Create a list to store chunks
                        chunks = []
                        # Run the generator in a separate thread
                        async for chunk in descriptor.get_articles_for_regulations(request.text, regulation):
                            data = json.loads(chunk)
                            chunks.append(chunk)
                            if data['type'] == 'article':
                                articles_response = json.loads(data['content'])
                        # Return all chunks and the final response
                        return chunks, articles_response
                    except Exception as e:
                        logger.error(f"Error processing articles for regulation {regulation.get('regulation', 'Unknown')}: {str(e)}")
                        return [json.dumps({'type': 'error', 'content': f'Error processing articles: {str(e)}'})], None
                
                # Gather all article results
                article_tasks = [process_regulation_articles(reg) for reg in regulations]
                article_results = []
                
                try:
                    # Wait for all tasks to complete
                    results = await asyncio.gather(*article_tasks)
                    for chunks, articles in results:
                        # Yield all chunks
                        for chunk in chunks:
                            yield f"data: {chunk}"
                        if articles:
                            article_results.extend(articles.get('articles', []))
                except Exception as e:
                    logger.error(f"Error in article processing: {str(e)}")

                # Process all articles in parallel to get citations
                logger.info(f"Processing {len(article_results)} articles in parallel")
                
                async def process_article_citations(article):
                    citations_response = None
                    try:
                        # Create a list to store chunks
                        chunks = []
                        # Run the generator in a separate thread
                        async for chunk in descriptor.get_citations_for_article(request.text, article):
                            data = json.loads(chunk)
                            chunks.append(chunk)
                            if data['type'] == 'citation':
                                citations_response = json.loads(data['content'])
                        # Return all chunks and the final response
                        return chunks, citations_response
                    except Exception as e:
                        logger.error(f"Error processing citations for article {article.get('article', 'Unknown')}: {str(e)}")
                        return [json.dumps({'type': 'error', 'content': f'Error processing citations: {str(e)}'})], None
                
                # Gather all citation results
                citation_tasks = [process_article_citations(art) for art in article_results]
                citation_results = []
                
                try:
                    # Wait for all tasks to complete
                    results = await asyncio.gather(*citation_tasks)
                    for chunks, citations in results:
                        # Yield all chunks
                        for chunk in chunks:
                            yield f"data: {chunk}"
                        if citations:
                            citation_results.extend(citations.get('citations', []))
                except Exception as e:
                    logger.error(f"Error in citation processing: {str(e)}")

                # Generate summary of all findings
                if article_results or citation_results:  # Only generate summary if we have results
                    logger.info("Generating summary of analysis")
                    async for chunk in descriptor.get_summary(
                        request.text,
                        regulations_response,
                        article_results,
                        citation_results
                    ):
                        yield f"data: {chunk}"
                else:
                    logger.warning("No articles or citations found, skipping summary generation")

            except Exception as e:
                logger.error(f"Error in analyze_stream: {str(e)}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'content': f'Analysis error: {str(e)}'})}\n\n"

        logger.info("Returning StreamingResponse")
        return StreamingResponse(
            analyze_stream(),
            media_type="text/event-stream"
        )
    except Exception as e:
        logger.error(f"Error in analyze endpoint: {str(e)}", exc_info=True)
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting server on http://0.0.0.0:8000")
    uvicorn.run(router, host="0.0.0.0", port=8000)
