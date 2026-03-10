// Simple SMS test script - no agents, just Vonage
import { Vonage } from '@vonage/server-sdk';

const vonage = new Vonage({
  apiKey: 'eb38a17c',
  apiSecret: 'pqL$@c7b8cY5!OQ1F'
});

const FROM = '12818247889';  // Your Vonage number
const TO = '15089693919';    // Your phone

async function sendTest() {
  console.log(`\nSending SMS from ${FROM} to ${TO}...\n`);
  
  try {
    const result = await vonage.sms.send({
      to: TO,
      from: FROM,
      text: 'Test from Genie - did you get this?'
    });
    
    console.log('Vonage Response:');
    console.log(JSON.stringify(result, null, 2));
    
    const msg = result.messages[0];
    console.log(`\nStatus: ${msg.status} (0 = success)`);
    console.log(`Message ID: ${msg.messageId}`);
    console.log(`Network: ${msg.network}`);
    console.log(`Cost: $${msg.messagePrice}`);
    console.log(`Balance: $${msg.remainingBalance}`);
    
    if (msg.status !== '0') {
      console.log(`\n❌ ERROR: ${msg.errorText}`);
    } else {
      console.log(`\n✅ Vonage accepted the message`);
      console.log(`Check your phone for the SMS!`);
    }
  } catch (err) {
    console.error('Error:', err.message);
    if (err.response?.messages) {
      console.error('Details:', JSON.stringify(err.response.messages, null, 2));
    }
  }
}

sendTest();
