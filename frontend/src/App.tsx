import { useState, useRef, useEffect } from 'react';
import { Send, User, Bot, AlertTriangle, Check, X, Building, ShieldCheck, Database, FileUp, Ticket, Package } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';
import './index.css';

// Use environment variable for API URL in production, fallback to localhost for development
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  requires_confirmation?: boolean;
  tool_call?: any;
};

function App() {
  const [messages, setMessages] = useState<Message[]>([
    { id: '1', role: 'assistant', content: 'Hello! I am the ParcelPilot AI Assistant. How can I help you today?' }
  ]);
  const [input, setInput] = useState('');
  const [persona, setPersona] = useState<'customer' | 'internal'>('customer');
  const [accountId, setAccountId] = useState('ACCT-001'); 
  const [threadId] = useState(() => Math.random().toString(36).substring(7));
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [isStartup, setIsStartup] = useState(true);
  const [authStep, setAuthStep] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');

  // Internal Tabs
  const [internalTab, setInternalTab] = useState<'chat' | 'orders' | 'tickets'>('chat');
  const [ticketsList, setTicketsList] = useState<any[]>([]);
  const [selectedTicket, setSelectedTicket] = useState<any | null>(null);
  const [closeReason, setCloseReason] = useState('');
  const [closerName, setCloserName] = useState('');

  // Single Order Form State
  const [singleOrder, setSingleOrder] = useState({
    account_id: 'ACCT-001',
    carrier: 'SwiftShip',
    shipment_fee_inr: 0
  });
  const [newAccountName, setNewAccountName] = useState('');
  const [customCarrier, setCustomCarrier] = useState('');
  
  const [startDateTime, setStartDateTime] = useState<Date | null>(new Date());
  const [endDateTime, setEndDateTime] = useState<Date | null>(new Date());
  const [ordersList, setOrdersList] = useState<any[]>([]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, internalTab]);

  const fetchTickets = () => {
    fetch(`${API_BASE_URL}/api/tickets`)
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setTicketsList(data);
        } else {
          console.error("Unexpected tickets response:", data);
          setTicketsList([]);
        }
      })
      .catch(err => console.error("Error fetching tickets:", err));
  };

  const fetchOrders = () => {
    fetch(`${API_BASE_URL}/api/orders`)
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setOrdersList(data);
        } else {
          console.error("Unexpected orders response:", data);
          setOrdersList([]);
        }
      })
      .catch(err => console.error("Error fetching orders:", err));
  };

  useEffect(() => {
    if (internalTab === 'tickets') {
      fetchTickets();
    } else if (internalTab === 'orders') {
      fetchOrders();
    }
  }, [internalTab]);

  const handleCloseTicket = async () => {
    if (!closeReason.trim() || !selectedTicket || !closerName.trim()) return;
    try {
      const res = await fetch(`${API_BASE_URL}/api/tickets/${selectedTicket.ticket_id}/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolution: `Closed by ${closerName.trim()}: ${closeReason.trim()}` })
      });
      if (res.ok) {
        fetchTickets();
        setSelectedTicket(null);
        setCloseReason('');
        setCloserName('');
      } else {
        alert("Failed to close ticket.");
      }
    } catch (e) {
      console.error(e);
      alert("Error closing ticket.");
    }
  };

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMessage: Message = { id: Date.now().toString(), role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMessage.content,
          persona,
          account_id: persona === 'customer' ? accountId : undefined,
          thread_id: threadId
        })
      });

      if (!res.body) throw new Error("ReadableStream not yet supported in this browser.");
      
      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      
      let assistantMsgId = Date.now().toString();
      setMessages(prev => [...prev, {
        id: assistantMsgId,
        role: 'assistant',
        content: '',
        requires_confirmation: false
      }]);
      
      let done = false;
      let streamedContent = '';
      let buffer = '';
      
      setIsLoading(false); // We can hide loading spinner once stream starts
      
      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          buffer += decoder.decode(value, { stream: true });
          
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const dataStr = line.substring(6);
              try {
                const data = JSON.parse(dataStr);
                
                if (data.type === 'token') {
                  streamedContent += data.content;
                  setMessages(prev => prev.map(m => 
                    m.id === assistantMsgId ? { ...m, content: streamedContent } : m
                  ));
                } else if (data.type === 'confirmation') {
                  setMessages(prev => prev.map(m => 
                    m.id === assistantMsgId ? { 
                      ...m, 
                      content: streamedContent + (data.message || ''),
                      requires_confirmation: true, 
                      tool_call: data.tool_call 
                    } : m
                  ));
                }
              } catch (e) {
                // Ignore incomplete JSON chunks
              }
            }
          }
        }
      }
    } catch (error) {
      console.error(error);
      setMessages(prev => [...prev, { id: Date.now().toString(), role: 'assistant', content: 'An error occurred while connecting to the server.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleConfirm = async (confirm: boolean, msgId: string) => {
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          thread_id: threadId,
          confirm
        })
      });
      
      setMessages(prev => {
        const newMsgs = prev.map(m => m.id === msgId ? { ...m, requires_confirmation: false, content: m.content + (confirm ? "\n\n**Action Confirmed.**" : "\n\n**Action Cancelled.**") } : m);
        return newMsgs;
      });

      if (!res.body) throw new Error("Stream not supported.");
      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      
      let newMsgId = Date.now().toString();
      setMessages(prev => [...prev, {
        id: newMsgId,
        role: 'assistant',
        content: ''
      }]);
      
      let done = false;
      let streamedContent = '';
      let buffer = '';
      
      setIsLoading(false);
      
      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          buffer += decoder.decode(value, { stream: true });
          
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const dataStr = line.substring(6);
              try {
                const data = JSON.parse(dataStr);
                if (data.type === 'token') {
                  streamedContent += data.content;
                  setMessages(prev => prev.map(m => 
                    m.id === newMsgId ? { ...m, content: streamedContent } : m
                  ));
                } else if (data.type === 'confirmation') {
                  setMessages(prev => prev.map(m => 
                    m.id === newMsgId ? { 
                      ...m, 
                      content: streamedContent + (data.message || ''),
                      requires_confirmation: true, 
                      tool_call: data.tool_call 
                    } : m
                  ));
                }
              } catch (e) {}
            }
          }
        }
      }
    } catch (error) {
      console.error(error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (username === 'admin' && password === 'password') {
      setPersona('internal');
      setInternalTab('chat');
      setMessages([{ id: '1', role: 'assistant', content: 'Internal Support AI initialized. Ready to analyze tickets, investigate trends, or perform actions.' }]);
      setIsStartup(false);
      setAuthStep(false);
    } else {
      setAuthError('Invalid credentials. Use admin/password');
    }
  };

  const submitSingleOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    
    const pad = (n: number) => n.toString().padStart(2, '0');
    const formatISO = (d: Date | null) => d ? `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00` : '';

    try {
      const payload: any = { 
        ...singleOrder, 
        status: 'BOOKED',
        pickup_window_start: formatISO(startDateTime),
        pickup_window_end: formatISO(endDateTime)
      };
      
      if (singleOrder.account_id === 'NEW') {
        payload.account_id = `ACCT-${Math.floor(Math.random() * 9000) + 1000}`;
        payload.new_account_name = newAccountName;
      }
      
      if (singleOrder.carrier === 'OTHER') {
        payload.carrier = customCarrier;
      }
      
      const res = await fetch(`${API_BASE_URL}/api/orders/single`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      alert(data.message || 'Order created!');
      fetchOrders();
    } catch (err) {
      alert('Error creating order.');
    }
  };

  const handleCsvUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (event) => {
      const text = event.target?.result as string;
      const lines = text.split('\n').map(l => l.trim()).filter(l => l);
      if (lines.length < 2) return alert("Invalid CSV format.");

      const headers = lines[0].split(',');
      const orders = lines.slice(1).map(line => {
        const values = line.split(',');
        const obj: any = {};
        headers.forEach((h, i) => {
          obj[h.trim()] = h.trim() === 'shipment_fee_inr' ? Number(values[i]) : values[i];
        });
        obj.status = obj.status || 'BOOKED';
        return obj;
      });

      try {
        const res = await fetch(`${API_BASE_URL}/api/orders/bulk`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(orders)
        });
        const data = await res.json();
        alert(data.message || 'Orders created!');
        fetchOrders();
      } catch (err) {
        alert('Error creating bulk orders.');
      }
    };
    reader.readAsText(file);
  };

  if (isStartup) {
    return (
      <div className="startup-container">
        <div className="startup-box glass-panel">
          <div className="brand" style={{ justifyContent: 'center', marginBottom: '20px' }}>
            <Building className="icon" size={36} />
            <h1>ParcelPilot AI</h1>
          </div>
          
          {!authStep ? (
            <div className="startup-choices">
              <h2>Select Portal</h2>
              <button 
                className="startup-btn"
                onClick={() => {
                  setPersona('customer');
                  setMessages([{ id: '1', role: 'assistant', content: 'Hello! I am the customer-facing AI. How can I assist you with your shipments?' }]);
                  setIsStartup(false);
                }}
              >
                <User size={20} style={{ marginRight: '10px' }} /> Customer Support
              </button>
              <button 
                className="startup-btn"
                onClick={() => setAuthStep(true)}
              >
                <ShieldCheck size={20} style={{ marginRight: '10px' }} /> Internal Operations
              </button>
            </div>
          ) : (
            <form className="auth-form" onSubmit={handleLogin}>
              <h2>Internal Login</h2>
              {authError && <div style={{ color: '#ff6b6b', marginBottom: '10px', fontSize: '14px' }}>{authError}</div>}
              <input 
                type="text" 
                placeholder="Username" 
                value={username} 
                onChange={e => setUsername(e.target.value)} 
                required 
                className="auth-input"
              />
              <input 
                type="password" 
                placeholder="Password" 
                value={password} 
                onChange={e => setPassword(e.target.value)} 
                required 
                className="auth-input"
              />
              <div style={{ display: 'flex', gap: '10px', marginTop: '10px' }}>
                <button type="button" className="btn-cancel" onClick={() => setAuthStep(false)}>Back</button>
                <button type="submit" className="btn-confirm">Login</button>
              </div>
            </form>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <aside className="sidebar glass-panel">
        <div className="brand">
          <Building className="icon" size={28} />
          <h1>ParcelPilot AI</h1>
        </div>
        
        <div className="settings-section">
          <h3>Session Details</h3>
          <div style={{ padding: '10px', background: 'rgba(255,255,255,0.05)', borderRadius: '8px', marginBottom: '15px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              {persona === 'customer' ? <User size={18} /> : <ShieldCheck size={18} />}
              <strong>{persona === 'customer' ? 'Customer Support' : 'Internal Ops'}</strong>
            </div>
          </div>

          <button 
            className="btn-cancel" 
            style={{ width: '100%', marginBottom: '20px' }}
            onClick={() => {
              setIsStartup(true);
              setAuthStep(false);
              setUsername('');
              setPassword('');
              setMessages([]);
            }}
          >
            Sign Out
          </button>

          {persona === 'customer' && (
            <div className="input-group">
              <label>Simulate Logged-In Customer</label>
              <select 
                value={accountId} 
                onChange={(e) => setAccountId(e.target.value)}
                className="account-select"
              >
                <option value="ACCT-001">Northstar Logistics (ACCT-001)</option>
                <option value="ACCT-002">LumenWorks (ACCT-002)</option>
                <option value="ACCT-003">Beacon Retail (ACCT-003)</option>
                <option value="ACCT-004">Axis Labs (ACCT-004)</option>
              </select>
              <small>The AI will only access data for this account.</small>
            </div>
          )}

          {persona === 'internal' && (
            <div className="input-group" style={{ marginTop: '20px' }}>
              <label>Internal Tools</label>
              <button 
                className="startup-btn" 
                style={{ padding: '10px', background: internalTab === 'chat' ? 'var(--accent)' : '' }}
                onClick={() => setInternalTab('chat')}
              >
                <Bot size={16} /> AI Assistant
              </button>
              <button 
                className="startup-btn" 
                style={{ padding: '10px', background: internalTab === 'orders' ? 'var(--accent)' : '' }}
                onClick={() => setInternalTab('orders')}
              >
                <Database size={16} /> Order Entry
              </button>
              <button 
                className="startup-btn" 
                style={{ padding: '10px', background: internalTab === 'tickets' ? 'var(--accent)' : '' }}
                onClick={() => setInternalTab('tickets')}
              >
                <Ticket size={16} /> Ticket Dashboard
              </button>
            </div>
          )}
        </div>
      </aside>

      <main className="chat-area">
        <div className="chat-header glass-panel">
          <h2>
            {persona === 'customer' ? 'Customer Support' : 
             (internalTab === 'chat' ? 'Operations & Support Center' : 'Bulk & Single Order Entry')}
          </h2>
        </div>
        
        {persona === 'internal' && internalTab === 'orders' ? (
          <div className="orders-container" style={{ padding: '32px', overflowY: 'auto' }}>
            <div className="glass-panel" style={{ padding: '24px', marginBottom: '24px' }}>
              <h3 style={{ marginBottom: '16px', color: 'var(--text-main)' }}>Single Order Input</h3>
              <form onSubmit={submitSingleOrder} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div className="input-group">
                  <label>Account</label>
                  <select 
                    className="account-select"
                    value={singleOrder.account_id}
                    onChange={(e) => setSingleOrder({...singleOrder, account_id: e.target.value})}
                  >
                    <option value="ACCT-001">Northstar Logistics (ACCT-001)</option>
                    <option value="ACCT-002">LumenWorks (ACCT-002)</option>
                    <option value="ACCT-003">Beacon Retail (ACCT-003)</option>
                    <option value="ACCT-004">Axis Labs (ACCT-004)</option>
                    <option value="NEW">+ Create New Account</option>
                  </select>
                  {singleOrder.account_id === 'NEW' && (
                    <input 
                      type="text" 
                      className="auth-input" 
                      placeholder="New Account Name" 
                      required 
                      value={newAccountName}
                      onChange={(e) => setNewAccountName(e.target.value)}
                      style={{ marginTop: '8px' }}
                    />
                  )}
                </div>
                <div className="input-group">
                  <label>Carrier</label>
                  <select 
                    className="account-select"
                    value={singleOrder.carrier}
                    onChange={(e) => setSingleOrder({...singleOrder, carrier: e.target.value})}
                  >
                    <option value="SwiftShip">SwiftShip</option>
                    <option value="EcoTransit">EcoTransit</option>
                    <option value="Global Freight">Global Freight</option>
                    <option value="OTHER">Other...</option>
                  </select>
                  {singleOrder.carrier === 'OTHER' && (
                    <input 
                      type="text" 
                      className="auth-input" 
                      placeholder="Enter Carrier Name" 
                      required 
                      value={customCarrier}
                      onChange={(e) => setCustomCarrier(e.target.value)}
                      style={{ marginTop: '8px' }}
                    />
                  )}
                </div>
                <div className="input-group">
                  <label>Pickup Start Window</label>
                  <DatePicker
                    selected={startDateTime}
                    onChange={(date) => setStartDateTime(date)}
                    showTimeSelect
                    timeFormat="HH:mm"
                    timeIntervals={1}
                    timeCaption="Time"
                    dateFormat="MMMM d, yyyy h:mm aa"
                    className="auth-input"
                    wrapperClassName="date-picker-wrapper"
                    required
                  />
                </div>
                <div className="input-group">
                  <label>Pickup End Window</label>
                  <DatePicker
                    selected={endDateTime}
                    onChange={(date) => setEndDateTime(date)}
                    showTimeSelect
                    timeFormat="HH:mm"
                    timeIntervals={1}
                    timeCaption="Time"
                    dateFormat="MMMM d, yyyy h:mm aa"
                    className="auth-input"
                    wrapperClassName="date-picker-wrapper"
                    required
                  />
                </div>
                <div className="input-group">
                  <label>Shipment Fee (INR)</label>
                  <input 
                    type="number" 
                    className="auth-input" 
                    required 
                    onChange={(e) => setSingleOrder({...singleOrder, shipment_fee_inr: Number(e.target.value)})}
                  />
                </div>
                <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                  <button type="submit" className="btn-confirm" style={{ width: '100%', height: '42px' }}>Create Order</button>
                </div>
              </form>
            </div>

            <div className="glass-panel" style={{ padding: '24px' }}>
              <h3 style={{ marginBottom: '16px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <FileUp size={20} /> Bulk Order Upload (CSV)
              </h3>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '16px' }}>
                Upload a CSV file with headers: account_id, carrier, pickup_window_start, pickup_window_end, shipment_fee_inr
              </p>
              <input 
                type="file" 
                accept=".csv" 
                onChange={handleCsvUpload} 
                style={{ color: 'var(--text-main)', background: 'var(--bg-color)', padding: '10px', borderRadius: 'var(--radius)', border: '1px dashed var(--panel-border)', width: '100%' }}
              />
            </div>

            <div className="glass-panel" style={{ padding: '24px', marginTop: '24px' }}>
              <h3 style={{ marginBottom: '16px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Package size={20} /> Recent Orders
              </h3>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse', color: 'var(--text-main)', fontSize: '13px' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--panel-border)' }}>
                      <th style={{ padding: '12px 8px' }}>Order ID</th>
                      <th style={{ padding: '12px 8px' }}>Account</th>
                      <th style={{ padding: '12px 8px' }}>Status</th>
                      <th style={{ padding: '12px 8px' }}>Carrier</th>
                      <th style={{ padding: '12px 8px' }}>Booked At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Array.isArray(ordersList) && ordersList.map(o => (
                      <tr key={o.order_id} style={{ borderBottom: '1px solid var(--panel-border)' }}>
                        <td style={{ padding: '12px 8px', color: 'var(--accent-glow)' }}>{o.order_id}</td>
                        <td style={{ padding: '12px 8px' }}>{o.account_id}</td>
                        <td style={{ padding: '12px 8px' }}>
                          <span style={{ 
                            padding: '4px 8px', 
                            borderRadius: '12px', 
                            fontSize: '11px',
                            fontWeight: 600,
                            backgroundColor: o.status === 'BOOKED' ? 'rgba(52, 211, 153, 0.15)' : 'rgba(251, 191, 36, 0.15)',
                            color: o.status === 'BOOKED' ? '#34d399' : '#fbbf24'
                          }}>
                            {o.status}
                          </span>
                        </td>
                        <td style={{ padding: '12px 8px' }}>{o.carrier}</td>
                        <td style={{ padding: '12px 8px' }}>{new Date(o.booked_at).toLocaleString()}</td>
                      </tr>
                    ))}
                    {(!Array.isArray(ordersList) || ordersList.length === 0) && (
                      <tr>
                        <td colSpan={5} style={{ padding: '16px 8px', textAlign: 'center', color: 'var(--text-muted)' }}>
                          No recent orders found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ) : persona === 'internal' && internalTab === 'tickets' ? (
          <div className="tickets-container" style={{ padding: '32px', overflowY: 'auto' }}>
            <div className="glass-panel" style={{ padding: '24px' }}>
              <h3 style={{ marginBottom: '16px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Ticket size={20} /> Open Tickets
              </h3>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse', color: 'var(--text-main)', fontSize: '13px' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--panel-border)' }}>
                      <th style={{ padding: '12px 8px' }}>ID</th>
                      <th style={{ padding: '12px 8px' }}>Account</th>
                      <th style={{ padding: '12px 8px' }}>Status</th>
                      <th style={{ padding: '12px 8px' }}>Subject</th>
                      <th style={{ padding: '12px 8px' }}>Created At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Array.isArray(ticketsList) && ticketsList.map(t => (
                      <tr 
                        key={t.ticket_id} 
                        style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', cursor: 'pointer' }}
                        onClick={() => { setSelectedTicket(t); setCloseReason(''); setCloserName(''); }}
                        className="table-row-hover"
                      >
                        <td style={{ padding: '12px 8px', color: 'var(--accent)', fontWeight: 'bold' }}>{t.ticket_id}</td>
                        <td style={{ padding: '12px 8px' }}>{t.account_id}</td>
                        <td style={{ padding: '12px 8px' }}>
                          <span style={{ 
                            padding: '4px 8px', 
                            borderRadius: '12px', 
                            background: t.status === 'open' ? 'rgba(255, 60, 60, 0.2)' : 'rgba(60, 255, 100, 0.2)',
                            color: t.status === 'open' ? '#ff6b6b' : '#69db7c' 
                          }}>
                            {t?.status?.toUpperCase()}
                          </span>
                        </td>
                        <td style={{ padding: '12px 8px' }}>{t.subject}</td>
                        <td style={{ padding: '12px 8px', color: 'var(--text-muted)' }}>{t.created_at}</td>
                      </tr>
                    ))}
                    {(!Array.isArray(ticketsList) || ticketsList.length === 0) && (
                      <tr><td colSpan={5} style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)' }}>No tickets found.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {selectedTicket && (
              <div style={{
                position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
                background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
              }}>
                <div className="glass-panel" style={{ width: '600px', maxWidth: '90%', padding: '24px', position: 'relative' }}>
                  <button 
                    onClick={() => setSelectedTicket(null)} 
                    style={{ position: 'absolute', top: '20px', right: '20px', background: 'transparent', border: 'none', color: 'var(--text-main)', cursor: 'pointer' }}
                  >
                    <X size={24} />
                  </button>
                  <h2 style={{ marginBottom: '8px', color: 'var(--text-main)' }}>{selectedTicket.ticket_id}</h2>
                  <p style={{ color: 'var(--text-muted)', marginBottom: '20px', fontSize: '14px' }}>
                    Created at {selectedTicket.created_at} • Account: {selectedTicket.account_id} • 
                    <span style={{ 
                      marginLeft: '8px', padding: '2px 6px', borderRadius: '8px', fontSize: '12px',
                      background: selectedTicket.status === 'open' ? 'rgba(255, 60, 60, 0.2)' : 'rgba(60, 255, 100, 0.2)',
                      color: selectedTicket.status === 'open' ? '#ff6b6b' : '#69db7c' 
                    }}>
                      {selectedTicket.status?.toUpperCase()}
                    </span>
                  </p>

                  <div style={{ marginBottom: '20px' }}>
                    <h4 style={{ color: 'var(--text-main)', marginBottom: '4px' }}>Customer Contact</h4>
                    <p style={{ color: 'var(--text-muted)', fontSize: '14px', background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '4px' }}>
                      {selectedTicket.customer_contact || "No contact details provided."}
                    </p>
                  </div>

                  <div style={{ marginBottom: '20px' }}>
                    <h4 style={{ color: 'var(--text-main)', marginBottom: '4px' }}>Subject</h4>
                    <p style={{ color: 'var(--text-muted)', fontSize: '14px', background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '4px' }}>
                      {selectedTicket.subject}
                    </p>
                  </div>

                  <div style={{ marginBottom: '20px' }}>
                    <h4 style={{ color: 'var(--text-main)', marginBottom: '4px' }}>Reason Created (Description)</h4>
                    <p style={{ color: 'var(--text-muted)', fontSize: '14px', background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '4px', whiteSpace: 'pre-wrap' }}>
                      {selectedTicket.description || "No description provided."}
                    </p>
                  </div>

                  {selectedTicket.status === 'closed' ? (
                    <div style={{ marginBottom: '20px' }}>
                      <h4 style={{ color: 'var(--text-main)', marginBottom: '4px' }}>Feedback / Resolution</h4>
                      <p style={{ color: 'var(--text-muted)', fontSize: '14px', background: 'rgba(60,255,100,0.1)', borderLeft: '4px solid #69db7c', padding: '12px', borderRadius: '4px', whiteSpace: 'pre-wrap' }}>
                        {selectedTicket.historical_resolution || "Closed without documented resolution."}
                      </p>
                    </div>
                  ) : (
                    <div style={{ marginBottom: '20px' }}>
                      <h4 style={{ color: 'var(--text-main)', marginBottom: '8px' }}>Close Ticket</h4>
                      <input 
                        type="text" 
                        className="auth-input" 
                        placeholder="Your Name (Required)"
                        value={closerName}
                        onChange={(e) => setCloserName(e.target.value)}
                        style={{ width: '100%', marginBottom: '12px' }}
                      />
                      <textarea 
                        className="auth-input" 
                        rows={3} 
                        placeholder="Enter the reason for closing this ticket... (At least one full sentence required)"
                        value={closeReason}
                        onChange={(e) => setCloseReason(e.target.value)}
                        style={{ width: '100%', resize: 'vertical', marginBottom: '12px' }}
                      />
                      <button 
                        className="btn-confirm" 
                        disabled={!(closeReason.trim().length > 15 && closeReason.includes(' ') && closerName.trim().length > 0)}
                        onClick={handleCloseTicket}
                        style={{ opacity: (closeReason.trim().length > 15 && closeReason.includes(' ') && closerName.trim().length > 0) ? 1 : 0.5 }}
                      >
                        Submit & Close Ticket
                      </button>
                      {!(closeReason.trim().length > 15 && closeReason.includes(' ')) && closeReason.length > 0 && (
                        <p style={{ color: '#ff6b6b', fontSize: '12px', marginTop: '8px' }}>Reason must be at least a full sentence.</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ) : (
          <>
            <div className="messages-container">
              {messages.map((msg) => (
                <div key={msg.id} className={`message-wrapper ${msg.role}`}>
                  <div className="avatar">
                    {msg.role === 'assistant' ? <Bot size={20} /> : <User size={20} />}
                  </div>
                  <div className="message-content glass-panel">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    
                    {msg.requires_confirmation && (
                      <div className="confirmation-box">
                        <div className="conf-header">
                          <AlertTriangle size={18} className="warning-icon" />
                          <span>Action Confirmation Required</span>
                        </div>
                        <div className="conf-actions">
                          <button className="btn-cancel" onClick={() => handleConfirm(false, msg.id)}>
                            <X size={16} /> Cancel
                          </button>
                          <button className="btn-confirm" onClick={() => handleConfirm(true, msg.id)}>
                            <Check size={16} /> Confirm Action
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {isLoading && (
                <div className="message-wrapper assistant">
                  <div className="avatar"><Bot size={20} /></div>
                  <div className="message-content glass-panel loading-indicator">
                    <div className="dot"></div><div className="dot"></div><div className="dot"></div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <div className="input-area glass-panel">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder="Type your message here..."
                disabled={isLoading || messages.some(m => m.requires_confirmation)}
              />
              <button 
                onClick={handleSend} 
                disabled={!input.trim() || isLoading || messages.some(m => m.requires_confirmation)}
                className="send-btn"
              >
                <Send size={20} />
              </button>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
