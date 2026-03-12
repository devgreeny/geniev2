import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Load .env from project root
const envPath = path.join(__dirname, '..', '..', '.env');
console.log(`[gateway] Loading env from: ${envPath}`);
dotenv.config({ path: envPath });
import express from 'express';
import { initDb } from './services/db.js';
import { initTelegram } from './services/telegram.js';
import { initVonage } from './services/vonage.js';
import telegramRouter from './routes/telegram.js';
import dashboardRouter from './routes/dashboard.js';
import vonageRouter from './routes/vonage.js';

const app = express();
const PORT = process.env.PORT ?? 3000;

app.use(express.urlencoded({ extended: false }));
app.use(express.json());

// CORS for dashboard
app.use((_req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  if (_req.method === 'OPTIONS') {
    res.sendStatus(200);
    return;
  }
  next();
});

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'genie2-gateway' });
});

app.use('/telegram', telegramRouter);
app.use('/vonage', vonageRouter);
app.use('/api', dashboardRouter);

function start(): void {
  try {
    initDb();
    console.log('[gateway] Database initialized');
  } catch (err) {
    console.warn('[gateway] Database init skipped:', err);
  }

  initTelegram();
  initVonage();
  
  app.listen(PORT, () => {
    console.log(`[gateway] Gateway running on port ${PORT}`);
    console.log(`[gateway] AgentField URL: ${process.env.AGENTFIELD_URL ?? 'http://localhost:8080'}`);
  });
}

start();
