import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
    addContact,
    cancelOrder,
    createOrder,
    getApiBase,
    getDeliveryStats,
    getEventStats,
    getOrder,
    getProfile,
    getZoneStats,
    listContacts,
    login,
    signup,
} from './api';
import './styles.css';
import type { Contact, DeliveryStat, EventStat, OrderRecord, Profile, Role, ZoneStat } from './types';

const TOKEN_KEY = 'smartdispatch.token';

function pretty(value: unknown) {
  return JSON.stringify(value, null, 2);
}

export default function App() {
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) ?? '');
  const [profile, setProfile] = useState<Profile | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [zoneStats, setZoneStats] = useState<ZoneStat[]>([]);
  const [deliveryStats, setDeliveryStats] = useState<DeliveryStat[]>([]);
  const [eventStats, setEventStats] = useState<EventStat[]>([]);
  const [orderLookup, setOrderLookup] = useState('');
  const [orderRecord, setOrderRecord] = useState<OrderRecord | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [auth, setAuth] = useState({ phone: '', password: '', role: 'customer' as Role });
  const [contactForm, setContactForm] = useState({ name: '', phone: '' });
  const [orderForm, setOrderForm] = useState({ lat: '-1.28', lon: '36.82', mode: 'standard' as 'standard' | 'express', item_ref: '' });

  const isAuthed = Boolean(token);

  async function refreshProfile(nextToken = token) {
    if (!nextToken) return;
    const [nextProfile, nextContacts] = await Promise.all([getProfile(nextToken), listContacts(nextToken)]);
    setProfile(nextProfile);
    setContacts(nextContacts);
  }

  async function refreshAnalytics() {
    const [zones, deliveries, events] = await Promise.all([getZoneStats(), getDeliveryStats(), getEventStats()]);
    setZoneStats(zones);
    setDeliveryStats(deliveries);
    setEventStats(events);
  }

  useEffect(() => {
    refreshAnalytics().catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!token) return;
    refreshProfile(token).catch((err: Error) => setError(err.message));
  }, [token]);

  const metrics = useMemo(() => [
    { label: 'Zones tracked', value: String(zoneStats.length) },
    { label: 'Active deliveries', value: String(deliveryStats.length) },
    { label: 'Event streams', value: String(eventStats.length) },
  ], [zoneStats.length, deliveryStats.length, eventStats.length]);

  async function handleAuthSubmit(event: FormEvent) {
    event.preventDefault();
    setError('');
    setMessage('');
    try {
      const response = mode === 'signup'
        ? await signup(auth)
        : await login({ phone: auth.phone, password: auth.password });
      localStorage.setItem(TOKEN_KEY, response.token);
      setToken(response.token);
      setMessage(`${mode === 'signup' ? 'Signed up' : 'Logged in'} successfully.`);
      await refreshProfile(response.token);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed');
    }
  }

  async function handleAddContact(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setError('');
    try {
      await addContact(token, contactForm);
      setContactForm({ name: '', phone: '' });
      await refreshProfile();
      setMessage('Contact saved.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save contact');
    }
  }

  async function handleCreateOrder(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setError('');
    try {
      const response = await createOrder(token, {
        lat: Number(orderForm.lat),
        lon: Number(orderForm.lon),
        mode: orderForm.mode,
        item_ref: orderForm.item_ref || undefined,
      });
      setOrderLookup(response.order_id);
      setMessage(`Order ${response.order_id} placed.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not place order');
    }
  }

  async function handleLookupOrder(event: FormEvent) {
    event.preventDefault();
    setError('');
    try {
      const response = await getOrder(orderLookup.trim());
      setOrderRecord(response);
      setMessage('Order loaded.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load order');
    }
  }

  async function handleCancelOrder() {
    if (!token || !orderLookup.trim()) return;
    setError('');
    try {
      const response = await cancelOrder(token, orderLookup.trim());
      setMessage(`Order ${response.status.toLowerCase()} successfully.`);
      const refreshed = await getOrder(orderLookup.trim());
      setOrderRecord(refreshed);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not cancel order');
    }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken('');
    setProfile(null);
    setContacts([]);
    setMessage('Logged out.');
  }

  return (
    <div className="page-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">SmartDispatch</p>
          <h1>Orders, agents, analytics, and customer contacts in one place.</h1>
          <p className="hero-copy">
            A lightweight frontend for the delivery platform. Sign up, place an order, inspect live stats, and track the active workflow.
          </p>
          <div className="hero-actions">
            <span className="pill">API base: {getApiBase()}</span>
            <span className="pill">{isAuthed ? 'Authenticated' : 'Guest mode'}</span>
          </div>
        </div>
        <div className="hero-panel">
          <h2>Platform snapshot</h2>
          <div className="metric-grid">
            {metrics.map((metric) => (
              <article key={metric.label} className="metric-card">
                <strong>{metric.value}</strong>
                <span>{metric.label}</span>
              </article>
            ))}
          </div>
        </div>
      </header>

      <main className="grid">
        <section className="card">
          <div className="section-head">
            <h2>Auth</h2>
            <div className="segmented">
              <button className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')} type="button">Login</button>
              <button className={mode === 'signup' ? 'active' : ''} onClick={() => setMode('signup')} type="button">Sign up</button>
            </div>
          </div>

          <form className="stack" onSubmit={handleAuthSubmit}>
            <label>
              Phone
              <input value={auth.phone} onChange={(event) => setAuth({ ...auth, phone: event.target.value })} placeholder="+254700000000" />
            </label>
            <label>
              Password
              <input type="password" value={auth.password} onChange={(event) => setAuth({ ...auth, password: event.target.value })} placeholder="••••••••" />
            </label>
            {mode === 'signup' && (
              <label>
                Role
                <select value={auth.role} onChange={(event) => setAuth({ ...auth, role: event.target.value as Role })}>
                  <option value="customer">Customer</option>
                  <option value="agent">Agent</option>
                  <option value="business">Business</option>
                </select>
              </label>
            )}
            <div className="row">
              <button className="primary" type="submit">{mode === 'signup' ? 'Create account' : 'Login'}</button>
              {isAuthed && <button type="button" onClick={logout}>Logout</button>}
            </div>
          </form>
        </section>

        <section className="card">
          <div className="section-head">
            <h2>Profile</h2>
            <button type="button" onClick={() => refreshAnalytics().catch((err: Error) => setError(err.message))}>Refresh stats</button>
          </div>
          {profile ? (
            <div className="stack">
              <div className="detail-grid">
                <div><span>ID</span><strong>{profile.id}</strong></div>
                <div><span>Phone</span><strong>{profile.phone}</strong></div>
                <div><span>Role</span><strong>{profile.role}</strong></div>
                <div><span>Credibility</span><strong>{profile.credibility}</strong></div>
              </div>
              <pre>{pretty(profile)}</pre>
            </div>
          ) : (
            <p className="muted">Sign in to load your account profile and contacts.</p>
          )}
        </section>

        <section className="card">
          <h2>Contacts</h2>
          <form className="inline-form" onSubmit={handleAddContact}>
            <input value={contactForm.name} onChange={(event) => setContactForm({ ...contactForm, name: event.target.value })} placeholder="Contact name" />
            <input value={contactForm.phone} onChange={(event) => setContactForm({ ...contactForm, phone: event.target.value })} placeholder="Phone" />
            <button className="primary" type="submit" disabled={!isAuthed}>Save</button>
          </form>
          <div className="stack">
            {contacts.length ? contacts.map((contact) => (
              <div key={`${contact.phone}-${contact.name}`} className="list-row">
                <strong>{contact.name}</strong>
                <span>{contact.phone}</span>
              </div>
            )) : <p className="muted">No contacts yet.</p>}
          </div>
        </section>

        <section className="card">
          <h2>Place order</h2>
          <form className="stack" onSubmit={handleCreateOrder}>
            <div className="inline-form compact">
              <input value={orderForm.lat} onChange={(event) => setOrderForm({ ...orderForm, lat: event.target.value })} placeholder="Latitude" />
              <input value={orderForm.lon} onChange={(event) => setOrderForm({ ...orderForm, lon: event.target.value })} placeholder="Longitude" />
            </div>
            <div className="inline-form compact">
              <select value={orderForm.mode} onChange={(event) => setOrderForm({ ...orderForm, mode: event.target.value as 'standard' | 'express' })}>
                <option value="standard">Standard</option>
                <option value="express">Express</option>
              </select>
              <input value={orderForm.item_ref} onChange={(event) => setOrderForm({ ...orderForm, item_ref: event.target.value })} placeholder="Optional item reference" />
            </div>
            <button className="primary" type="submit" disabled={!isAuthed}>Submit order</button>
          </form>
        </section>

        <section className="card">
          <h2>Track order</h2>
          <form className="inline-form" onSubmit={handleLookupOrder}>
            <input value={orderLookup} onChange={(event) => setOrderLookup(event.target.value)} placeholder="Order ID" />
            <button className="primary" type="submit">Load</button>
            <button type="button" onClick={handleCancelOrder} disabled={!isAuthed}>Cancel</button>
          </form>
          {orderRecord ? <pre>{pretty(orderRecord)}</pre> : <p className="muted">Load an order ID to inspect its state.</p>}
        </section>

        <section className="card wide">
          <div className="section-head">
            <h2>Analytics</h2>
            <span className="pill">/stats/zones • /stats/deliveries • /stats/events</span>
          </div>
          <div className="analytics-grid">
            <div>
              <h3>Zones</h3>
              <pre>{pretty(zoneStats)}</pre>
            </div>
            <div>
              <h3>Deliveries</h3>
              <pre>{pretty(deliveryStats)}</pre>
            </div>
            <div>
              <h3>Events</h3>
              <pre>{pretty(eventStats)}</pre>
            </div>
          </div>
        </section>
      </main>

      <footer className="footer">
        <span>{message || 'Ready.'}</span>
        <span>{error}</span>
      </footer>
    </div>
  );
}