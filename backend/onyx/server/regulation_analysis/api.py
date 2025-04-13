import asyncio
import json
from typing import AsyncGenerator
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.auth.users import User
from onyx.db.engine import get_session
from onyx.utils.logger import setup_logger
from onyx.llm.factory import get_default_llms
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.context.search.models import IndexFilters
from onyx.context.search.utils import chunks_or_sections_to_search_docs
from onyx.context.search.preprocessing.access_filters import build_access_filters_for_user

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
            
            Provide your response as a JSON array of objects. Each
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

    async def get_citations_for_article(self, user_input: str, article: dict, related_doc: dict | None = None) -> AsyncGenerator[str, None]:
        # Build document context if available
        document_context = ""
        if related_doc:
            document_context = f"""
            The following document is related to this article and should be used as a reference:
            ====================
            Title: {related_doc.get('semantic_identifier') or related_doc.get('document_id')}
            Content: {related_doc.get('blurb', '')}
            ====================
            """

        citations_prompt = f"""
            You are an expert in the field of financial compliance and regulations with business context awareness. 
            Provide exact citations from the provided document context for {article["regulation"]} article "{article["article"]}" which are relevant to the following text:
            ====================

            {user_input}
            ====================
            Here is the document context:
            {document_context}
            
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

    async def find_related_documents(
        self,
        regulations_data: dict,
        articles_data: dict,
        user: User | None,
        db_session: Session,
        limit: int = 1
    ) -> AsyncGenerator[str, None]:
        """
        Search for documents related to the regulation and article pairs.
        
        Args:
            regulations_data: Dictionary containing regulation information
            articles_data: Dictionary containing article information
            user: Current user for access control
            db_session: Database session
            limit: Maximum number of documents to return per regulation-article pair
            
        Yields:
            JSON strings containing related documents for each regulation-article pair
        """
        try:
            logger.info("Searching for related documents")
            
            # Get search settings and document index
            search_settings = get_current_search_settings(db_session)
            document_index = get_default_document_index(search_settings, None)
            
            # Build user access filters
            user_acl_filters = build_access_filters_for_user(user, db_session)
            
            # Process each regulation and its articles
            for regulation in regulations_data.get('regulations', []):
                reg_name = regulation.get('regulation')
                if not reg_name:
                    continue
                
                # Find matching articles for this regulation
                matching_articles = [
                    art for art in articles_data['articles']
                    if art.get('regulation') == reg_name
                ]
                
                for article in matching_articles:
                    art_name = article.get('article')
                    if not art_name:
                        continue
                        
                    # Construct search query combining regulation and article info
                    search_query = f"{reg_name} {art_name} {article.get('description', '')}"
                    
                    # Set up filters
                    filters = IndexFilters(
                        access_control_list=user_acl_filters,
                    )
                    
                    # Perform document search
                    matching_chunks = document_index.admin_retrieval(
                        query=search_query,
                        filters=filters,
                        num_to_retrieve=limit
                    )
                    
                    # Convert chunks to search docs
                    documents = chunks_or_sections_to_search_docs(matching_chunks)
                    
                    # Deduplicate documents
                    seen_docs = set()
                    unique_docs = []
                    for doc in documents:
                        if doc.document_id not in seen_docs:
                            unique_docs.append(doc)
                            seen_docs.add(doc.document_id)
                    
                    # Prepare response with additional context
                    for doc in unique_docs:
                        response = {
                            "type": "related_document",  # Changed to singular for individual document streaming
                            "content": {
                                "regulation": reg_name,
                                "article": art_name,
                                "document": {
                                    **doc.model_dump(),
                                    "relevance_explanation": f"This document is related to {reg_name} {art_name}",
                                    "is_relevant": True,
                                    "score": doc.score or 1.0,
                                    "match_highlights": doc.match_highlights or [doc.blurb] if doc.blurb else [],
                                }
                            }
                        }
                        yield f"data: {json.dumps(response)}\n\n"
                    
        except Exception as e:
            logger.error(f"Error finding related documents: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': f'Error finding related documents: {str(e)}'})}\n\n"

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
                regulations_response = None
                article_results = []
                citation_results = []
                
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

                # Dummy regulations response
                # regulations_response = {
                #     "regulations": [
                #         {
                #             "regulation": "GDPR",
                #             "description": "General Data Protection Regulation"
                #         },
                #         {
                #             "regulation": "CCPA",
                #             "description": "California Consumer Privacy Act"
                #         }
                #     ]
                # }

                # # Stream regulations response
                # yield f"data: {json.dumps({'type': 'regulation', 'content': json.dumps(regulations_response)})}\n\n"

                # # Dummy article results
                # article_results = {
                #     'articles': [
                #         {
                #             "regulation": "GDPR",
                #             "article": "Article 5",
                #             "description": "Principles relating to processing of personal data"
                #         },
                #         {
                #             "regulation": "CCPA",
                #             "article": "Section 1798.100",
                #             "description": "Consumer rights regarding personal information"
                #         }
                #     ]
                # }

                # # Stream article results
                # yield f"data: {json.dumps({'type': 'article', 'content': json.dumps(article_results)})}\n\n"

                # Search for related documents if we have regulations and articles
                if regulations_response and article_results:
                    logger.info("Searching for related documents")
                    # Store related documents by regulation and article
                    related_docs_map = {}
                    try:
                        async for chunk in descriptor.find_related_documents(
                            regulations_response,
                            article_results,
                            _,  # Current user
                            db_session
                        ):
                            # Log and stream the document results
                            try:
                                # The chunk already includes "data: " prefix
                                yield chunk
                                
                                # Parse and log the data (remove "data: " prefix first)
                                data = json.loads(chunk.replace("data: ", ""))
                                if data['type'] == 'related_document':
                                    # Store the document for later use
                                    reg = data['content']['regulation']
                                    art = data['content']['article']
                                    key = f"{reg}:{art}"
                                    if key not in related_docs_map:
                                        related_docs_map[key] = data['content']['document']
                                    
                                    logger.info(
                                        f"Found related document for {reg} - "
                                        f"{art}: "
                                        f"{data['content']['document'].get('semantic_identifier', 'Unknown')} "
                                        f"(ID: {data['content']['document'].get('document_id', 'Unknown')})"
                                    )
                            except json.JSONDecodeError as e:
                                logger.error(f"Error parsing document chunk: {str(e)}")
                                continue
                    except Exception as e:
                        logger.error(f"Error processing related documents: {str(e)}")
                        yield f"data: {json.dumps({'type': 'error', 'content': f'Error processing related documents: {str(e)}'})}\n\n"

                # Process articles one at a time to get citations
                logger.info(f"Processing {len(article_results)} articles for citations")
                for article in article_results['articles']:
                    try:
                        # Get related document for this article if available
                        key = f"{article['regulation']}:{article['article']}"
                        related_doc = related_docs_map.get(key)
                        async for chunk in descriptor.get_citations_for_article(request.text, article, related_doc):
                            data = json.loads(chunk)
                            # Stream each citation chunk immediately
                            yield f"data: {chunk}"
                            if data['type'] == 'citation' and data.get('content'):
                                try:
                                    citations_content = json.loads(data['content']) if isinstance(data['content'], str) else data['content']
                                    if citations_content.get('citations'):
                                        citation_results.extend(citations_content.get('citations', []))
                                except json.JSONDecodeError as e:
                                    logger.error(f"Invalid JSON in citation response: {str(e)}")
                    except Exception as e:
                        logger.error(f"Error processing citations for article {article.get('article', 'Unknown')}: {str(e)}")

                # Generate summary of all findings
                # if article_results or citatiolklkj;lk;lkj;lkjkjhgkjhgkjhgcles or citations found, skipping summary generation")

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
