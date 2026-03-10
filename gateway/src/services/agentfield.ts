// AgentField Control Plane URL
const AGENTFIELD_URL = process.env.AGENTFIELD_URL ?? 'http://localhost:8080';

export interface ExecuteInput {
  phone: string;
  message: string;
  business_id: string;
  is_owner: boolean;
}

export interface ExecuteResponse {
  response: string;
}

export async function executeAgent(
  agentId: string,
  reasoner: string,
  input: ExecuteInput
): Promise<{ output: ExecuteResponse }> {
  // Call AgentField's REST API to execute the agent
  const url = `${AGENTFIELD_URL}/api/v1/execute/${agentId}.${reasoner}`;
  
  console.log(`[agentfield] Calling ${agentId}.${reasoner} at ${url}`);
  
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ input }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    console.error(`[agentfield] Error ${response.status}: ${errorText}`);
    throw new Error(`AgentField error: ${response.status} - ${errorText}`);
  }

  const result = await response.json() as { result?: ExecuteResponse; output?: ExecuteResponse };
  console.log(`[agentfield] Response:`, JSON.stringify(result, null, 2));
  
  // AgentField returns { result: ... } not { output: ... }
  return { output: result.result ?? result.output ?? { response: '' } };
}

export async function healthCheck(): Promise<boolean> {
  try {
    const response = await fetch(`${AGENTFIELD_URL}/api/v1/health`);
    return response.ok;
  } catch {
    return false;
  }
}
