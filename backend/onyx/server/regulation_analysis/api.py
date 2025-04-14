import asyncio
import json
import time
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
        pass

    async def _call_llm_with_template(self, prompt: str, response_type: str) -> AsyncGenerator[str, None]:
        """
        Template method for making LLM API calls with standardized error handling and response formatting.
        """
        start_time = time.time()
        logger.info(f"Starting LLM call for {response_type}")
        try:
            llm, _ = get_default_llms()

            logger.info(f"Sending request to LLM for {response_type} with prompt length: {len(prompt)}")
            
            # Run the synchronous generator in a separate thread and collect content
            try:
                chunks = await asyncio.to_thread(lambda: [chunk.content for chunk in llm.stream(
                    prompt,
                    structured_response_format={"type": "json_object"}
                ) if chunk.content])
                
                logger.info(f"Received {len(chunks)} chunks from LLM for {response_type}")
            except Exception as e:
                logger.error(f"Error during LLM streaming for {response_type}: {str(e)}", exc_info=True)
                yield f"{json.dumps({'type': 'error', 'content': f'Error during LLM streaming: {str(e)}'})}\n\n"
                return
            
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
                logger.error(f"Raw content: {content[:500]}...")  # Log first 500 chars of invalid content
                yield f"{json.dumps({'type': 'error', 'content': f'Invalid response format for {response_type}'})}\n\n"
                return
                
            elapsed_time = time.time() - start_time
            logger.info(f"Successfully completed {response_type} response in {elapsed_time:.2f} seconds")
            yield f"{json.dumps({'type': response_type, 'content': content})}\n\n"
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"Error in {response_type} analysis after {elapsed_time:.2f} seconds: {str(e)}", exc_info=True)
            yield f"{json.dumps({'type': 'error', 'content': f'Error getting {response_type}: {str(e)}'})}\n\n"

    async def get_summary(self, user_input: str, regulations_data: dict, articles_data: list, citations_data: list) -> AsyncGenerator[str, None]:
        """
        Generates a summary of all regulations, articles, and citations with improved nuance.
        """
        summary_prompt = f"""
            You are a compliance and regulations officer working in a fintech company.
            Part of your role is to provide feedback on marketing materials to ensure they are compliant with the regulations that apply to marketing
            and not misleading to consumers. 

            Original Text:
            ====================
            {user_input}
            ====================

            Regulations you would consider:
            {json.dumps(regulations_data, indent=2)}

            Articles for those regulations you would consider:
            {json.dumps(articles_data, indent=2)}

            Citations for those regulations you would consider:
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
            You are a compliance and regulations officer working in a fintech company.
            Part of your role is to provide feedback on marketing materials to ensure they are compliant with the regulations that apply to marketing
            and not misleading to consumers. 

            For the following text, please identify all regulations that you would consider when providing feedback on the marketing text.
            
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
            You are a compliance and regulations officer working in a fintech company.
            Part of your role is to provide feedback on marketing materials to ensure they are compliant with the regulations that apply to marketing
            and not misleading to consumers. 

            For the following text, please identify all articles from the regulation "{regulation['regulation']}" that you would consider when providing feedback on the marketing text.
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
            You are a compliance and regulations officer working in a fintech company.
            Part of your role is to provide feedback on marketing materials to ensure they are compliant with the regulations that apply to marketing
            and not misleading to consumers. 

            For the following text, please identify all citations from "{article['regulation']}: {article['article']}" that you would consider when providing feedback on the marketing text.
            You are provided with a document context that may be related to the regulation and article.
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
        articles_data: list,
        user: User | None,
        db_session: Session,
        limit: int = 1
    ) -> AsyncGenerator[str, None]:
        """
        Search for documents related to the regulation and article pairs.
        
        Args:
            regulations_data: Dictionary containing regulation information
            articles_data: List of article information
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
                    art for art in articles_data
                    if art.get('regulation') == reg_name
                ]
                
                for article in matching_articles:
                    art_name = article.get('article')
                    if not art_name:
                        continue
                        
                    # Construct search query combining regulation and article info
                    search_query = f"{reg_name} {art_name}"
                    
                    # Set up filters
                    filters = IndexFilters(
                        access_control_list=user_acl_filters,
                    )
                    
                    # Perform document search
                    matching_chunks = document_index.admin_retrieval(
                        query=search_query,
                        filters=filters,
                        num_to_retrieve=limit * 3  # Retrieve more docs since we'll filter some out
                    )
                    
                    # Convert chunks to search docs
                    documents = chunks_or_sections_to_search_docs(matching_chunks)
                    
                    # Deduplicate documents and verify relevance
                    seen_docs = set()
                    unique_docs = []
                    for doc in documents:
                        if doc.document_id in seen_docs:
                            continue
                            
                        # Check if document title/identifier contains regulation or article reference
                        doc_identifier = (doc.semantic_identifier or "").lower()
                        doc_title = (doc.semantic_identifier or "").lower()
                        reg_name_lower = reg_name.lower()
                        art_name_lower = art_name.lower()
                        
                        # Basic relevance check - document should mention either regulation or article
                        is_relevant = (
                            reg_name_lower in doc_identifier or 
                            reg_name_lower in doc_title or
                            art_name_lower in doc_identifier or 
                            art_name_lower in doc_title
                        )
                        
                        if not is_relevant:
                            logger.debug(f"Skipping irrelevant document: {doc_identifier} for {reg_name} {art_name}")
                            continue
                            
                        unique_docs.append(doc)
                        seen_docs.add(doc.document_id)
                        
                        # Break if we have enough relevant documents
                        if len(unique_docs) >= limit:
                            break
                    
                    # Prepare response with additional context
                    for doc in unique_docs:
                        response = {
                            "type": "related_document",
                            "content": {
                                "regulation": reg_name,
                                "article": art_name,
                                "document": {
                                    **doc.model_dump(),
                                    "relevance_explanation": f"This document mentions {reg_name} {art_name} in its title/identifier",
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
    request_start_time = time.time()
    request_id = f"req_{int(request_start_time)}"  # Simple request ID for tracking
    logger.info(f"[{request_id}] Received analysis request with text length: {len(request.text)}")
    
    try:
        async def analyze_stream():
            try:
                regulations_response = None
                article_results = []  # This is a list of articles
                citation_results = []
                
                logger.info(f"[{request_id}] Starting regulations analysis")
                regulations_start_time = time.time()
                
                async for chunk in descriptor.get_regulations(request.text):
                    data = json.loads(chunk)
                    yield f"data: {chunk}"
                    if data['type'] == 'regulation' and data.get('content'):
                        try:
                            regulations_response = json.loads(data['content'])
                            if not isinstance(regulations_response, dict) or 'regulations' not in regulations_response:
                                logger.error(f"[{request_id}] Invalid regulations response format")
                                raise Exception("Invalid regulations response format")
                        except json.JSONDecodeError as e:
                            logger.error(f"[{request_id}] Invalid JSON in regulations response: {str(e)}")
                            raise Exception("Invalid regulations response format")

                regulations_time = time.time() - regulations_start_time
                logger.info(f"[{request_id}] Completed regulations analysis in {regulations_time:.2f} seconds")

                if not regulations_response or not regulations_response.get('regulations'):
                    logger.error(f"[{request_id}] No valid regulations found. Response: {regulations_response}")
                    yield f"data: {json.dumps({'type': 'error', 'content': 'No valid regulations found'})}\n\n"
                    return

                # Process all regulations in parallel to get articles
                num_regulations = len(regulations_response.get('regulations', []))
                logger.info(f"[{request_id}] Processing {num_regulations} regulations in parallel")
                articles_start_time = time.time()
                regulations = regulations_response.get('regulations', [])
                
                async def process_regulation_articles(regulation):
                    reg_start_time = time.time()
                    articles_response = None
                    try:
                        logger.info(f"[{request_id}] Processing articles for regulation: {regulation.get('regulation', 'Unknown')}")
                        chunks = []
                        async for chunk in descriptor.get_articles_for_regulations(request.text, regulation):
                            data = json.loads(chunk)
                            chunks.append(chunk)
                            if data['type'] == 'article':
                                articles_response = json.loads(data['content'])
                        reg_time = time.time() - reg_start_time
                        logger.info(f"[{request_id}] Completed articles for regulation {regulation.get('regulation', 'Unknown')} in {reg_time:.2f} seconds")
                        return chunks, articles_response
                    except Exception as e:
                        logger.error(f"[{request_id}] Error processing articles for regulation {regulation.get('regulation', 'Unknown')}: {str(e)}", exc_info=True)
                        return [json.dumps({'type': 'error', 'content': f'Error processing articles: {str(e)}'})], None
                
                try:
                    results = await asyncio.gather(*[process_regulation_articles(reg) for reg in regulations])
                    articles_time = time.time() - articles_start_time
                    logger.info(f"[{request_id}] Completed all article processing in {articles_time:.2f} seconds")
                    
                    for chunks, articles in results:
                        for chunk in chunks:
                            yield f"data: {chunk}"
                        if articles:
                            article_results.extend(articles.get('articles', []))
                except Exception as e:
                    logger.error(f"[{request_id}] Error in parallel article processing: {str(e)}", exc_info=True)

                # Search for related documents if we have regulations and articles
                if regulations_response and article_results:
                    logger.info(f"[{request_id}] Starting document search with {len(article_results)} articles")
                    docs_start_time = time.time()
                    related_docs_map = {}
                    try:
                        async for chunk in descriptor.find_related_documents(
                            regulations_response,
                            article_results,
                            _,
                            db_session
                        ):
                            yield chunk
                            try:
                                data = json.loads(chunk.replace("data: ", ""))
                                if data['type'] == 'related_document':
                                    reg = data['content']['regulation']
                                    art = data['content']['article']
                                    key = f"{reg}:{art}"
                                    if key not in related_docs_map:
                                        related_docs_map[key] = data['content']['document']
                                    logger.debug(
                                        f"[{request_id}] Found document for {reg} - {art}: "
                                        f"{data['content']['document'].get('semantic_identifier', 'Unknown')}"
                                    )
                            except json.JSONDecodeError as e:
                                logger.error(f"[{request_id}] Error parsing document chunk: {str(e)}")
                                continue
                        docs_time = time.time() - docs_start_time
                        logger.info(f"[{request_id}] Completed document search in {docs_time:.2f} seconds")
                    except Exception as e:
                        logger.error(f"[{request_id}] Error processing related documents: {str(e)}", exc_info=True)
                        yield f"data: {json.dumps({'type': 'error', 'content': f'Error processing related documents: {str(e)}'})}\n\n"

                # Process citations
                logger.info(f"[{request_id}] Starting citation processing for {len(article_results)} articles")
                citations_start_time = time.time()
                
                async def process_article_citations(article):
                    cite_start_time = time.time()
                    try:
                        key = f"{article['regulation']}:{article['article']}"
                        related_doc = related_docs_map.get(key)
                        chunks = []
                        article_citations = []
                        
                        logger.info(f"[{request_id}] Processing citations for {key}")
                        async for chunk in descriptor.get_citations_for_article(request.text, article, related_doc):
                            data = json.loads(chunk)
                            chunks.append(chunk)
                            if data['type'] == 'citation' and data.get('content'):
                                try:
                                    citations_content = json.loads(data['content']) if isinstance(data['content'], str) else data['content']
                                    if citations_content.get('citations'):
                                        article_citations.extend(citations_content.get('citations', []))
                                except json.JSONDecodeError as e:
                                    logger.error(f"[{request_id}] Invalid JSON in citation response: {str(e)}")
                        
                        cite_time = time.time() - cite_start_time
                        logger.info(f"[{request_id}] Completed citations for {key} in {cite_time:.2f} seconds")
                        return chunks, article_citations
                    except Exception as e:
                        logger.error(f"[{request_id}] Error processing citations for article {article.get('article', 'Unknown')}: {str(e)}", exc_info=True)
                        return [json.dumps({'type': 'error', 'content': f'Error processing citations: {str(e)}'})], []

                try:
                    results = await asyncio.gather(*[process_article_citations(article) for article in article_results])
                    citations_time = time.time() - citations_start_time
                    logger.info(f"[{request_id}] Completed all citation processing in {citations_time:.2f} seconds")
                    
                    for chunks, citations in results:
                        for chunk in chunks:
                            yield f"data: {chunk}"
                        citation_results.extend(citations)
                except Exception as e:
                    logger.error(f"[{request_id}] Error in parallel citation processing: {str(e)}", exc_info=True)
                    yield f"data: {json.dumps({'type': 'error', 'content': f'Error processing citations: {str(e)}'})}\n\n"

                # Generate summary
                logger.info(f"[{request_id}] Starting summary generation")
                summary_start_time = time.time()
                async for chunk in descriptor.get_summary(
                    request.text,
                    regulations_response,
                    {'articles': article_results},
                    citation_results
                ):
                    yield f"data: {chunk}"
                summary_time = time.time() - summary_start_time
                logger.info(f"[{request_id}] Completed summary generation in {summary_time:.2f} seconds")
                
                total_time = time.time() - request_start_time
                logger.info(f"[{request_id}] Completed full analysis in {total_time:.2f} seconds")
                
            except Exception as e:
                total_time = time.time() - request_start_time
                logger.error(f"[{request_id}] Error in analyze_stream after {total_time:.2f} seconds: {str(e)}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'content': f'Analysis error: {str(e)}'})}\n\n"

        logger.info(f"[{request_id}] Returning StreamingResponse")
        return StreamingResponse(
            analyze_stream(),
            media_type="text/event-stream"
        )
    except Exception as e:
        total_time = time.time() - request_start_time
        logger.error(f"[{request_id}] Error in analyze endpoint after {total_time:.2f} seconds: {str(e)}", exc_info=True)
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting server on http://0.0.0.0:8000")
    uvicorn.run(router, host="0.0.0.0", port=8000)
