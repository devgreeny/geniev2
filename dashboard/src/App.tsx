import { useState, useEffect } from 'react'
import './App.css'

interface Message {
  id: string
  direction: 'inbound' | 'outbound'
  message: string
  participant_phone: string
  created_at: string
  role: string
  read_at: string | null
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

interface Booking {
  id: string
  customer_name: string
  customer_phone: string
  service: string
  datetime: string
  status: string
}

interface Approval {
  id: string
  recipient_phone: string
  recipient_name: string | null
  message_text: string
  reason: string | null
  status: string
  created_at: string
}

interface TodayView {
  unread_conversations: number
  pending_approvals: number
  today_bookings: number
  bookings: Booking[]
  campaigns_sent_today: number
  ai_paused: boolean
  funnel: {
    inbound: number
    booked: number
    conversion_rate: number
  }
}

const API_URL = 'http://localhost:3000'

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [business, setBusiness] = useState<Business | null>(null)
  const [leads, setLeads] = useState<Lead[]>([])
  const [todayView, setTodayView] = useState<TodayView | null>(null)
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [currentPage, setCurrentPage] = useState<'today' | 'messages' | 'leads' | 'settings'>('today')
  const [isEditing, setIsEditing] = useState(false)
  const [formData, setFormData] = useState<Partial<Business>>({})
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date())

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 10000)
    return () => clearInterval(interval)
  }, [])

  async function loadData() {
    try {
      const [messagesRes, businessRes, leadsRes, todayRes, approvalsRes] = await Promise.all([
        fetch(`${API_URL}/api/messages`),
        fetch(`${API_URL}/api/business`),
        fetch(`${API_URL}/api/leads`),
        fetch(`${API_URL}/api/today`),
        fetch(`${API_URL}/api/approvals`),
      ])
      
      if (messagesRes.ok) setMessages(await messagesRes.json())
      if (businessRes.ok) {
        const b = await businessRes.json()
        setBusiness(b)
        setFormData(b)
      }
      if (leadsRes.ok) setLeads(await leadsRes.json())
      if (todayRes.ok) setTodayView(await todayRes.json())
      if (approvalsRes.ok) setApprovals(await approvalsRes.json())
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
      }
    } catch (err) {
      console.error('Could not save:', err)
    }
  }

  async function toggleAi() {
    try {
      const endpoint = todayView?.ai_paused ? '/api/ai/resume' : '/api/ai/pause'
      await fetch(`${API_URL}${endpoint}`, { method: 'POST' })
      loadData()
    } catch (err) {
      console.error('Could not toggle AI:', err)
    }
  }

  async function handleApproval(id: string, action: 'approve' | 'reject') {
    try {
      await fetch(`${API_URL}/api/approvals/${id}/${action}`, { method: 'POST' })
      loadData()
    } catch (err) {
      console.error(`Could not ${action}:`, err)
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
        <div className="header-left">
          <div className="logo">
            <span className="logo-icon">◆</span>
            <span className="logo-text">genie</span>
          </div>
          <div className="business-badge">{business?.business_name || 'Loading...'}</div>
        </div>
        <div className="header-right">
          <div className="ai-status" onClick={toggleAi}>
            <span className={`ai-indicator ${todayView?.ai_paused ? 'paused' : 'active'}`}></span>
            <span>AI {todayView?.ai_paused ? 'Paused' : 'Active'}</span>
          </div>
          <span className="last-update">Updated {lastRefresh.toLocaleTimeString()}</span>
        </div>
      </header>

      {/* NAVIGATION */}
      <nav className="nav">
        <button 
          className={`nav-item ${currentPage === 'today' ? 'active' : ''}`}
          onClick={() => setCurrentPage('today')}
        >
          <span className="nav-icon">◉</span>
          Today
        </button>
        <button 
          className={`nav-item ${currentPage === 'messages' ? 'active' : ''}`}
          onClick={() => setCurrentPage('messages')}
        >
          <span className="nav-icon">◈</span>
          Messages
          {todayView && todayView.unread_conversations > 0 && (
            <span className="badge">{todayView.unread_conversations}</span>
          )}
        </button>
        <button 
          className={`nav-item ${currentPage === 'leads' ? 'active' : ''}`}
          onClick={() => setCurrentPage('leads')}
        >
          <span className="nav-icon">◇</span>
          Leads
          {leads.filter(l => l.status === 'new').length > 0 && (
            <span className="badge">{leads.filter(l => l.status === 'new').length}</span>
          )}
        </button>
        <button 
          className={`nav-item ${currentPage === 'settings' ? 'active' : ''}`}
          onClick={() => setCurrentPage('settings')}
        >
          <span className="nav-icon">⚙</span>
          Settings
        </button>
      </nav>

      {/* MAIN CONTENT */}
      <main className="main">
        
        {/* TODAY VIEW */}
        {currentPage === 'today' && todayView && (
          <div className="today-view">
            {/* Quick Stats Row */}
            <div className="stats-grid">
              <div className="stat-card highlight">
                <div className="stat-value">{todayView.unread_conversations}</div>
                <div className="stat-label">Unread Messages</div>
                <div className="stat-action" onClick={() => setCurrentPage('messages')}>View →</div>
              </div>
              <div className={`stat-card ${todayView.pending_approvals > 0 ? 'alert' : ''}`}>
                <div className="stat-value">{todayView.pending_approvals}</div>
                <div className="stat-label">Pending Approvals</div>
                {todayView.pending_approvals > 0 && <div className="stat-action">Review below ↓</div>}
              </div>
              <div className="stat-card">
                <div className="stat-value">{todayView.today_bookings}</div>
                <div className="stat-label">Today's Bookings</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{todayView.campaigns_sent_today}</div>
                <div className="stat-label">Campaigns Sent</div>
              </div>
            </div>

            {/* Approval Queue */}
            {approvals.length > 0 && (
              <section className="section approval-section">
                <h2 className="section-title">
                  <span className="section-icon">⚡</span>
                  Needs Your Approval
                </h2>
                <div className="approval-list">
                  {approvals.map(approval => (
                    <div key={approval.id} className="approval-card">
                      <div className="approval-header">
                        <span className="approval-to">To: {approval.recipient_name || formatPhone(approval.recipient_phone)}</span>
                        {approval.reason && <span className="approval-reason">{approval.reason}</span>}
                      </div>
                      <div className="approval-message">"{approval.message_text}"</div>
                      <div className="approval-actions">
                        <button 
                          className="btn btn-approve"
                          onClick={() => handleApproval(approval.id, 'approve')}
                        >
                          ✓ Approve & Send
                        </button>
                        <button 
                          className="btn btn-reject"
                          onClick={() => handleApproval(approval.id, 'reject')}
                        >
                          ✕ Reject
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Today's Schedule */}
            <section className="section">
              <h2 className="section-title">
                <span className="section-icon">📅</span>
                Today's Schedule
              </h2>
              {todayView.bookings.length === 0 ? (
                <div className="empty-state">
                  <p>No appointments scheduled for today.</p>
                </div>
              ) : (
                <div className="schedule-list">
                  {todayView.bookings.map(booking => (
                    <div key={booking.id} className="schedule-item">
                      <div className="schedule-time">{formatTime(booking.datetime)}</div>
                      <div className="schedule-details">
                        <div className="schedule-customer">{booking.customer_name || formatPhone(booking.customer_phone)}</div>
                        <div className="schedule-service">{booking.service}</div>
                      </div>
                      <div className={`schedule-status ${booking.status}`}>{booking.status}</div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Conversion Funnel */}
            <section className="section">
              <h2 className="section-title">
                <span className="section-icon">📊</span>
                This Week's Funnel
              </h2>
              <div className="funnel">
                <div className="funnel-stage">
                  <div className="funnel-bar" style={{ width: '100%' }}></div>
                  <div className="funnel-content">
                    <span className="funnel-label">Inbound Customers</span>
                    <span className="funnel-value">{todayView.funnel.inbound}</span>
                  </div>
                </div>
                <div className="funnel-arrow">↓</div>
                <div className="funnel-stage">
                  <div 
                    className="funnel-bar booked" 
                    style={{ width: `${Math.max(todayView.funnel.conversion_rate, 5)}%` }}
                  ></div>
                  <div className="funnel-content">
                    <span className="funnel-label">Booked</span>
                    <span className="funnel-value">{todayView.funnel.booked}</span>
                  </div>
                </div>
                <div className="funnel-conversion">
                  <span className="conversion-rate">{todayView.funnel.conversion_rate}%</span>
                  <span className="conversion-label">conversion rate</span>
                </div>
              </div>
            </section>
          </div>
        )}

        {/* MESSAGES PAGE */}
        {currentPage === 'messages' && (
          <div className="messages-view">
            <div className="page-header">
              <h1>Messages</h1>
              <button className="btn btn-secondary" onClick={loadData}>↻ Refresh</button>
            </div>
            
            {messages.length === 0 ? (
              <div className="empty-state">
                <p>No messages yet. They'll appear here when customers text.</p>
              </div>
            ) : (
              <div className="message-list">
                {messages.map((msg, idx) => {
                  const showDate = idx === 0 || formatDate(messages[idx - 1].created_at) !== formatDate(msg.created_at)
                  const isCustomer = msg.direction === 'inbound'
                  const isUnread = isCustomer && !msg.read_at
                  
                  return (
                    <div key={msg.id}>
                      {showDate && (
                        <div className="date-divider">{formatDate(msg.created_at)}</div>
                      )}
                      <div className={`message ${isCustomer ? 'inbound' : 'outbound'} ${isUnread ? 'unread' : ''}`}>
                        <div className="message-meta">
                          <span className="message-sender">
                            {isCustomer ? formatPhone(msg.participant_phone) : 'Genie AI'}
                          </span>
                          <span className="message-time">{formatTime(msg.created_at)}</span>
                        </div>
                        <div className="message-body">{msg.message}</div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* LEADS PAGE */}
        {currentPage === 'leads' && (
          <div className="leads-view">
            <div className="page-header">
              <h1>Leads</h1>
            </div>
            
            {leads.length === 0 ? (
              <div className="empty-state">
                <p>No leads tracked yet. They'll appear when potential customers reach out.</p>
              </div>
            ) : (
              <div className="leads-list">
                {leads.map(lead => (
                  <div key={lead.id} className="lead-card">
                    <div className="lead-header">
                      <span className="lead-phone">{formatPhone(lead.customer_phone)}</span>
                      <span className={`lead-status ${lead.status}`}>{lead.status}</span>
                    </div>
                    {lead.customer_name && <div className="lead-name">{lead.customer_name}</div>}
                    {lead.job_description && (
                      <div className="lead-description">"{lead.job_description}"</div>
                    )}
                    <div className="lead-date">{formatDate(lead.created_at)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* SETTINGS PAGE */}
        {currentPage === 'settings' && business && (
          <div className="settings-view">
            <div className="page-header">
              <h1>Business Settings</h1>
              {!isEditing ? (
                <button className="btn btn-primary" onClick={() => setIsEditing(true)}>Edit</button>
              ) : (
                <div style={{ display: 'flex', gap: '10px' }}>
                  <button className="btn btn-primary" onClick={saveSettings}>Save</button>
                  <button className="btn btn-secondary" onClick={() => {
                    setIsEditing(false)
                    setFormData(business)
                  }}>Cancel</button>
                </div>
              )}
            </div>
            
            <p className="settings-description">
              This information helps Genie answer customer questions accurately.
            </p>
            
            <div className="settings-form">
              <div className="field">
                <label>Business Name</label>
                <input 
                  type="text"
                  value={formData.business_name || ''}
                  onChange={e => setFormData({...formData, business_name: e.target.value})}
                  disabled={!isEditing}
                />
              </div>

              <div className="field">
                <label>Services</label>
                <textarea 
                  value={formData.services || ''}
                  onChange={e => setFormData({...formData, services: e.target.value})}
                  disabled={!isEditing}
                  placeholder="List your services..."
                />
              </div>

              <div className="field">
                <label>Pricing</label>
                <textarea 
                  value={formData.pricing || ''}
                  onChange={e => setFormData({...formData, pricing: e.target.value})}
                  disabled={!isEditing}
                  placeholder="List your prices..."
                />
              </div>

              <div className="field">
                <label>Business Hours</label>
                <input 
                  type="text"
                  value={formData.hours || ''}
                  onChange={e => setFormData({...formData, hours: e.target.value})}
                  disabled={!isEditing}
                  placeholder="e.g., Mon-Sat 9am-6pm"
                />
              </div>

              <div className="field">
                <label>Current Availability</label>
                <input 
                  type="text"
                  value={formData.availability || ''}
                  onChange={e => setFormData({...formData, availability: e.target.value})}
                  disabled={!isEditing}
                  placeholder="e.g., Walk-ins welcome"
                />
              </div>

              <div className="field">
                <label>Special Notes for Genie</label>
                <textarea 
                  value={formData.custom_context || ''}
                  onChange={e => setFormData({...formData, custom_context: e.target.value})}
                  disabled={!isEditing}
                  placeholder="Any extra info Genie should know..."
                />
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
