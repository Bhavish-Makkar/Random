
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import redis
import json
import os
from typing import List, Dict

# For Azure OpenAI
# You'll need: pip install openai
try:
    from openai import AzureOpenAI
except ImportError:
    print("⚠️  openai package not installed. Run: pip install openai")
    AzureOpenAI = None

# ========== Configuration ==========

# Redis Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

# Session TTL (24 hours)
SESSION_TTL = 24 * 3600

# ========== Initialize Redis Client ==========

try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_timeout=5
    )
    # Test connection
    redis_client.ping()
    print(f"✅ Redis connected: {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    print(f"❌ Redis connection failed: {e}")
    print("💡 Make sure Redis is running. For local testing: docker run -d -p 6379:6379 redis")
    redis_client = None

# ========== Initialize Azure OpenAI Client ==========

azure_client = None
if AzureOpenAI and AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY:
    try:
        azure_client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION
        )
        print(f"✅ Azure OpenAI configured: {AZURE_OPENAI_DEPLOYMENT}")
    except Exception as e:
        print(f"❌ Azure OpenAI initialization failed: {e}")
else:
    print("⚠️  Azure OpenAI not configured (will use mock responses)")
    print("💡 Set environment variables: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_DEPLOYMENT")

# ========== FastAPI App ==========

app = FastAPI(title="Chatbot with Session Memory POC")

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== Pydantic Models ==========

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    reply: str
    session_id: str
    message_count: int

# ========== Helper Functions ==========

def get_session_key(session_id: str) -> str:
    """Generate Redis key for session history"""
    return f"session:{session_id}:history"

def get_session_history(session_id: str) -> List[Dict]:
    """Retrieve chat history from Redis"""
    if not redis_client:
        return []
    
    try:
        key = get_session_key(session_id)
        history_entries = redis_client.lrange(key, 0, -1)
        return [json.loads(entry) for entry in history_entries]
    except Exception as e:
        print(f"Error getting session history: {e}")
        return []

def save_message_to_history(session_id: str, role: str, content: str):
    """Save a message to Redis"""
    if not redis_client:
        return
    
    try:
        key = get_session_key(session_id)
        message = {"role": role, "content": content}
        redis_client.rpush(key, json.dumps(message))
        redis_client.expire(key, SESSION_TTL)
    except Exception as e:
        print(f"Error saving message: {e}")

async def call_azure_openai(messages: List[Dict]) -> str:
    """Call Azure OpenAI with conversation history"""
    if not azure_client:
        # Mock response for testing without Azure OpenAI
        return mock_openai_response(messages)
    
    try:
        response = azure_client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Azure OpenAI error: {e}")
        return f"Sorry, I encountered an error: {str(e)}"

def mock_openai_response(messages: List[Dict]) -> str:
    """Mock response for testing without Azure OpenAI"""
    last_msg = messages[-1]["content"].lower()
    
    # Check if user introduced themselves
    user_history = [m for m in messages if m["role"] == "user"]
    name = None
    for msg in user_history:
        if "my name is" in msg["content"].lower():
            parts = msg["content"].lower().split("my name is")
            if len(parts) > 1:
                name = parts[1].strip().split()[0].capitalize()
    
    # Memory-aware responses
    if "what" in last_msg and "name" in last_msg:
        if name:
            return f"Your name is {name}! I remember you told me earlier. 😊"
        else:
            return "I don't think you've told me your name yet. What is it?"
    
    if "my name is" in last_msg:
        parts = last_msg.split("my name is")
        if len(parts) > 1:
            name = parts[1].strip().split()[0].capitalize()
            return f"Nice to meet you, {name}! I'll remember that. 👋"
    
    # Context-aware responses
    if name and any(word in last_msg for word in ["hello", "hi", "hey"]):
        return f"Hello {name}! How can I help you today?"
    
    # Default responses
    responses = {
        "hello": "Hello! I'm a chatbot with session memory. Try telling me your name!",
        "hi": "Hi there! I can remember our conversation. What would you like to talk about?",
        "how are you": "I'm doing great! Thanks for asking. How about you?",
        "help": "I can remember our conversation within this session. Try:\n1. Tell me 'My name is [your name]'\n2. Then ask 'What's my name?'\n3. I'll remember it!",
    }
    
    for key, response in responses.items():
        if key in last_msg:
            return response
    
    return "I understand you said: '" + messages[-1]["content"] + "'. I'm a POC chatbot - configure Azure OpenAI for better responses! 🤖"

# ========== API Endpoints ==========

@app.get("/")
def read_root():
    """Health check endpoint"""
    return {
        "status": "running",
        "redis": "connected" if redis_client else "disconnected",
        "azure_openai": "configured" if azure_client else "mock_mode",
        "message": "FastAPI backend is ready!"
    }

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint with session memory"""
    
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis is not available")
    
    # Get existing conversation history
    history = get_session_history(request.session_id)
    
    # Add system message if first message
    if not history:
        system_msg = {
            "role": "system",
            "content": "You are a helpful AI assistant with memory. Remember details the user shares with you."
        }
        history = [system_msg]
    
    # Add current user message
    history.append({"role": "user", "content": request.message})
    
    # Trim history if too long (keep last 20 messages + system)
    if len(history) > 21:
        history = [history[0]] + history[-20:]
    
    # Get AI response
    bot_response = await call_azure_openai(history)
    
    # Save user message and bot response to Redis
    save_message_to_history(request.session_id, "user", request.message)
    save_message_to_history(request.session_id, "assistant", bot_response)
    
    # Return response
    return ChatResponse(
        reply=bot_response,
        session_id=request.session_id,
        message_count=len(history)
    )

@app.get("/session/{session_id}/history")
def get_history(session_id: str):
    """Get full session history"""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis is not available")
    
    history = get_session_history(session_id)
    return {
        "session_id": session_id,
        "messages": history,
        "count": len(history)
    }

@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    """Delete a session"""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis is not available")
    
    try:
        key = get_session_key(session_id)
        redis_client.delete(key)
        return {"message": "Session deleted", "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== Run with: uvicorn backend:app --reload ==========

if __name__ == "__main__":
    import uvicorn
    print("\n🚀 Starting FastAPI server...")
    print("📝 Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)