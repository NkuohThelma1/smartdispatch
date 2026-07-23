import { describe, it, expect, vi, beforeEach } from 'vitest';
import { addContact, cancelOrder, createOrder, getEventStats, getDeliveryStats, getOrder, getZoneStats, login, signup, getApiBase } from './api';

function ok(data: unknown) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function err(message: string, status = 400) {
  return new Response(JSON.stringify({ detail: message }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('api client', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('returns the API base', () => {
    expect(getApiBase()).toBe('/api');
  });

  it('signup calls POST /users/signup with the correct payload', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ id: 'uid', token: 'tok' }) as Response);

    const result = await signup({ phone: '+254700000000', password: 'secret', role: 'customer' });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/users/signup',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ phone: '+254700000000', password: 'secret', role: 'customer' }),
      })
    );
    expect(result).toEqual({ id: 'uid', token: 'tok' });
  });

  it('login calls POST /users/login with the correct payload', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ id: 'uid', token: 'tok' }) as Response);

    const result = await login({ phone: '+254700000000', password: 'secret' });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/users/login',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ phone: '+254700000000', password: 'secret' }),
      })
    );
    expect(result).toEqual({ id: 'uid', token: 'tok' });
  });

  it('createOrder calls POST /orders with token and payload', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ order_id: 'oid', status: 'ACTIVE' }) as Response);

    const result = await createOrder('tok', { lat: -1.28, lon: 36.82, mode: 'standard', item_ref: 'item' });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/orders',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ lat: -1.28, lon: 36.82, mode: 'standard', item_ref: 'item' }),
      })
    );
    const call = (globalThis.fetch as unknown as { mock: { calls: [string, { headers: Headers }][] } }).mock.calls[0];
    const headers = Object.fromEntries((call[1].headers as Headers).entries());
    expect(headers).toEqual(
      expect.objectContaining({ authorization: 'Bearer tok' })
    );
    expect(result).toEqual({ order_id: 'oid', status: 'ACTIVE' });
  });

  it('getOrder calls GET /orders/:id', async () => {
    const order = { id: 'oid', lat: -1.28, lon: 36.82, mode: 'standard' as const, status: 'ACTIVE' };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok(order) as Response);

    const result = await getOrder('oid');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/orders/oid',
      expect.objectContaining({
        method: 'GET',
      })
    );
    expect(result).toEqual(order);
  });

  it('getZoneStats returns array data', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok([{ zone_id: 'z1', count: 2 }]) as Response);

    const result = await getZoneStats();

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/stats/zones',
      expect.objectContaining({
        method: 'GET',
      })
    );
    expect(result).toEqual([{ zone_id: 'z1', count: 2 }]);
  });

  it('getDeliveryStats returns array data', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok([{ agent_id: 'a1', deliveries: 1 }]) as Response);

    const result = await getDeliveryStats();

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/stats/deliveries',
      expect.objectContaining({
        method: 'GET',
      })
    );
    expect(result).toEqual([{ agent_id: 'a1', deliveries: 1 }]);
  });

  it('getEventStats returns array data', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok([{ stream: 'order.placed', total: 1 }]) as Response);

    const result = await getEventStats();

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/stats/events',
      expect.objectContaining({
        method: 'GET',
      })
    );
    expect(result).toEqual([{ stream: 'order.placed', total: 1 }]);
  });

  it('throws on error response with detail', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(err('Unauthorized', 401) as Response);

    await expect(signup({ phone: '+254700000000', password: 'secret', role: 'customer' })).rejects.toThrow('Unauthorized');
  });

  it('throws generic message when detail is missing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 500 }) as Response);

    await expect(login({ phone: '+254700000000', password: 'secret' })).rejects.toThrow();
  });

  it('addContact calls POST /users/contacts with token and payload', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ ok: true }) as Response);

    const result = await addContact('tok', { name: 'Jane', phone: '+254711111111' });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/users/contacts',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ name: 'Jane', phone: '+254711111111' }),
      })
    );
    const call = (globalThis.fetch as unknown as { mock: { calls: [string, { headers: Headers }][] } }).mock.calls[0];
    const headers = Object.fromEntries((call[1].headers as Headers).entries());
    expect(headers).toEqual(
      expect.objectContaining({ authorization: 'Bearer tok' })
    );
    expect(result).toEqual({ ok: true });
  });

  it('cancelOrder calls POST /orders/:id/cancel with token', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ status: 'cancelled' }) as Response);

    const result = await cancelOrder('tok', 'oid');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/orders/oid/cancel',
      expect.objectContaining({
        method: 'POST',
      })
    );
    const call = (globalThis.fetch as unknown as { mock: { calls: [string, { headers: Headers }][] } }).mock.calls[0];
    const headers = Object.fromEntries((call[1].headers as Headers).entries());
    expect(headers).toEqual(
      expect.objectContaining({ authorization: 'Bearer tok' })
    );
    expect(result).toEqual({ status: 'cancelled' });
  });
});
