import crypto from 'crypto';

// Vonage API credentials
const API_KEY = process.env.VONAGE_API_KEY || '';
const API_SECRET = process.env.VONAGE_API_SECRET || '';
const SIGNATURE_SECRET = process.env.VONAGE_SIGNATURE_SECRET || '';
const VONAGE_NUMBER = process.env.VONAGE_NUMBER || '';

// Use Messages API for toll-free SMS
const VONAGE_API_URL = 'https://api.nexmo.com/v1/messages';

export interface SendSmsResult {
  messageId: string;
  status: 'queued' | 'submitted';
}

export interface VonageInboundMessage {
  message_uuid: string;
  from: string;  // { type: 'sms', number: string }
  to: string;    // { type: 'sms', number: string }
  text: string;
  timestamp: string;
  channel?: string;
}

export interface VonageStatusCallback {
  message_uuid: string;
  to: string;
  from: string;
  timestamp: string;
  status: 'submitted' | 'delivered' | 'rejected' | 'undeliverable' | 'failed';
  error?: {
    code?: string;
    reason?: string;
  };
  usage?: {
    currency: string;
    price: string;
  };
}

/**
 * Initialize Vonage service - validates credentials are present
 */
export function initVonage(): boolean {
  if (!API_KEY || !API_SECRET) {
    console.log('[vonage] No credentials configured - SMS disabled');
    return false;
  }
  
  if (!VONAGE_NUMBER) {
    console.warn('[vonage] No VONAGE_NUMBER configured - outbound SMS will fail');
  }
  
  if (!SIGNATURE_SECRET) {
    console.warn('[vonage] No SIGNATURE_SECRET configured - webhook verification disabled');
  }
  
  console.log(`[vonage] Initialized with number: ${VONAGE_NUMBER || 'not set'}`);
  return true;
}

/**
 * Send an SMS via Vonage Messages API
 */
export async function sendSms(to: string, text: string, from?: string): Promise<SendSmsResult> {
  const fromNumber = from || VONAGE_NUMBER;
  
  if (!fromNumber) {
    throw new Error('No from number specified and VONAGE_NUMBER not configured');
  }

  // Normalize phone numbers - remove + prefix for Vonage
  const toNormalized = to.replace(/^\+/, '');
  const fromNormalized = fromNumber.replace(/^\+/, '');

  console.log(`[vonage] Sending SMS to ${toNormalized} from ${fromNormalized}`);

  // Create Basic auth header
  const auth = Buffer.from(`${API_KEY}:${API_SECRET}`).toString('base64');

  const response = await fetch(VONAGE_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Basic ${auth}`,
    },
    body: JSON.stringify({
      message_type: 'text',
      channel: 'sms',
      from: fromNormalized,
      to: toNormalized,
      text: text,
    }),
  });

  const responseText = await response.text();
  
  if (!response.ok) {
    console.error(`[vonage] Send failed: ${response.status} - ${responseText}`);
    throw new Error(`Vonage API error: ${response.status} - ${responseText}`);
  }

  const result = JSON.parse(responseText) as { message_uuid: string };
  console.log(`[vonage] SMS queued with ID: ${result.message_uuid}`);

  return {
    messageId: result.message_uuid,
    status: 'queued',
  };
}

/**
 * Verify Vonage webhook signature
 * Uses HMAC-SHA256 signature verification
 * 
 * @param body - The raw request body as a string
 * @param signature - The signature from X-Vonage-Signature header
 * @param timestamp - The timestamp from request
 * @returns true if signature is valid
 */
export function verifyWebhookSignature(
  body: string,
  signature: string | undefined,
  _timestamp?: string
): boolean {
  if (!SIGNATURE_SECRET) {
    // If no secret configured, skip verification (dev mode)
    console.warn('[vonage] Skipping signature verification - no secret configured');
    return true;
  }

  if (!signature) {
    console.warn('[vonage] No signature provided in webhook');
    return false;
  }

  try {
    // Vonage uses HMAC-SHA256 for webhook signatures
    const expectedSignature = crypto
      .createHmac('sha256', SIGNATURE_SECRET)
      .update(body)
      .digest('hex');

    const isValid = crypto.timingSafeEqual(
      Buffer.from(signature),
      Buffer.from(expectedSignature)
    );

    if (!isValid) {
      console.warn('[vonage] Invalid webhook signature');
    }

    return isValid;
  } catch (err) {
    console.error('[vonage] Signature verification error:', err);
    return false;
  }
}

/**
 * Parse Vonage inbound message from webhook body
 * Handles both old SMS API and new Messages API formats
 */
export function parseInboundMessage(body: Record<string, unknown>): {
  messageId: string;
  from: string;
  to: string;
  text: string;
  timestamp: string;
} | null {
  // Messages API format (preferred for toll-free)
  if (body.message_uuid) {
    const fromObj = body.from as { number?: string } | string | undefined;
    const toObj = body.to as { number?: string } | string | undefined;
    
    const fromNumber = typeof fromObj === 'string' 
      ? fromObj 
      : (fromObj?.number || '');
    const toNumber = typeof toObj === 'string'
      ? toObj
      : (toObj?.number || '');

    return {
      messageId: body.message_uuid as string,
      from: fromNumber.startsWith('+') ? fromNumber : `+${fromNumber}`,
      to: toNumber.startsWith('+') ? toNumber : `+${toNumber}`,
      text: (body.text as string) || '',
      timestamp: (body.timestamp as string) || new Date().toISOString(),
    };
  }

  // Legacy SMS API format (msisdn based)
  if (body.msisdn) {
    return {
      messageId: (body.messageId as string) || crypto.randomUUID(),
      from: `+${body.msisdn}`,
      to: body.to ? `+${body.to}` : '',
      text: (body.text as string) || '',
      timestamp: body.timestamp 
        ? new Date(body.timestamp as string).toISOString() 
        : new Date().toISOString(),
    };
  }

  console.warn('[vonage] Unknown message format:', JSON.stringify(body));
  return null;
}

/**
 * Parse Vonage status callback
 */
export function parseStatusCallback(body: Record<string, unknown>): {
  messageId: string;
  status: string;
  errorCode?: string;
  errorReason?: string;
  timestamp: string;
} | null {
  if (!body.message_uuid || !body.status) {
    console.warn('[vonage] Invalid status callback:', JSON.stringify(body));
    return null;
  }

  const error = body.error as { code?: string; reason?: string } | undefined;

  return {
    messageId: body.message_uuid as string,
    status: body.status as string,
    errorCode: error?.code,
    errorReason: error?.reason,
    timestamp: (body.timestamp as string) || new Date().toISOString(),
  };
}

/**
 * Get configured Vonage number
 */
export function getVonageNumber(): string {
  return VONAGE_NUMBER;
}
