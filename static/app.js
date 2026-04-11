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
  laneAttempts: {
    direct: 1,
    trs: 1,
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
    : "(Waiting for the full response...)";
  laneNode.answer.textContent = answerPlaceholder;
  laneNode.reasoning.textContent = state.activeModel?.showsReasoningTrace
    ? retry
      ? "(Retrying. The reasoning trace will restart if the model returns one.)"
      : "(Waiting for the reasoning trace...)"
    : "(This model does not return a separate reasoning trace.)";
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
    metricRow("Output tokens", formatMaybeNumber(result.completion_tokens), "accent"),
    metricRow("Total tokens", formatMaybeNumber(result.total_tokens)),
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
  seedLanePlaceholders("direct");
  seedLanePlaceholders("trs");
}

function updateRunStatus() {
  const doneCount = Object.values(state.streamProgress).filter(Boolean).length;
  if (!state.running) {
    return;
  }
  const retrying = Object.entries(state.laneAttempts)
    .filter(([lane, attempt]) => attempt > 1 && !state.streamProgress[lane])
    .map(([lane, attempt]) => `${lane === "direct" ? "Direct" : "TRS"} attempt ${attempt}`);
  if (retrying.length) {
    nodes.runStatus.textContent = `Retrying ${retrying.join(" and ")} after a transient upstream error.`;
    return;
  }
  if (doneCount === 0) {
    nodes.runStatus.textContent = "Streaming both runs. Reasoning and full responses will appear as chunks arrive.";
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
      ? "(The API did not return a separate reasoning trace.)"
      : "(This model does not return a separate reasoning trace.)");
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

function handleStreamEvent(eventName, payload) {
  switch (eventName) {
    case "meta":
      state.activeModel = payload.model;
      seedReasoningPlaceholders();
      updateRunStatus();
      return false;
    case "lane_status":
      return false;
    case "lane_retry":
      state.laneAttempts[payload.lane] = payload.attempt;
      const retryLaneNode = laneNodes(payload.lane);
      retryLaneNode.metrics.innerHTML = "";
      seedLanePlaceholders(payload.lane, true);
      setLaneStreaming(payload.lane, true);
      updateRunStatus();
      return false;
    case "lane_delta":
      appendLaneDelta(payload.lane, payload.kind, payload.text);
      return false;
    case "lane_result":
      state.streamProgress[payload.lane] = true;
      state.laneAttempts[payload.lane] = Math.max(state.laneAttempts[payload.lane], 1);
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
  state.laneAttempts = { direct: 1, trs: 1 };
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
