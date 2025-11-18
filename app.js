import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = 'http://localhost:8000';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState('');
  const [messageCount, setMessageCount] = useState(0);
  const [sessions, setSessions] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef(null);

  // Load sessions from localStorage on mount
  useEffect(() => {
    const savedSessions = localStorage.getItem('chat_sessions');
    if (savedSessions) {
      setSessions(JSON.parse(savedSessions));
    }
    createNewSession();
  }, []);

  // Save sessions to localStorage whenever it changes
  useEffect(() => {
    if (sessions.length > 0) {
      localStorage.setItem('chat_sessions', JSON.stringify(sessions));
    }
  }, [sessions]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const createNewSession = () => {
    const newSessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const newSession = {
      id: newSessionId,
      title: 'New Chat',
      timestamp: new Date().toISOString(),
      messageCount: 0
    };
    
    setSessionId(newSessionId);
    setMessages([]);
    setMessageCount(0);
    setSessions(prev => [newSession, ...prev]);
    
    console.log('✅ New session created:', newSessionId);
    console.log('📍 Redis key: nonprod:occuweather_hub:weather_mcp:mockchat:' + newSessionId);
  };

  const loadSession = async (session) => {
    try {
      // Load history from backend
      const response = await axios.get(`${API_URL}/session/${session.id}/history`);
      
      setSessionId(session.id);
      setMessages(response.data.messages.filter(msg => msg.role !== 'system'));
      setMessageCount(response.data.count);
      
      console.log('📂 Loaded session:', session.id);
    } catch (error) {
      console.error('❌ Error loading session:', error);
      // If session not found in Redis, still switch to it
      setSessionId(session.id);
      setMessages([]);
      setMessageCount(0);
    }
  };

  const updateSessionTitle = (sessionId, firstMessage) => {
    setSessions(prev => prev.map(s => 
      s.id === sessionId && s.title === 'New Chat'
        ? { ...s, title: firstMessage.slice(0, 30) + (firstMessage.length > 30 ? '...' : '') }
        : s
    ));
  };

  const deleteSession = async (sessionId, e) => {
    e.stopPropagation();
    
    try {
      await axios.delete(`${API_URL}/session/${sessionId}`);
      setSessions(prev => prev.filter(s => s.id !== sessionId));
      
      // If deleting current session, create new one
      if (sessionId === sessionId) {
        createNewSession();
      }
      
      console.log('🗑️ Session deleted:', sessionId);
    } catch (error) {
      console.error('❌ Error deleting session:', error);
    }
  };

  const sendMessage = async () => {
    if (!input.trim()) return;

    const userMessage = input.trim();
    setInput('');
    
    // Update session title with first message
    if (messageCount === 0) {
      updateSessionTitle(sessionId, userMessage);
    }
    
    // Add user message to UI
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setLoading(true);

    try {
      const response = await axios.post(`${API_URL}/chat`, {
        session_id: sessionId,
        message: userMessage
      });

      // Add bot response to UI
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: response.data.reply 
      }]);
      setMessageCount(response.data.message_count);
      
      // Update session message count
      setSessions(prev => prev.map(s => 
        s.id === sessionId ? { ...s, messageCount: response.data.message_count } : s
      ));

    } catch (error) {
      console.error('❌ Error:', error);
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: '❌ Connection failed! Make sure FastAPI backend is running on http://localhost:8000'
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const formatTimestamp = (timestamp) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffInHours = (now - date) / (1000 * 60 * 60);
    
    if (diffInHours < 24) {
      return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    } else if (diffInHours < 48) {
      return 'Yesterday';
    } else {
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }
  };

  return (
    <div className="App">
      {/* Sidebar */}
      <div className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
        <div className="sidebar-header">
          <h3>💬 Chat History</h3>
          <button className="new-chat-sidebar-btn" onClick={createNewSession}>
            + New
          </button>
        </div>
        
        <div className="sessions-list">
          {sessions.map((session) => (
            <div
              key={session.id}
              className={`session-item ${session.id === sessionId ? 'active' : ''}`}
              onClick={() => loadSession(session)}
            >
              <div className="session-content">
                <div className="session-title">{session.title}</div>
                <div className="session-meta">
                  {formatTimestamp(session.timestamp)} • {session.messageCount} msgs
                </div>
              </div>
              <button 
                className="delete-session-btn"
                onClick={(e) => deleteSession(session.id, e)}
                title="Delete session"
              >
                🗑️
              </button>
            </div>
          ))}
          
          {sessions.length === 0 && (
            <div className="empty-sessions">
              <p>No chat history yet</p>
              <p>Start a new conversation!</p>
            </div>
          )}
        </div>
      </div>

      {/* Toggle Sidebar Button */}
      <button 
        className="toggle-sidebar-btn" 
        onClick={() => setSidebarOpen(!sidebarOpen)}
      >
        {sidebarOpen ? '◀' : '▶'}
      </button>

      {/* Main Chat Area */}
      <div className="chat-container">
        <div className="chat-header">
          <div>
            <h2>🤖 Chatbot POC</h2>
            <div className="session-info">
              Session: {sessionId.slice(-8)} | Messages: {messageCount}
            </div>
          </div>
          <button className="new-chat-btn" onClick={createNewSession}>
            + New Chat
          </button>
        </div>

        <div className="messages-container">
          {messages.length === 0 && (
            <div className="welcome-message">
              <h3>👋 Welcome!</h3>
              <p>Start a conversation...</p>
              <p className="tip">Try: "My name is Rahul" then "What's my name?"</p>
            </div>
          )}
          
          {messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role === 'user' ? 'user' : 'bot'}`}>
              <div className="message-bubble">
                {msg.content}
              </div>
            </div>
          ))}

          {loading && (
            <div className="message bot">
              <div className="message-bubble">
                <div className="typing-indicator">
                  <div className="typing-dot"></div>
                  <div className="typing-dot"></div>
                  <div className="typing-dot"></div>
                </div>
              </div>
            </div>
          )}
          
          <div ref={messagesEndRef} />
        </div>

        <div className="input-container">
          <input
            type="text"
            className="message-input"
            placeholder="Type your message..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            disabled={loading || !sessionId}
          />
          <button 
            className="send-btn" 
            onClick={sendMessage}
            disabled={loading || !input.trim() || !sessionId}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;