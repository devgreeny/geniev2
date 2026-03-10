import { useState, useEffect } from 'react'
import './App.css'

interface Message {
  id: string
  direction: 'inbound' | 'outbound'
  message: string
  participant_phone: string
  created_at: string
  role: string
}

interface Business {
  id: string
  business_name: string
  owner_name: string
  services: string
  pricing: string
  hours: string
  availability: string
  custom_context: string
}

interface Lead {
  id: string
  customer_phone: string
  customer_name: string
  job_description: string
  status: string
  created_at: string
}

interface Stats {
  messages_today: number
  total_conversations: number
  new_leads: number
  active_customers: number
}

const API_URL = 'http://localhost:3000'

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [business, setBusiness] = useState<Business | null>(null)
  const [leads, setLeads] = useState<Lead[]>([])
  const [stats, setStats] = useState<Stats>({ messages_today: 0, total_conversations: 0, new_leads: 0, active_customers: 0 })
  const [currentPage, setCurrentPage] = useState<'messages' | 'leads' | 'settings'>('messages')
  const [isEditing, setIsEditing] = useState(false)
  const [formData, setFormData] = useState<Partial<Business>>({})
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date())

  useEffect(() => {
    loadData()
    // Auto-refresh every 10 seconds
    const interval = setInterval(loadData, 10000)
    return () => clearInterval(interval)
  }, [])

  async function loadData() {
    try {
      const [messagesRes, businessRes, leadsRes, statsRes] = await Promise.all([
        fetch(`${API_URL}/api/messages`),
        fetch(`${API_URL}/api/business`),
        fetch(`${API_URL}/api/leads`),
        fetch(`${API_URL}/api/stats`),
      ])
      
      if (messagesRes.ok) setMessages(await messagesRes.json())
      if (businessRes.ok) {
        const b = await businessRes.json()
        setBusiness(b)
        setFormData(b)
      }
      if (leadsRes.ok) setLeads(await leadsRes.json())
      if (statsRes.ok) setStats(await statsRes.json())
      setLastRefresh(new Date())
    } catch (err) {
      console.error('Could not load data:', err)
    }
  }

  async function saveSettings() {
    try {
      const res = await fetch(`${API_URL}/api/business`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      })
      if (res.ok) {
        const updated = await res.json()
        setBusiness(updated)
        setFormData(updated)
        setIsEditing(false)
        alert('Settings saved successfully!')
      }
    } catch (err) {
      console.error('Could not save:', err)
      alert('Could not save settings. Please try again.')
    }
  }

  function formatTime(dateStr: string) {
    const date = new Date(dateStr)
    return date.toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit',
      hour12: true 
    })
  }

  function formatDate(dateStr: string) {
    const date = new Date(dateStr)
    const today = new Date()
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)
    
    if (date.toDateString() === today.toDateString()) return 'Today'
    if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'
    return date.toLocaleDateString('en-US', { 
      weekday: 'long',
      month: 'long', 
      day: 'numeric' 
    })
  }

  function formatPhone(phone: string) {
    // Format phone number nicely
    const cleaned = phone.replace(/\D/g, '')
    if (cleaned.length === 11 && cleaned.startsWith('1')) {
      return `(${cleaned.slice(1,4)}) ${cleaned.slice(4,7)}-${cleaned.slice(7)}`
    }
    if (cleaned.length === 10) {
      return `(${cleaned.slice(0,3)}) ${cleaned.slice(3,6)}-${cleaned.slice(6)}`
    }
    return phone
  }

  return (
    <div className="app">
      {/* HEADER */}
      <header className="header">
        <h1>✨ Genie Dashboard</h1>
        <div className="business-name">{business?.business_name || 'Loading...'}</div>
      </header>

      {/* STATS ROW */}
      <div className="stats-row">
        <div className="stat-box">
          <span className="number">{stats.messages_today}</span>
          <span className="label">Messages Today</span>
        </div>
        <div className="stat-box">
          <span className="number">{stats.active_customers}</span>
          <span className="label">Active Customers</span>
        </div>
        <div className="stat-box">
          <span className="number">{stats.new_leads}</span>
          <span className="label">New Leads</span>
        </div>
        <div className="stat-box">
          <span className="number">{stats.total_conversations}</span>
          <span className="label">Total Messages</span>
        </div>
      </div>

      {/* NAVIGATION */}
      <nav className="nav-tabs">
        <button 
          className={`nav-tab ${currentPage === 'messages' ? 'active' : ''}`}
          onClick={() => setCurrentPage('messages')}
        >
          📬 Messages
        </button>
        <button 
          className={`nav-tab ${currentPage === 'leads' ? 'active' : ''}`}
          onClick={() => setCurrentPage('leads')}
        >
          👥 Leads ({leads.length})
        </button>
        <button 
          className={`nav-tab ${currentPage === 'settings' ? 'active' : ''}`}
          onClick={() => setCurrentPage('settings')}
        >
          ⚙️ Settings
        </button>
      </nav>

      {/* MAIN CONTENT */}
      <main className="main-content">
        
        {/* MESSAGES PAGE */}
        {currentPage === 'messages' && (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h2 className="section-title" style={{ marginBottom: 0, borderBottom: 'none', paddingBottom: 0 }}>
                Recent Conversations
              </h2>
              <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                <span className="live-badge">
                  <span className="live-dot"></span>
                  Auto-updating
                </span>
                <button className="refresh-btn" onClick={loadData}>
                  🔄 Refresh Now
                </button>
              </div>
            </div>
            
            {messages.length === 0 ? (
              <div className="no-messages">
                <p>📭 No messages yet.</p>
                <p style={{ marginTop: '10px', color: '#888' }}>
                  Messages will appear here when customers text your business number.
                </p>
              </div>
            ) : (
              <div className="message-list">
                {messages.map((msg, idx) => {
                  const showDate = idx === 0 || formatDate(messages[idx - 1].created_at) !== formatDate(msg.created_at)
                  const isCustomer = msg.direction === 'inbound'
                  
                  return (
                    <div key={msg.id}>
                      {showDate && (
                        <div className="date-separator">{formatDate(msg.created_at)}</div>
                      )}
                      <div className={`message-item ${isCustomer ? 'from-customer' : 'from-genie'}`}>
                        <div className="message-header">
                          <span className="sender">
                            {isCustomer ? `📱 Customer (${formatPhone(msg.participant_phone)})` : '🤖 Genie (Auto-Reply)'}
                          </span>
                          <span className="time">{formatTime(msg.created_at)}</span>
                        </div>
                        <div className="message-text">{msg.message}</div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}

        {/* LEADS PAGE */}
        {currentPage === 'leads' && (
          <>
            <h2 className="section-title">Your Leads</h2>
            
            {leads.length === 0 ? (
              <div className="no-leads">
                <p>👥 No leads yet.</p>
                <p style={{ marginTop: '10px', color: '#888' }}>
                  When potential customers reach out, they'll be tracked here.
                </p>
              </div>
            ) : (
              <div className="leads-list">
                {leads.map(lead => (
                  <div key={lead.id} className="lead-item">
                    <div className="phone">{formatPhone(lead.customer_phone)}</div>
                    {lead.customer_name && (
                      <div className="name">👤 {lead.customer_name}</div>
                    )}
                    {lead.job_description && (
                      <div className="description">
                        <strong>What they said:</strong> "{lead.job_description}"
                      </div>
                    )}
                    <div className="meta">
                      <span className="date">{formatDate(lead.created_at)}</span>
                      <span className={`status-badge ${lead.status}`}>{lead.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* SETTINGS PAGE */}
        {currentPage === 'settings' && business && (
          <>
            <h2 className="section-title">Business Settings</h2>
            <p style={{ marginBottom: '25px', color: '#666', fontSize: '16px' }}>
              This information helps Genie answer customer questions accurately.
            </p>
            
            <div className="settings-form">
              <div className="form-field">
                <label>Business Name</label>
                <input 
                  type="text"
                  value={formData.business_name || ''}
                  onChange={e => setFormData({...formData, business_name: e.target.value})}
                  disabled={!isEditing}
                  placeholder="e.g., Joe's Barbershop"
                />
              </div>

              <div className="form-field">
                <label>Services You Offer</label>
                <textarea 
                  value={formData.services || ''}
                  onChange={e => setFormData({...formData, services: e.target.value})}
                  disabled={!isEditing}
                  placeholder="e.g., Haircuts, beard trims, hot towel shaves"
                />
                <div className="hint">List what services your business provides</div>
              </div>

              <div className="form-field">
                <label>Pricing</label>
                <textarea 
                  value={formData.pricing || ''}
                  onChange={e => setFormData({...formData, pricing: e.target.value})}
                  disabled={!isEditing}
                  placeholder="e.g., Haircut $25, Beard trim $15"
                />
                <div className="hint">List your prices so Genie can quote customers</div>
              </div>

              <div className="form-field">
                <label>Business Hours</label>
                <input 
                  type="text"
                  value={formData.hours || ''}
                  onChange={e => setFormData({...formData, hours: e.target.value})}
                  disabled={!isEditing}
                  placeholder="e.g., Mon-Sat 9am-6pm, Closed Sunday"
                />
              </div>

              <div className="form-field">
                <label>Current Availability</label>
                <input 
                  type="text"
                  value={formData.availability || ''}
                  onChange={e => setFormData({...formData, availability: e.target.value})}
                  disabled={!isEditing}
                  placeholder="e.g., Walk-ins welcome, Booked until Friday"
                />
                <div className="hint">Update this when your schedule changes</div>
              </div>

              <div className="form-field">
                <label>Special Notes for Genie</label>
                <textarea 
                  value={formData.custom_context || ''}
                  onChange={e => setFormData({...formData, custom_context: e.target.value})}
                  disabled={!isEditing}
                  placeholder="e.g., Ask for Mike for the best fades. We're cash only. Parking in rear."
                />
                <div className="hint">Any extra info you want Genie to know when chatting with customers</div>
              </div>

              <div className="button-row">
                {isEditing ? (
                  <>
                    <button className="btn btn-primary" onClick={saveSettings}>
                      💾 Save Changes
                    </button>
                    <button className="btn btn-secondary" onClick={() => {
                      setIsEditing(false)
                      setFormData(business)
                    }}>
                      ✕ Cancel
                    </button>
                  </>
                ) : (
                  <button className="btn btn-primary" onClick={() => setIsEditing(true)}>
                    ✏️ Edit Settings
                  </button>
                )}
              </div>
            </div>
          </>
        )}
      </main>

      {/* FOOTER */}
      <footer className="footer">
        <p>Last updated: {lastRefresh.toLocaleTimeString()}</p>
        <p style={{ marginTop: '5px' }}>Genie is working 24/7 to help your customers ✨</p>
      </footer>
    </div>
  )
}

export default App
