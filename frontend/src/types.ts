export type Role = 'customer' | 'agent' | 'business';

export interface AuthResponse {
  id: string;
  token: string;
}

export interface Profile {
  id: string;
  phone: string;
  role: Role;
  credibility: number;
}

export interface Contact {
  name: string;
  phone: string;
}

export interface OrderRecord {
  id: string;
  uid?: string;
  lat: number;
  lon: number;
  mode: 'standard' | 'express';
  item_ref?: string;
  status: string;
}

export interface ZoneStat {
  zone_id: string;
  deliveries?: number;
  count?: number;
}

export interface DeliveryStat {
  agent_id: string;
  deliveries?: number;
}

export interface EventStat {
  stream: string;
  total?: number;
  count?: number;
}