const state = {
  payload: null,
  modelId: "doubao",
  selectedFamilyId: null,
  familySelections: {},
  exampleId: null,
  running: false,
  activeModel: null,
  streamProgress: {
    direct: false,
    trs: false,
  },
  laneRecovering: {
    direct: false,
    trs: false,
  },
  laneAttempts: {
    direct: 1,
    trs: 1,
  },
  activeRunId: 0,
  streamError: null,
  streamSawLaneOutput: false,
  streamAbortController: null,
  userStopped: false,
};

const STREAM_CONNECT_MAX_RETRIES = 4;
const RUN_RESTART_MAX_RETRIES = 3;

const nodes = {
  exampleList: document.getElementById("exampleList"),
  modelCount: document.getElementById("modelCount"),
  modelGroupGrid: document.getElementById("modelGroupGrid"),
  runButton: document.getElementById("runButton"),
  stopButton: document.getElementById("stopButton"),
  topicBadge: document.getElementById("topicBadge"),
  difficultyBadge: document.getElementById("difficultyBadge"),
  questionTitle: document.getElementById("questionTitle"),
  questionSubtitle: document.getElementById("questionSubtitle"),
  questionText: document.getElementById("questionText"),
  referenceAnswer: document.getElementById("referenceAnswer"),
  currentModel: document.getElementById("currentModel"),
  verifierModel: document.getElementById("verifierModel"),
  skillCard: document.getElementById("skillCard"),
  runStatus: document.getElementById("runStatus"),
  liveSummary: document.getElementById("liveSummary"),
  directMetrics: document.getElementById("directMetrics"),
  trsMetrics: document.getElementById("trsMetrics"),
  directReasoning: document.getElementById("directReasoning"),
  trsReasoning: document.getElementById("trsReasoning"),
  directAnswer: document.getElementById("directAnswer"),
  trsAnswer: document.getElementById("trsAnswer"),
  template: document.getElementById("exampleCardTemplate"),
};

const FAMILY_ORDER = [
  "doubao",
  "gpt",
  "glm",
  "qwen",
  "claude",
  "grok",
  "gemini",
  "minimax",
  "deepseek",
  "kimi",
];

const FAMILY_META = {
  doubao: {
    label: "Doubao",
    short: "DB",
    icon: "/icon/doubao-color.svg",
  },
  gpt: {
    label: "GPT",
    short: "GPT",
    icon: "/icon/openai.svg",
  },
  glm: {
    label: "GLM",
    short: "GLM",
    icon: "/icon/zai.svg",
  },
  qwen: {
    label: "Qwen",
    short: "QW",
    icon: "/icon/qwen-color.svg",
  },
  claude: {
    label: "Claude",
    short: "CD",
    icon: "/icon/claude-color.svg",
  },
  grok: {
    label: "Grok",
    short: "GR",
    icon: "/icon/grok.svg",
  },
  gemini: {
    label: "Gemini",
    short: "GM",
    icon: "/icon/gemini-color.svg",
  },
  minimax: {
    label: "MiniMax",
    short: "MX",
    icon: "/icon/minimax-color.svg",
  },
  deepseek: {
    label: "DeepSeek",
    short: "DS",
    icon: "/icon/deepseek-color.svg",
  },
  kimi: {
    label: "Kimi",
    short: "KM",
    icon: null,
  },
};

function formatNumber(value) {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatReductionPercent(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function formatYuan(value) {
  return `¥${value.toFixed(6)}`;
}

function formatMaybeNumber(value) {
  return Number.isFinite(value) ? formatNumber(value) : "N/A";
}

function formatMaybeReductionPercent(value) {
  return Number.isFinite(value) ? formatReductionPercent(value) : "N/A";
}

function formatMaybeYuan(value) {
  return Number.isFinite(value) ? formatYuan(value) : "N/A";
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function typesetMath(targets = []) {
  if (!window.MathJax || !window.MathJax.typesetPromise) {
    return;
  }
  window.MathJax.typesetClear(targets);
  window.MathJax.typesetPromise(targets).catch(() => {});
}

function normalizeLookupValue(value) {
  return String(value || "").toLowerCase();
}

function inferFamilyId(modelId, model) {
  const family = normalizeLookupValue(model?.family);
  if (family === "doubao") {
    return "doubao";
  }
  if (family === "deepseek") {
    return "deepseek";
  }
  if (family === "minimax") {
    return "minimax";
  }
  if (family === "claude") {
    return "claude";
  }
  if (family === "grok") {
    return "grok";
  }
  if (family === "gemini") {
    return "gemini";
  }
  if (family === "qwen") {
    return "qwen";
  }
  if (family === "glm") {
    return "glm";
  }
  if (family === "kimi") {
    return "kimi";
  }
  if (family === "gpt") {
    return "gpt";
  }

  const haystack = normalizeLookupValue(
    [model?.family, modelId, model?.label, model?.apiModel, model?.company].join(" ")
  );
  if (haystack.includes("doubao")) {
    return "doubao";
  }
  if (haystack.includes("deepseek")) {
    return "deepseek";
  }
  if (haystack.includes("minimax")) {
    return "minimax";
  }
  if (haystack.includes("claude")) {
    return "claude";
  }
  if (haystack.includes("grok")) {
    return "grok";
  }
  if (haystack.includes("gemini")) {
    return "gemini";
  }
  if (haystack.includes("qwen")) {
    return "qwen";
  }
  if (haystack.includes("glm") || haystack.includes("z-ai") || haystack.includes("z.ai")) {
    return "glm";
  }
  if (haystack.includes("kimi")) {
    return "kimi";
  }
  if (haystack.includes("gpt-5") || haystack.includes("/gpt") || haystack.includes("openai")) {
    return "gpt";
  }
  return "other";
}

function groupedFamilies() {
  const groups = new Map();
  Object.entries(state.payload.models).forEach(([modelId, model]) => {
    const family = inferFamilyId(modelId, model);
    if (!groups.has(family)) {
      groups.set(family, []);
    }
    groups.get(family).push([modelId, model]);
  });

  const ordered = new Map();
  FAMILY_ORDER.forEach((family) => {
    if (groups.has(family)) {
      ordered.set(family, groups.get(family));
    }
  });

  Array.from(groups.keys())
    .filter((family) => !ordered.has(family))
    .sort((a, b) => a.localeCompare(b))
    .forEach((family) => {
      ordered.set(family, groups.get(family));
    });

  ordered.forEach((entries, family) => {
    entries.sort((a, b) => a[1].label.localeCompare(b[1].label));
    ordered.set(family, entries);
  });

  return ordered;
}

function familyMeta(familyId) {
  const id = familyId || "other";
  return FAMILY_META[id] || {
    label: id.toUpperCase(),
    short: id.slice(0, 2).toUpperCase(),
    icon: null,
  };
}

function initializeFamilySelections() {
  const models = state.payload.models;
  const activeModel = models[state.modelId] ? state.modelId : Object.keys(models)[0];
  const activeFamily = inferFamilyId(activeModel, models[activeModel]);
  state.selectedFamilyId = activeFamily;
  state.familySelections = {};

  groupedFamilies().forEach((entries, family) => {
    const defaultModel =
      family === activeFamily && entries.some(([modelId]) => modelId === activeModel)
        ? activeModel
        : entries[0][0];
    state.familySelections[family] = defaultModel;
  });

  state.modelId = activeModel;
}

function ensureFamilySelections() {
  if (!Object.keys(state.familySelections).length) {
    initializeFamilySelections();
  }

  groupedFamilies().forEach((entries, family) => {
    const current = state.familySelections[family];
    if (!entries.some(([modelId]) => modelId === current)) {
      state.familySelections[family] = entries[0][0];
    }
  });

  if (!groupedFamilies().has(state.selectedFamilyId)) {
    state.selectedFamilyId = groupedFamilies().keys().next().value || null;
  }
}

function renderFamilyIcon(meta) {
  if (meta.icon) {
    const img = document.createElement("img");
    img.className = "model-group-icon";
    img.src = meta.icon;
    img.alt = `${meta.label} icon`;
    return img;
  }

  const fallback = document.createElement("span");
  fallback.className = "model-group-fallback";
  fallback.textContent = meta.short;
  return fallback;
}

function renderModelSelector() {
  ensureFamilySelections();
  const families = groupedFamilies();
  const activeFamily = families.has(state.selectedFamilyId)
    ? state.selectedFamilyId
    : families.keys().next().value;
  state.selectedFamilyId = activeFamily;
  nodes.modelGroupGrid.innerHTML = "";
  nodes.modelCount.textContent = `${Object.keys(state.payload.models).length} models`;

  families.forEach((entries, family) => {
    const meta = familyMeta(family);
    const selectedModelId = state.familySelections[family] || entries[0][0];
    state.familySelections[family] = selectedModelId;

    const card = document.createElement("article");
    card.className = family === activeFamily ? "model-group-card active" : "model-group-card";

    const head = document.createElement("div");
    head.className = "model-group-head";

    const brand = document.createElement("div");
    brand.className = "model-group-brand";
    brand.appendChild(renderFamilyIcon(meta));

    const copy = document.createElement("div");
    copy.className = "model-group-copy";
    const title = document.createElement("strong");
    title.textContent = meta.label;
    copy.append(title);

    head.append(brand, copy);

    const label = document.createElement("label");
    label.className = "sr-only";
    label.setAttribute("for", `model-select-${family}`);
    label.textContent = `Select ${meta.label} model`;

    const select = document.createElement("select");
    select.id = `model-select-${family}`;
    select.className = "model-group-select";

    entries.forEach(([modelId, model]) => {
      const option = document.createElement("option");
      option.value = modelId;
      option.textContent = model.label;
      select.appendChild(option);
    });

    select.value = selectedModelId;
    const activateFamily = (modelId = select.value) => {
      const wasActiveFamily = state.selectedFamilyId === family;
      const wasActiveModel = state.modelId === modelId;
      state.selectedFamilyId = family;
      state.familySelections[family] = modelId;
      state.modelId = modelId;
      if (!wasActiveFamily || !wasActiveModel) {
        renderModelSelector();
        renderSelection();
        clearLiveResults();
      }
    };

    head.addEventListener("click", () => {
      activateFamily(select.value);
    });
    select.addEventListener("focus", () => {
      activateFamily(select.value);
    });
    select.addEventListener("click", () => {
      activateFamily(select.value);
    });
    select.addEventListener("change", (event) => {
      activateFamily(event.target.value);
    });

    card.append(head, label, select);
    nodes.modelGroupGrid.appendChild(card);
  });

  state.modelId = state.familySelections[activeFamily];
}

function renderExamples() {
  nodes.exampleList.innerHTML = "";
  state.payload.examples.forEach((example) => {
    const fragment = nodes.template.content.cloneNode(true);
    const button = fragment.querySelector(".example-card");
    fragment.querySelector(".example-kicker").textContent = `${example.topic.split(" -> ").slice(-1)[0]} · D${example.difficulty}`;
    fragment.querySelector(".example-title").textContent = example.title;
    if (example.id === state.exampleId) {
      button.classList.add("active");
    }
    button.addEventListener("click", () => {
      state.exampleId = example.id;
      renderExamples();
      renderSelection();
      clearLiveResults();
    });
    nodes.exampleList.appendChild(fragment);
  });
}

function selectedExample() {
  return state.payload.examples.find((example) => example.id === state.exampleId);
}

function renderSelection() {
  const example = selectedExample();
  const archived = example.archived[state.modelId];
  nodes.topicBadge.textContent = example.topic.split(" -> ").slice(-2).join(" • ");
  nodes.difficultyBadge.textContent = `Difficulty ${example.difficulty}`;
  nodes.questionTitle.textContent = example.title;
  nodes.questionSubtitle.textContent = example.subtitle;
  nodes.questionText.textContent = example.question;
  nodes.referenceAnswer.textContent = example.answer;
  nodes.currentModel.textContent = state.payload.models[state.modelId]?.label || "-";
  nodes.verifierModel.textContent = state.payload.verifier?.model || "openai/gpt-5-mini";
  nodes.skillCard.textContent = archived.trs.skill_text;
  typesetMath([nodes.questionText, nodes.referenceAnswer, nodes.skillCard]);
}

function laneNodes(lane) {
  return lane === "direct"
    ? {
        metrics: nodes.directMetrics,
        reasoning: nodes.directReasoning,
        answer: nodes.directAnswer,
      }
    : {
        metrics: nodes.trsMetrics,
        reasoning: nodes.trsReasoning,
        answer: nodes.trsAnswer,
      };
}

function setLaneStreaming(lane, enabled) {
  const laneNode = laneNodes(lane);
  const supportsReasoning = state.activeModel?.showsReasoningTrace;
  laneNode.answer.classList.toggle("streaming", enabled);
  laneNode.reasoning.classList.toggle("streaming", enabled && supportsReasoning);
}

function resetLanePanels() {
  ["direct", "trs"].forEach((lane) => {
    const laneNode = laneNodes(lane);
    laneNode.metrics.innerHTML = "";
    laneNode.reasoning.textContent = "";
    laneNode.answer.textContent = "";
    setLaneStreaming(lane, false);
  });
}

function seedLanePlaceholders(lane, retry = false) {
  const laneNode = laneNodes(lane);
  const answerPlaceholder = retry
    ? "(Retrying after a transient API error...)"
    : "(Waiting for the response...)";
  laneNode.answer.textContent = answerPlaceholder;
  laneNode.reasoning.textContent = state.activeModel?.showsReasoningTrace
    ? retry
      ? "(Retrying. The chain of thought will restart if the model returns one.)"
      : "(Waiting for the chain of thought...)"
    : "(This model does not return a separate chain of thought.)";
}

function clearLiveResults() {
  nodes.liveSummary.classList.add("hidden");
  nodes.liveSummary.innerHTML = "";
  resetLanePanels();
  nodes.runStatus.textContent = "Press run to compare direct prompting against TRS on the selected problem.";
}

function metricRow(label, value, tone = "") {
  const wrapper = document.createElement("div");
  wrapper.className = tone ? `metric ${tone}` : "metric";
  const span = document.createElement("span");
  span.textContent = label;
  const strong = document.createElement("strong");
  strong.textContent = value;
  wrapper.append(span, strong);
  return wrapper;
}

function renderLiveMetrics(container, result) {
  const correctness = result.correctness || {};
  container.innerHTML = "";
  container.append(
    metricRow("Input tokens", formatMaybeNumber(result.prompt_tokens)),
    metricRow("Output tokens (CoT + response)", formatMaybeNumber(result.completion_tokens), "accent"),
    metricRow("Cost (input + output pricing)", formatMaybeYuan(result.cost_yuan)),
    metricRow("Reference answer", correctness.reference_answer || "—", "muted"),
    metricRow("Verifier verdict", correctness.label || "Verifier Unclear", verdictTone(correctness.status))
  );
}

function verdictTone(status) {
  if (status === "correct") {
    return "success";
  }
  if (status === "incorrect") {
    return "warning";
  }
  return "muted";
}

function renderLiveSummary(summary) {
  nodes.liveSummary.classList.remove("hidden");
  nodes.liveSummary.innerHTML = "";
  const cards = [
    {
      label: "Output Tokens Saved",
      value: formatMaybeNumber(summary.completion_tokens_saved),
    },
    {
      label: "Output Reduction",
      value: formatMaybeReductionPercent(summary.completion_reduction_pct),
    },
    {
      label: "Paper-Priced Cost Saved",
      value: formatMaybeYuan(summary.cost_saved_yuan),
    },
  ];
  cards.forEach((card) => {
    const div = document.createElement("div");
    div.className = "summary-card live";
    const span = document.createElement("span");
    span.textContent = card.label;
    const strong = document.createElement("strong");
    strong.textContent = card.value;
    div.append(span, strong);
    nodes.liveSummary.appendChild(div);
  });
}

function openTracePanels() {
  document.querySelectorAll(".trace-panel").forEach((panel) => {
    panel.open = true;
  });
}

function seedReasoningPlaceholders(retry = false) {
  seedLanePlaceholders("direct", retry);
  seedLanePlaceholders("trs", retry);
}

function updateRunStatus() {
  const doneCount = Object.values(state.streamProgress).filter(Boolean).length;
  if (!state.running) {
    return;
  }
  const recovering = Object.entries(state.laneRecovering)
    .filter(([, active]) => active)
    .map(([lane]) => (lane === "direct" ? "Direct" : "TRS"));
  if (recovering.length) {
    nodes.runStatus.textContent = `${recovering.join(" and ")} stream unstable. Recovering with a standard request.`;
    return;
  }
  const retrying = Object.entries(state.laneAttempts)
    .filter(([lane, attempt]) => attempt > 1 && !state.streamProgress[lane])
    .map(([lane, attempt]) => `${lane === "direct" ? "Direct" : "TRS"} attempt ${attempt}`);
  if (retrying.length) {
    nodes.runStatus.textContent = `${retrying.join(" and ")} retrying automatically after an upstream drop.`;
    return;
  }
  if (doneCount === 0) {
    nodes.runStatus.textContent = "Streaming both runs. Chain of thought and response will appear as chunks arrive.";
    return;
  }
  if (doneCount === 1) {
    const finishedLane = state.streamProgress.direct ? "Direct" : "TRS";
    const waitingLane = state.streamProgress.direct ? "TRS" : "Direct";
    nodes.runStatus.textContent = `${finishedLane} finished. ${waitingLane} is still streaming.`;
    return;
  }
  nodes.runStatus.textContent = `${state.activeModel.label} finished. Costs use the paper's input and output token pricing.`;
}

function finalizeLaneResult(lane, result) {
  const laneNode = laneNodes(lane);
  renderLiveMetrics(laneNode.metrics, result);
  laneNode.reasoning.textContent =
    result.reasoning_text ||
    (state.activeModel?.showsReasoningTrace
      ? "(The API did not return a separate chain of thought.)"
      : "(This model does not return a separate chain of thought.)");
  laneNode.answer.textContent = result.answer_text || "(No response returned.)";
  setLaneStreaming(lane, false);
  typesetMath([laneNode.reasoning, laneNode.answer]);
}

function appendLaneDelta(lane, kind, text) {
  const laneNode = laneNodes(lane);
  if (kind === "reasoning") {
    if (laneNode.reasoning.textContent.startsWith("(")) {
      laneNode.reasoning.textContent = "";
    }
    laneNode.reasoning.textContent += text;
    return;
  }
  if (laneNode.answer.textContent.startsWith("(")) {
    laneNode.answer.textContent = "";
  }
  laneNode.answer.textContent += text;
}

function seedLaneFallback(lane) {
  const laneNode = laneNodes(lane);
  laneNode.metrics.innerHTML = "";
  laneNode.reasoning.textContent = "(Stream interrupted. Recovering the full result...)";
  laneNode.answer.textContent = "(Recovering with a standard request...)";
  setLaneStreaming(lane, false);
}

function stopAndClearRun() {
  state.activeRunId += 1;
  state.userStopped = true;
  state.streamError = null;
  state.streamSawLaneOutput = false;
  state.streamProgress = { direct: false, trs: false };
  state.laneRecovering = { direct: false, trs: false };
  state.laneAttempts = { direct: 1, trs: 1 };
  if (state.streamAbortController) {
    state.streamAbortController.abort();
  }
  state.streamAbortController = null;
  state.running = false;
  clearLiveResults();
  nodes.runStatus.textContent = "Run stopped and cleared. You can switch models or start a new run.";
  nodes.runButton.disabled = false;
  nodes.runButton.textContent = "Run Live Comparison";
  nodes.stopButton.disabled = true;
}

function handleStreamEvent(eventName, payload) {
  if (payload?.runId != null && payload.runId !== state.activeRunId) {
    return false;
  }
  if ((!state.running || state.userStopped) && eventName !== "done") {
    return false;
  }
  switch (eventName) {
    case "meta":
      state.activeModel = payload.model;
      seedReasoningPlaceholders();
      updateRunStatus();
      return false;
    case "lane_status":
      return false;
    case "lane_retry":
      state.laneRecovering[payload.lane] = false;
      state.laneAttempts[payload.lane] = payload.attempt;
      const retryLaneNode = laneNodes(payload.lane);
      retryLaneNode.metrics.innerHTML = "";
      seedLanePlaceholders(payload.lane, true);
      setLaneStreaming(payload.lane, true);
      updateRunStatus();
      return false;
    case "lane_fallback":
      state.laneRecovering[payload.lane] = true;
      seedLaneFallback(payload.lane);
      updateRunStatus();
      return false;
    case "lane_delta":
      state.streamSawLaneOutput = true;
      appendLaneDelta(payload.lane, payload.kind, payload.text);
      return false;
    case "lane_result":
      state.streamSawLaneOutput = true;
      state.laneRecovering[payload.lane] = false;
      state.streamProgress[payload.lane] = true;
      state.laneAttempts[payload.lane] = Math.max(state.laneAttempts[payload.lane], 1);
      finalizeLaneResult(payload.lane, payload.result);
      updateRunStatus();
      return false;
    case "lane_error":
      state.laneRecovering[payload.lane] = false;
      setLaneStreaming(payload.lane, false);
      return false;
    case "summary":
      renderLiveSummary(payload.summary);
      return false;
    case "error":
      state.streamError = payload.error || "Unknown stream error";
      return false;
    case "done":
      return true;
    default:
      return false;
  }
}

function consumeSSEBlock(block) {
  let eventName = "message";
  const dataLines = [];
  block.split(/\r?\n/).forEach((line) => {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.startsWith("data: ") ? line.slice(6) : line.slice(5));
    }
  });
  if (!dataLines.length) {
    return false;
  }
  return handleStreamEvent(eventName, JSON.parse(dataLines.join("\n")));
}

async function consumeEventStream(response) {
  if (!response.body) {
    throw new Error("The browser did not expose a readable response stream.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      if (consumeSSEBlock(block)) {
        return;
      }
      boundary = buffer.indexOf("\n\n");
    }
  }

  if (buffer.trim()) {
    if (consumeSSEBlock(buffer)) {
      return;
    }
  }

  throw new Error("The live stream closed before the run completed.");
}

function isRetryableStreamStatus(status) {
  return [408, 425, 429, 500, 502, 503, 504].includes(status);
}

function isRetryableStreamError(error) {
  const message = String(error?.message || "").toLowerCase();
  return (
    error instanceof TypeError ||
    message.includes("load failed") ||
    message.includes("failed to fetch") ||
    message.includes("networkerror") ||
    message.includes("network error") ||
    message.includes("stream closed before the run completed")
  );
}

async function openRunStreamResponse(signal, runId) {
  let lastError = new Error("Live stream connection failed.");

  for (let attempt = 1; attempt <= STREAM_CONNECT_MAX_RETRIES; attempt += 1) {
    try {
      if (attempt > 1) {
        nodes.runStatus.textContent = `Reconnecting live stream (${attempt}/${STREAM_CONNECT_MAX_RETRIES})...`;
      }

      const response = await fetch("/api/run_stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        cache: "no-store",
        signal,
        body: JSON.stringify({
          exampleId: state.exampleId,
          modelId: state.modelId,
          runId,
        }),
      });

      if (!response.ok) {
        let errorMessage = `Request failed with status ${response.status}`;
        try {
          const payload = await response.json();
          errorMessage = payload.error || errorMessage;
        } catch {}

        if (attempt < STREAM_CONNECT_MAX_RETRIES && isRetryableStreamStatus(response.status)) {
          lastError = new Error(errorMessage);
          await sleep(250 * attempt);
          continue;
        }
        throw new Error(errorMessage);
      }

      if (!response.body) {
        throw new Error("The browser did not expose a readable response stream.");
      }

      return response;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      if (attempt >= STREAM_CONNECT_MAX_RETRIES || !isRetryableStreamError(lastError)) {
        throw lastError;
      }
      await sleep(250 * attempt);
    }
  }

  throw lastError;
}

async function runComparison() {
  if (state.running) {
    return;
  }

  clearLiveResults();
  openTracePanels();
  const runId = state.activeRunId + 1;
  state.activeRunId = runId;
  state.running = true;
  state.userStopped = false;
  state.streamError = null;
  state.streamSawLaneOutput = false;
  state.streamProgress = { direct: false, trs: false };
  state.laneRecovering = { direct: false, trs: false };
  state.laneAttempts = { direct: 1, trs: 1 };
  state.activeModel = state.payload.models[state.modelId];
  state.streamAbortController = new AbortController();
  nodes.runButton.disabled = true;
  nodes.runButton.textContent = "Streaming...";
  nodes.stopButton.disabled = false;
  setLaneStreaming("direct", true);
  setLaneStreaming("trs", true);
  seedReasoningPlaceholders();
  updateRunStatus();

  try {
    for (let attempt = 1; attempt <= RUN_RESTART_MAX_RETRIES; attempt += 1) {
      try {
        const response = await openRunStreamResponse(state.streamAbortController.signal, runId);
        await consumeEventStream(response);
        if (state.streamError) {
          throw new Error(state.streamError);
        }
        return;
      } catch (error) {
        if (state.activeRunId !== runId) {
          return;
        }
        if (state.userStopped || error?.name === "AbortError") {
          return;
        }
        const retryable = isRetryableStreamError(error);
        const noFinishedLane = !state.streamProgress.direct && !state.streamProgress.trs;
        const noLaneOutput = !state.streamSawLaneOutput;
        if (attempt >= RUN_RESTART_MAX_RETRIES || !retryable || !noFinishedLane || !noLaneOutput) {
          throw error;
        }
        state.streamError = null;
        state.streamSawLaneOutput = false;
        state.laneAttempts = { direct: 1, trs: 1 };
        resetLanePanels();
        setLaneStreaming("direct", true);
        setLaneStreaming("trs", true);
        seedReasoningPlaceholders(true);
        nodes.runStatus.textContent = "The first stream connection dropped. Restarting automatically...";
        await sleep(350);
      }
    }
  } catch (error) {
    if (state.activeRunId !== runId) {
      return;
    }
    if (state.userStopped || error?.name === "AbortError") {
      return;
    }
    nodes.runStatus.textContent = `Live run failed: ${error.message}`;
    setLaneStreaming("direct", false);
    setLaneStreaming("trs", false);
  } finally {
    if (state.activeRunId !== runId) {
      return;
    }
    state.running = false;
    state.streamAbortController = null;
    state.userStopped = false;
    nodes.runButton.disabled = false;
    nodes.runButton.textContent = "Run Live Comparison";
    nodes.stopButton.disabled = true;
  }
}

async function boot() {
  const response = await fetch("/api/examples");
  state.payload = await response.json();
  state.exampleId = state.payload.examples[0].id;
  initializeFamilySelections();
  renderModelSelector();
  renderExamples();
  renderSelection();
  clearLiveResults();
  nodes.runButton.addEventListener("click", runComparison);
  nodes.stopButton.addEventListener("click", stopAndClearRun);
  nodes.stopButton.disabled = true;
}

boot().catch((error) => {
  nodes.runStatus.textContent = `Failed to load demo data: ${error.message}`;
});
