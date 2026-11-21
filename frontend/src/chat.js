const baseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "");

export async function sendMessage(sessionId, message, systemPrompt) {
  if (!baseUrl) throw new Error("Set VITE_API_BASE_URL to the backend URL and rebuild the frontend.");

  let response;
  try {
    response = await fetch(`${baseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        ...(systemPrompt ? { system_prompt: systemPrompt } : {}),
      }),
    });
  } catch {
    throw new Error("Couldn’t reach the chat server. Check your connection and try again.");
  }
  if (response.status === 422) throw new Error("Enter a message between 1 and 4,000 characters.");
  if (response.status === 503) throw new Error("Chat is temporarily unavailable. Please try again in a moment.");
  if (!response.ok) throw new Error(`The chat server returned an error (${response.status}). Please try again.`);

  const data = await response.json().catch(() => null);
  const meta = data?.metadata;
  if (data?.session_id !== sessionId || typeof data.reply !== "string" || !data.reply.trim() ||
      !["LIVE_INFERENCE", "LLM_CACHE"].includes(meta?.resolution_source) ||
      typeof meta.model !== "string" ||
      ![meta.latency_ms, meta.input_tokens, meta.output_tokens].every(Number.isInteger)) {
    throw new Error("The server returned an incomplete reply. Please try again.");
  }
  return data;
}
