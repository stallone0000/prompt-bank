const state = {
  payload: null,
  modelId: "doubao",
  exampleId: null,
  running: false,
  activeModel: null,
  streamProgress: {
    direct: false,
    trs: false,
  },
  streamError: null,
};

const nodes = {
  exampleList: document.getElementById("exampleList"),
  modelToggle: document.getElementById("modelToggle"),
  runButton: document.getElementById("runButton"),
  topicBadge: document.getElementById("topicBadge"),
  difficultyBadge: document.getElementById("difficultyBadge"),
  questionTitle: document.getElementById("questionTitle"),
  questionSubtitle: document.getElementById("questionSubtitle"),
  questionText: document.getElementById("questionText"),
  referenceAnswer: document.getElementById("referenceAnswer"),
  selectionRule: document.getElementById("selectionRule"),
  tokenFields: document.getElementById("tokenFields"),
  verifierModel: document.getElementById("verifierModel"),
  archivedSkillScore: document.getElementById("archivedSkillScore"),
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

function typesetMath(targets = []) {
  if (!window.MathJax || !window.MathJax.typesetPromise) {
    return;
  }
  window.MathJax.typesetClear(targets);
  window.MathJax.typesetPromise(targets).catch(() => {});
}

function renderModels() {
  nodes.modelToggle.innerHTML = "";
  Object.entries(state.payload.models).forEach(([modelId, model]) => {
    const button = document.createElement("button");
    button.className = modelId === state.modelId ? "toggle-button active" : "toggle-button";
    button.textContent = model.label;
    button.addEventListener("click", () => {
      state.modelId = modelId;
      renderModels();
      renderSelection();
      clearLiveResults();
    });
    nodes.modelToggle.appendChild(button);
  });
}

function renderExamples() {
  nodes.exampleList.innerHTML = "";
  state.payload.examples.forEach((example) => {
    const fragment = nodes.template.content.cloneNode(true);
    const button = fragment.querySelector(".example-card");
    fragment.querySelector(".example-kicker").textContent = example.subtitle;
    fragment.querySelector(".example-title").textContent = example.title;
    fragment.querySelector(".example-highlight").textContent = example.highlight;
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
  nodes.selectionRule.textContent = state.payload.selectionRule || "Long-CoT rebuttal curation";
  nodes.tokenFields.textContent = (state.payload.tokenUsageFields || []).join(" • ");
  nodes.verifierModel.textContent = state.payload.verifier?.model || "openai/gpt-5-mini";
  nodes.archivedSkillScore.textContent = archived.trs.skill_score.toFixed(3);
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

function clearLiveResults() {
  nodes.liveSummary.classList.add("hidden");
  nodes.liveSummary.innerHTML = "";
  resetLanePanels();
  nodes.runStatus.textContent =
    "No live run yet. Press the button to query the model twice: once with no skill prefix, and once with the archived TRS skill card.";
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
    metricRow("Prompt tokens (API)", formatMaybeNumber(result.prompt_tokens)),
    metricRow("Completion tokens (API)", formatMaybeNumber(result.completion_tokens)),
    metricRow("Total tokens (API)", formatMaybeNumber(result.total_tokens)),
    metricRow(
      "Reasoning tokens field",
      Number.isFinite(result.reported_reasoning_tokens) ? formatNumber(result.reported_reasoning_tokens) : "Not returned",
      Number.isFinite(result.reported_reasoning_tokens) && result.reported_reasoning_tokens > 0 ? "" : "muted"
    ),
    metricRow("Paper-priced cost", formatMaybeYuan(result.cost_yuan)),
    metricRow("Reference answer", correctness.reference_answer || "—", "muted"),
    metricRow("Verifier model", correctness.verifier_model || "—", "muted"),
    metricRow("Verifier verdict", correctness.label || "Verifier Unclear", verdictTone(correctness.status))
  );
  if (result.reasoning_token_note) {
    container.append(metricRow("Reasoning token note", result.reasoning_token_note, "muted"));
  }
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
      label: "CoT Tokens Saved",
      value: formatMaybeNumber(summary.reasoning_tokens_saved),
    },
    {
      label: "CoT Reduction",
      value: formatMaybeReductionPercent(summary.reasoning_reduction_pct),
    },
    {
      label: "Total Tokens Saved",
      value: formatMaybeNumber(summary.total_tokens_saved),
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

function seedReasoningPlaceholders() {
  if (state.activeModel?.showsReasoningTrace) {
    if (state.activeModel?.fallbackReasoningFromContent) {
      nodes.directAnswer.textContent = "(Extracting final answer from the model output...)";
      nodes.trsAnswer.textContent = "(Extracting final answer from the model output...)";
    }
    return;
  }
  const note = "(This model does not expose a separate reasoning trace on the current 360 API route.)";
  nodes.directReasoning.textContent = note;
  nodes.trsReasoning.textContent = note;
}

function updateRunStatus() {
  const doneCount = Object.values(state.streamProgress).filter(Boolean).length;
  if (!state.running) {
    return;
  }
  if (doneCount === 0) {
    nodes.runStatus.textContent = "Streaming direct and TRS runs from the server. Reasoning and answers will appear as chunks arrive.";
    return;
  }
  if (doneCount === 1) {
    const finishedLane = state.streamProgress.direct ? "Direct" : "TRS";
    const waitingLane = state.streamProgress.direct ? "TRS" : "Direct";
    nodes.runStatus.textContent = `${finishedLane} finished. ${waitingLane} is still streaming.`;
    return;
  }
  nodes.runStatus.textContent = `${state.activeModel.label} finished. Costs below use the paper pricing constants embedded in the demo.`;
}

function finalizeLaneResult(lane, result) {
  const laneNode = laneNodes(lane);
  renderLiveMetrics(laneNode.metrics, result);
  laneNode.reasoning.textContent =
    result.reasoning_text ||
    (state.activeModel?.showsReasoningTrace
      ? "(The API did not return a separate reasoning trace.)"
      : "(This model does not expose a separate reasoning trace on the current 360 API route.)");
  laneNode.answer.textContent = result.answer_text || "(No final answer returned.)";
  setLaneStreaming(lane, false);
  typesetMath([laneNode.reasoning, laneNode.answer]);
}

function appendLaneDelta(lane, kind, text) {
  const laneNode = laneNodes(lane);
  if (kind === "reasoning") {
    if (laneNode.reasoning.textContent.startsWith("(This model does not expose")) {
      laneNode.reasoning.textContent = "";
    }
    laneNode.reasoning.textContent += text;
    return;
  }
  laneNode.answer.textContent += text;
}

function handleStreamEvent(eventName, payload) {
  switch (eventName) {
    case "meta":
      state.activeModel = payload.model;
      seedReasoningPlaceholders();
      updateRunStatus();
      return false;
    case "lane_status":
      return false;
    case "lane_delta":
      appendLaneDelta(payload.lane, payload.kind, payload.text);
      return false;
    case "lane_result":
      state.streamProgress[payload.lane] = true;
      finalizeLaneResult(payload.lane, payload.result);
      updateRunStatus();
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
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let streamComplete = false;

  while (!streamComplete) {
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
      streamComplete = consumeSSEBlock(block) || streamComplete;
      if (streamComplete) {
        await reader.cancel();
        break;
      }
      boundary = buffer.indexOf("\n\n");
    }
  }

  if (!streamComplete && buffer.trim()) {
    consumeSSEBlock(buffer);
  }
}

async function runComparison() {
  if (state.running) {
    return;
  }

  clearLiveResults();
  openTracePanels();
  state.running = true;
  state.streamError = null;
  state.streamProgress = { direct: false, trs: false };
  state.activeModel = state.payload.models[state.modelId];
  nodes.runButton.disabled = true;
  nodes.runButton.textContent = "Streaming...";
  setLaneStreaming("direct", true);
  setLaneStreaming("trs", true);
  seedReasoningPlaceholders();
  updateRunStatus();

  try {
    const response = await fetch("/api/run_stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exampleId: state.exampleId,
        modelId: state.modelId,
      }),
    });

    if (!response.ok) {
      let errorMessage = `Request failed with status ${response.status}`;
      try {
        const payload = await response.json();
        errorMessage = payload.error || errorMessage;
      } catch {}
      throw new Error(errorMessage);
    }

    await consumeEventStream(response);
    if (state.streamError) {
      throw new Error(state.streamError);
    }
  } catch (error) {
    nodes.runStatus.textContent = `Live run failed: ${error.message}`;
    setLaneStreaming("direct", false);
    setLaneStreaming("trs", false);
  } finally {
    state.running = false;
    nodes.runButton.disabled = false;
    nodes.runButton.textContent = "Run Live Comparison";
  }
}

async function boot() {
  const response = await fetch("/api/examples");
  state.payload = await response.json();
  state.exampleId = state.payload.examples[0].id;
  renderModels();
  renderExamples();
  renderSelection();
  clearLiveResults();
  nodes.runButton.addEventListener("click", runComparison);
}

boot().catch((error) => {
  nodes.runStatus.textContent = `Failed to load demo data: ${error.message}`;
});
