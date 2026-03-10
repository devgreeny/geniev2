// Telegram Bot Service
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
const TELEGRAM_API = `https://api.telegram.org/bot${BOT_TOKEN}`;

export function initTelegram(): void {
  if (!BOT_TOKEN) {
    console.log('[telegram] No bot token configured');
    return;
  }
  console.log('[telegram] Initialized');
}

export async function sendTelegramMessage(chatId: number | string, text: string): Promise<void> {
  const response = await fetch(`${TELEGRAM_API}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: chatId,
      text: text,
      parse_mode: 'Markdown',
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    console.error('[telegram] Send failed:', error);
    throw new Error(`Telegram error: ${error}`);
  }

  console.log(`[telegram] Message sent to ${chatId}`);
}

export async function setWebhook(url: string): Promise<boolean> {
  const response = await fetch(`${TELEGRAM_API}/setWebhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });

  const result = await response.json() as { ok: boolean; description?: string };
  console.log('[telegram] Webhook set:', result);
  return result.ok;
}

export async function getMe(): Promise<{ username: string } | null> {
  try {
    const response = await fetch(`${TELEGRAM_API}/getMe`);
    const result = await response.json() as { ok: boolean; result?: { username: string } };
    return result.result || null;
  } catch {
    return null;
  }
}
