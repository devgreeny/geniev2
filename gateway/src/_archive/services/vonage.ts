import { Vonage } from '@vonage/server-sdk';

let vonageClient: Vonage;

const DEMO_MODE = process.env.DEMO_MODE === 'true';

export function initVonage(): void {
  if (DEMO_MODE) {
    console.log('[vonage] DEMO MODE — SMS will be logged, not sent');
    return;
  }
  
  const apiKey = process.env.VONAGE_API_KEY;
  const apiSecret = process.env.VONAGE_API_SECRET;
  
  if (!apiKey || !apiSecret) {
    throw new Error('Missing Vonage credentials');
  }
  
  vonageClient = new Vonage({
    apiKey,
    apiSecret,
  });
  
  console.log('[vonage] Initialized');
}

export async function sendSms(to: string, from: string, body: string): Promise<void> {
  if (DEMO_MODE) {
    console.log(`\n📱 SMS → ${to}\n${body}\n`);
    return;
  }

  const toNumber = to.replace(/^\+/, '');
  const fromNumber = from.replace(/^\+/, '');

  try {
    const result = await vonageClient.sms.send({
      to: toNumber,
      from: fromNumber,
      text: body,
    });
    console.log('[vonage] SMS sent:', JSON.stringify(result, null, 2));
  } catch (err: any) {
    console.error('[vonage] Send failed:', err?.message);
    if (err?.response?.messages) {
      console.error('[vonage] Error details:', JSON.stringify(err.response.messages, null, 2));
    }
    throw err;
  }
}
