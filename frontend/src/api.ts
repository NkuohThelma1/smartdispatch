import type { AuthResponse, Contact, DeliveryStat, EventStat, OrderRecord, Profile, Role, ZoneStat } from './types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api';

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  if (!headers.has('Content-Type') && init.body) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const message = data?.detail ?? data?.message ?? response.statusText;
    throw new Error(typeof message === 'string' ? message : 'Request failed');
  }

  return data as T;
}

export function signup(payload: { phone: string; password: string; role: Role }) {
  return request<AuthResponse>('/users/signup', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function login(payload: { phone: string; password: string }) {
  return request<AuthResponse>('/users/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getProfile(token: string) {
  return request<Profile>('/users/me', { method: 'GET' }, token);
}

export function listContacts(token: string) {
  return request<Contact[]>('/users/contacts', { method: 'GET' }, token);
}

export function addContact(token: string, payload: Contact) {
  return request<{ ok: true }>('/users/contacts', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, token);
}

export function createOrder(token: string, payload: { lat: number; lon: number; mode: 'standard' | 'express'; item_ref?: string }) {
  return request<{ order_id: string; status: string }>('/orders', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, token);
}

export function getOrder(orderId: string) {
  return request<OrderRecord>(`/orders/${orderId}`, { method: 'GET' });
}

export function cancelOrder(token: string, orderId: string) {
  return request<{ status: string }>(`/orders/${orderId}/cancel`, { method: 'POST' }, token);
}

export function getZoneStats() {
  return request<ZoneStat[]>('/stats/zones', { method: 'GET' });
}

export function getDeliveryStats() {
  return request<DeliveryStat[]>('/stats/deliveries', { method: 'GET' });
}

export function getEventStats() {
  return request<EventStat[]>('/stats/events', { method: 'GET' });
}

export function getApiBase() {
  return API_BASE;
}