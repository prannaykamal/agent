export const STEP_LABELS = {
  USER_INPUT: "Received your message",
  RETRIEVAL: "Searching memory",
  LLM_STARTED: "Thinking",
  REASONING: "Planning the next action",
  TOOL_REQUESTED: "Using a tool",
  TOOL_EXECUTED: "Tool finished",
  OBSERVATION: "Reading the tool result",
  FINAL_RESPONSE: "Writing a reply",
  HITL_REQUIRED: "Waiting for approval",
  HITL_APPROVED: "Approved",
  HITL_REJECTED: "Rejected",
  HITL_BLOCKED: "Blocked",
  QUEUED: "Starting",
};

export const HIDDEN_STEP_TYPES = new Set(["OBSERVATION"]);

export function stepTitle(step) {
  const type = String(step?.step_type || "").toUpperCase();
  const tool = String(step?.tool_name || "").trim();
  if (type === "TOOL_REQUESTED" && tool) return `Using ${tool}`;
  if (type === "TOOL_EXECUTED" && tool) return `Finished ${tool}`;
  if (type === "HITL_REQUIRED" && tool) return `Needs approval for ${tool}`;
  if (type === "LLM_STARTED") return step?.reasoning || "Thinking";
  return STEP_LABELS[type] || type.replaceAll("_", " ").toLowerCase();
}

export function stepFailed(step) {
  const blob = `${step?.tool_result || ""} ${step?.reasoning || ""}`.toLowerCase();
  return (
    String(step?.step_type || "").includes("BLOCKED") ||
    String(step?.step_type || "").includes("REJECTED") ||
    blob.includes("failed") ||
    blob.includes("error") ||
    blob.includes("blocked")
  );
}

export function visibleSteps(steps) {
  return (steps || []).filter((step) => !HIDDEN_STEP_TYPES.has(String(step?.step_type || "").toUpperCase()));
}

export function groupLoopTrace(loopTrace) {
  const groups = [];
  let current = null;
  for (const event of loopTrace || []) {
    if (String(event.step_type || "").toUpperCase() === "USER_INPUT") {
      if (current) groups.push(current);
      current = [event];
    } else if (current) {
      current.push(event);
    }
  }
  if (current) groups.push(current);
  return groups;
}

export async function readSseStream(response, onEvent) {
  if (!response.body) {
    throw new Error("Chat stream is not readable.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        if (!raw) continue;
        onEvent(JSON.parse(raw));
      }
    }
  }
}
