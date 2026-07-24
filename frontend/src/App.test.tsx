import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import type { OrderRecord } from './types';

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

function setupFetchMock() {
  let count = 0;
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const urlStr = typeof input === 'string' ? input : input.toString();
    count++;
    if (urlStr.includes('/users/signup') || urlStr.includes('/users/login')) {
      return Promise.resolve(ok({ id: 'uid', token: 'tok' }) as Response);
    }
    if (urlStr.includes('/orders') && !urlStr.includes('/stats')) {
      return Promise.resolve(ok({ order_id: 'oid', status: 'ACTIVE' }) as Response);
    }
    if (urlStr.includes('/users/me')) {
      return Promise.resolve(ok({ id: 'uid', phone: '+254700000000', role: 'customer', credibility: 1 }) as Response);
    }
    return Promise.resolve(ok([]) as Response);
  });
}

function setupContactMock(newContact: { name: string; phone: string }) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const urlStr = typeof input === 'string' ? input : input.toString();
    if (urlStr.includes('/users/contacts') && urlStr.includes('POST')) {
      return Promise.resolve(ok({ ok: true }) as Response);
    }
    if (urlStr.includes('/users/me')) {
      return Promise.resolve(ok({ id: 'uid', phone: '+254700000000', role: 'customer', credibility: 1 }) as Response);
    }
    if (urlStr.includes('/users/contacts') && !urlStr.includes('POST')) {
      return Promise.resolve(ok([newContact]) as Response);
    }
    return Promise.resolve(ok([]) as Response);
  });
}

function setupOrderLookupMock(orderRecord: OrderRecord) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const urlStr = typeof input === 'string' ? input : input.toString();
    if (urlStr.includes('/orders/') && !urlStr.includes('/cancel')) {
      return Promise.resolve(ok(orderRecord) as Response);
    }
    return Promise.resolve(ok([]) as Response);
  });
}

function setupCancelMock(orderRecord: OrderRecord) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const urlStr = typeof input === 'string' ? input : input.toString();
    if (urlStr.includes('/cancel')) {
      return Promise.resolve(ok({ status: 'cancelled' }) as Response);
    }
    if (urlStr.includes('/orders/')) {
      return Promise.resolve(ok(orderRecord) as Response);
    }
    return Promise.resolve(ok([]) as Response);
  });
}

describe('App auth and order flows', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
  });

  it('signs up a new user and shows success message', async () => {
    setupFetchMock();
    render(<App />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Sign up' }));
    await user.type(screen.getByPlaceholderText('+254700000000'), '+254700000000');
    await user.type(screen.getByPlaceholderText('••••••••'), 'password123');
    const selects = screen.getAllByRole('combobox');
    await user.selectOptions(selects[0], 'customer');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    await waitFor(() => expect(screen.getByText('Signed up successfully.')).toBeVisible());
  });

  it('logs in an existing user and shows success message', async () => {
    setupFetchMock();
    render(<App />);

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('+254700000000'), '+254700000000');
    await user.type(screen.getByPlaceholderText('••••••••'), 'password123');
    await user.click(screen.getAllByRole('button', { name: 'Login' })[1]);

    await waitFor(() => expect(screen.getByText('Logged in successfully.')).toBeVisible());
  });

  it('shows error message when login fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      return Promise.resolve(err('Invalid credentials') as Response);
    });
    render(<App />);

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('+254700000000'), '+254700000000');
    await user.type(screen.getByPlaceholderText('••••••••'), 'wrong');
    await user.click(screen.getAllByRole('button', { name: 'Login' })[1]);

    await waitFor(() => expect(screen.getByText('Invalid credentials')).toBeVisible());
  });

  it('places an order when authenticated and shows success message', async () => {
    localStorage.setItem('smartdispatch.token', 'tok');
    setupFetchMock();
    render(<App />);

    const user = userEvent.setup();
    const modeSelect = screen.getAllByRole('combobox')[0];
    await user.type(screen.getByPlaceholderText('Latitude'), '-1.28');
    await user.type(screen.getByPlaceholderText('Longitude'), '36.82');
    await user.selectOptions(modeSelect, 'standard');
    await user.type(screen.getByPlaceholderText('Optional item reference'), 'E2E test item');
    await user.click(screen.getByRole('button', { name: 'Submit order' }));

    await waitFor(() => expect(screen.getByText('Order oid placed.')).toBeVisible());
  });

  it('does not submit order when not authenticated', async () => {
    localStorage.removeItem('smartdispatch.token');
    render(<App />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Submit order' }));

    expect(screen.queryByText(/Order .* placed/)).not.toBeInTheDocument();
  });

  it('logs out and clears auth state', async () => {
    localStorage.setItem('smartdispatch.token', 'tok');
    setupFetchMock();
    render(<App />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Logout' }));

    await waitFor(() => expect(screen.getByText('Logged out.')).toBeVisible());
    expect(localStorage.getItem('smartdispatch.token')).toBeNull();
  });

  it('adds a contact and renders it in the contacts list', async () => {
    localStorage.setItem('smartdispatch.token', 'tok');
    const newContact = { name: 'Jane', phone: '+254711111111' };
    setupContactMock(newContact);
    render(<App />);

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('Contact name'), 'Jane');
    await user.type(screen.getByPlaceholderText('Phone'), '+254711111111');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(screen.getByText('Contact saved.')).toBeVisible());
    expect(screen.getByText('Jane')).toBeVisible();
    expect(screen.getByText('+254711111111')).toBeVisible();
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/users/contacts',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(newContact),
      })
    );
  });

  it('looks up an order and renders the order record', async () => {
    localStorage.setItem('smartdispatch.token', 'tok');
    const orderRecord = { id: 'oid', lat: -1.28, lon: 36.82, mode: 'standard' as const, status: 'ACTIVE' };
    setupOrderLookupMock(orderRecord);
    render(<App />);

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('Order ID'), 'oid');
    await user.click(screen.getByRole('button', { name: 'Load' }));

    await waitFor(() => expect(screen.getByText('Order loaded.')).toBeVisible());
    const trackSection = screen.getByText('Track order').closest('section')!;
    expect(trackSection).toHaveTextContent('"id": "oid"');
    expect(trackSection).toHaveTextContent('"status": "ACTIVE"');
  });

  it('cancels an order and reflects the cancellation', async () => {
    localStorage.setItem('smartdispatch.token', 'tok');
    const orderRecord = { id: 'oid', lat: -1.28, lon: 36.82, mode: 'standard' as const, status: 'cancelled' };
    setupCancelMock(orderRecord);
    render(<App />);

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('Order ID'), 'oid');
    await user.click(screen.getByRole('button', { name: 'Load' }));

    await waitFor(() => expect(screen.getByText('Order loaded.')).toBeVisible());
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.getByText(/cancelled successfully/i)).toBeVisible());
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/orders/oid/cancel',
      expect.objectContaining({
        method: 'POST',
      })
    );
  });

  it('switches to login mode when Login segmented button is clicked', async () => {
    setupFetchMock();
    render(<App />);

    const user = userEvent.setup();
    const loginButtons = screen.getAllByRole('button', { name: 'Login' });
    const segmentedLogin = loginButtons[0];
    const submitLogin = loginButtons[1];

    expect(segmentedLogin.className).toContain('active');
    expect(submitLogin.className).not.toContain('active');

    await user.click(screen.getByRole('button', { name: 'Sign up' }));
    expect(screen.getByRole('button', { name: 'Sign up' }).className).toContain('active');
    expect(segmentedLogin.className).not.toContain('active');

    await user.click(segmentedLogin);
    expect(segmentedLogin.className).toContain('active');
    expect(screen.getByRole('button', { name: 'Sign up' }).className).not.toContain('active');
  });

  it('refreshes analytics when Refresh stats button is clicked', async () => {
    localStorage.setItem('smartdispatch.token', 'tok');
    setupFetchMock();
    render(<App />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Refresh stats' }));

    await waitFor(() => expect(screen.getByText('Zones tracked')).toBeVisible());
  });
});
