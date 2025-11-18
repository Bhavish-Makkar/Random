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
  const messagesEndRef = useRef(null);

  // Generate initial session ID on mount
  useEffect(() => {
    createNewSession();
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const createNewSession = () => {
    const newSessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    setSessionId(newSessionId);
    setMessages([]);
    setMessageCount(0);
    console.log('✅ New session created:', newSessionId);
    console.log('📍 Redis key will be: nonprod:occuweather_hub:weather_mcp:mockchat:' + newSessionId);
  };

  const sendMessage = async () => {
    if (!input.trim()) return;

    const userMessage = input.trim();
    setInput('');
    
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

  return (
    <div className="App">
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