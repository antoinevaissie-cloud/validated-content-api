# Load environment variables from .env file (for local development only)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not available (like on Vercel), environment variables are already loaded
    pass

# api/main.py - Complete file

# Import the packages we need
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import openai
import os
from supabase import create_client, Client
from datetime import datetime

# Create our FastAPI app
app = FastAPI(title="Validated Content API", version="1.0.0")

# Allow ChatGPT to call our API (CORS = Cross-Origin Resource Sharing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chatgpt.com", "https://chat.openai.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect to our services using the keys from .env
openai.api_key = os.getenv("OPENAI_API_KEY")
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# Define what data our API expects to receive
# These are like "templates" that validate incoming requests

class SearchRequest(BaseModel):
    query: str                              # The search text (required)
    topics: Optional[List[str]] = None      # Filter by topics (optional)
    source: Optional[str] = None            # Filter by source (optional)
    validated_only: bool = True             # Only show validated content
    limit: int = 5                          # How many results to return

class AddContentRequest(BaseModel):
    title: str                              # Title (required)
    excerpt: Optional[str] = None           # Short summary (optional)
    full_text: Optional[str] = None         # Full content (optional)
    topics: List[str]                       # Topics array (required)
    source: Optional[str] = None            # Where it came from (optional)
    url: Optional[str] = None               # Related URL (optional)
    validated: bool = True                  # Is it validated?

# Helper functions
def generate_embedding(text: str) -> List[float]:
    """Convert text into numbers that represent its meaning"""
    try:
        response = openai.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

def format_content_result(row: dict) -> dict:
    """Clean up database results for the API response"""
    return {
        "id": row["id"],
        "title": row["title"], 
        "excerpt": row.get("excerpt"),
        "full_text": row.get("full_text"),
        "topics": row.get("topics", []),
        "source": row.get("source"),
        "url": row.get("url"),
        "date": row.get("date"),
        "validated": row.get("validated", False)
    }

# API Endpoints
@app.post("/search")
def search_content(request: SearchRequest):
    """Search for content in your database"""
    try:
        # Step 1: Convert the search query to numbers (embedding)
        query_embedding = generate_embedding(request.query)
        
        # Step 2: Search the database for similar content
        query = supabase.rpc('match_content', {
            'query_embedding': query_embedding,
            'match_threshold': 0.1,  # How similar results need to be
            'match_count': request.limit
        })
        
        # Step 3: Apply filters if requested
        if request.validated_only:
            query = query.eq('validated', True)
        
        if request.source:
            query = query.eq('source', request.source)
            
        if request.topics:
            query = query.overlaps('topics', request.topics)
        
        # Step 4: Execute the search
        result = query.execute()
        
        # Step 5: Format the results nicely
        formatted_results = []
        for row in result.data:
            item = format_content_result(row)
            item['similarity_score'] = row.get('similarity', 0)
            formatted_results.append(item)
        
        # Step 6: Return the results
        return {
            "results": formatted_results,
            "total_count": len(formatted_results),
            "query_used": request.query
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
@app.post("/add")
def add_content(request: AddContentRequest):
    """Add new content with embedding generation"""
    try:
        # Prepare text for embedding (use full_text if available, otherwise title + excerpt)
        embedding_text = request.full_text or f"{request.title}\n{request.excerpt or ''}"
        
        # Generate embedding
        embedding = generate_embedding(embedding_text.strip())
        
        # Insert new content
        insert_data = {
            "title": request.title,
            "excerpt": request.excerpt,
            "full_text": request.full_text,
            "topics": request.topics,
            "source": request.source,
            "url": request.url,
            "validated": request.validated,
            "embedding": embedding,
            "date": datetime.utcnow().isoformat()
        }
        
        result = supabase.table('validated_content').insert(insert_data).execute()
        
        return {
            "id": result.data[0]["id"],
            "message": "Content added successfully",
            "title": request.title
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Add content failed: {str(e)}")
@app.get("/")
def root():
    """Simple test to see if the API is working"""
    return {"message": "Validated Content API is running!", "status": "healthy"}
@app.delete("/delete/{content_id}")
def delete_content(content_id: str):
    """Delete content by ID"""
    try:
        result = supabase.table('validated_content').delete().eq('id', content_id).execute()
        
        if len(result.data) == 0:
            raise HTTPException(status_code=404, detail="Content not found")
        
        return {
            "message": "Content deleted successfully",
            "deleted_id": content_id
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

@app.get("/all")
def get_all_content():
    """Get all content without similarity filtering"""
    try:
        result = supabase.table('validated_content').select('*').order('date', desc=True).execute()
        
        formatted_results = []
        for row in result.data:
            formatted_results.append(format_content_result(row))
        
        return {
            "results": formatted_results,
            "total_count": len(formatted_results)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get all failed: {str(e)}")

# Export the FastAPI app directly
# Vercel will handle it natively
