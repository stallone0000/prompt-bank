const state = {
  payload: null,
  modelId: "doubao",
  exampleId: null,
  running: false,
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
  archivedReduction: document.getElementById("archivedReduction"),
  archivedTokensSaved: document.getElementById("archivedTokensSaved"),
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

function formatPercent(value) {
  return `${value > 0 ? "-" : ""}${Math.abs(value).toFixed(2)}%`;
}

function formatYuan(value) {
  return `¥${value.toFixed(6)}`;
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
  nodes.archivedReduction.textContent = formatPercent(archived.summary.estimatedReasoningReductionPct);
  nodes.archivedTokensSaved.textContent = formatNumber(archived.summary.estimatedTotalTokensSaved);
  nodes.archivedSkillScore.textContent = archived.trs.skill_score.toFixed(3);
  nodes.skillCard.textContent = archived.trs.skill_text;
  typesetMath([nodes.questionText, nodes.referenceAnswer, nodes.skillCard]);
}

function clearLiveResults() {
  nodes.liveSummary.classList.add("hidden");
  nodes.liveSummary.innerHTML = "";
  nodes.directMetrics.innerHTML = "";
  nodes.trsMetrics.innerHTML = "";
  nodes.directReasoning.textContent = "";
  nodes.trsReasoning.textContent = "";
  nodes.directAnswer.textContent = "";
  nodes.trsAnswer.textContent = "";
  nodes.runStatus.textContent =
    "No live run yet. Press the button to query the model twice: once with no skill prefix, and once with the archived TRS skill card.";
}

function metricRow(label, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "metric";
  const span = document.createElement("span");
  span.textContent = label;
  const strong = document.createElement("strong");
  strong.textContent = value;
  wrapper.append(span, strong);
  return wrapper;
}

function renderLiveMetrics(container, result) {
  container.innerHTML = "";
  container.append(
    metricRow("Prompt tokens", formatNumber(result.prompt_tokens)),
    metricRow("Completion tokens", formatNumber(result.completion_tokens)),
    metricRow("Total tokens", formatNumber(result.total_tokens)),
    metricRow("Estimated CoT tokens", formatNumber(result.estimated_reasoning_tokens)),
    metricRow("Paper-priced cost", formatYuan(result.cost_yuan))
  );
}

function renderLiveSummary(summary) {
  nodes.liveSummary.classList.remove("hidden");
  nodes.liveSummary.innerHTML = "";
  const cards = [
    {
      label: "Estimated CoT Saved",
      value: formatNumber(summary.estimated_reasoning_tokens_saved),
    },
    {
      label: "Estimated CoT Reduction",
      value: formatPercent(summary.estimated_reasoning_reduction_pct),
    },
    {
      label: "Total Tokens Saved",
      value: formatNumber(summary.total_tokens_saved),
    },
    {
      label: "Paper-Priced Cost Saved",
      value: formatYuan(summary.cost_saved_yuan),
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

async function runComparison() {
  if (state.running) {
    return;
  }
  state.running = true;
  nodes.runButton.disabled = true;
  nodes.runButton.textContent = "Running...";
  nodes.runStatus.textContent = "Calling the model twice on the server: first direct, then TRS with the archived skill card.";

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exampleId: state.exampleId,
        modelId: state.modelId,
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `Request failed with status ${response.status}`);
    }

    const live = payload.live;
    nodes.runStatus.textContent = `${live.model.label} finished. Costs below use the paper pricing constants embedded in the demo.`;
    renderLiveSummary(live.summary);
    renderLiveMetrics(nodes.directMetrics, live.direct);
    renderLiveMetrics(nodes.trsMetrics, live.trs);
    nodes.directReasoning.textContent = live.direct.reasoning_text || "(No separate reasoning_content returned by the API.)";
    nodes.trsReasoning.textContent = live.trs.reasoning_text || "(No separate reasoning_content returned by the API.)";
    nodes.directAnswer.textContent = live.direct.answer_text;
    nodes.trsAnswer.textContent = live.trs.answer_text;
    typesetMath([nodes.directReasoning, nodes.trsReasoning, nodes.directAnswer, nodes.trsAnswer]);
  } catch (error) {
    nodes.runStatus.textContent = `Live run failed: ${error.message}`;
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
