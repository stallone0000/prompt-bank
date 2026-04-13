const state = {
  payload: null,
  modelId: "doubao",
  verifierModelId: null,
  skillDatasetIds: [],
  selectedFamilyId: null,
  familySelections: {},
  exampleId: null,
  openExampleGroupId: null,
  examplePreviewCache: {},
  exampleLookupPending: false,
  exampleLookupRequestId: 0,
  exampleLookupAbortController: null,
  sourceMode: "example",
  customDraft: {
    question: "",
    answer: "",
  },
  customContext: null,
  customDirty: false,
  customLookupPending: false,
  customLookupRequestId: 0,
  customLookupAbortController: null,
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
  examplesModeButton: document.getElementById("examplesModeButton"),
  customModeButton: document.getElementById("customModeButton"),
  examplesPanel: document.getElementById("examplesPanel"),
  customPanel: document.getElementById("customPanel"),
  customQuestion: document.getElementById("customQuestion"),
  customAnswer: document.getElementById("customAnswer"),
  applyCustomButton: document.getElementById("applyCustomButton"),
  customCorpusMeta: document.getElementById("customCorpusMeta"),
  customStatus: document.getElementById("customStatus"),
  skillDatasetControls: document.getElementById("skillDatasetControls"),
  exampleList: document.getElementById("exampleList"),
  modelCount: document.getElementById("modelCount"),
  modelGroupGrid: document.getElementById("modelGroupGrid"),
  runButton: document.getElementById("runButton"),
  stopButton: document.getElementById("stopButton"),
  topicBadge: document.getElementById("topicBadge"),
  difficultyBadge: document.getElementById("difficultyBadge"),
  questionTitle: document.getElementById("questionTitle"),
  questionSubtitle: document.getElementById("questionSubtitle"),
  benchmarkHint: document.getElementById("benchmarkHint"),
  questionText: document.getElementById("questionText"),
  referenceAnswer: document.getElementById("referenceAnswer"),
  currentModel: document.getElementById("currentModel"),
  verifierModel: document.getElementById("verifierModel"),
  skillCardSource: document.getElementById("skillCardSource"),
  skillCard: document.getElementById("skillCard"),
  runStatus: document.getElementById("runStatus"),
  liveSummary: document.getElementById("liveSummary"),
  directMetrics: document.getElementById("directMetrics"),
  trsMetrics: document.getElementById("trsMetrics"),
  directReasoning: document.getElementById("directReasoning"),
  trsReasoning: document.getElementById("trsReasoning"),
  directAnswer: document.getElementById("directAnswer"),
  trsAnswer: document.getElementById("trsAnswer"),
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
    icon: "/icon/kimi.svg",
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

function verifierOptions() {
  return state.payload?.verifier?.options || [];
}

function skillDatasetOptions() {
  return state.payload?.skillDatasets?.options || [];
}

function datasetSelectionKey(datasetIds = state.skillDatasetIds) {
  return [...datasetIds].sort().join(",");
}

function selectedSkillDatasets() {
  const selected = new Set(state.skillDatasetIds);
  return skillDatasetOptions().filter((option) => selected.has(option.id));
}

function availableSkillDatasetIds() {
  return skillDatasetOptions().map((option) => option.id);
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

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatHintKeywords(line) {
  const pattern = /\b(hints?)\b/gi;
  let cursor = 0;
  let html = "";
  let match;
  while ((match = pattern.exec(line))) {
    html += escapeHtml(line.slice(cursor, match.index));
    html += `<strong class="trace-hint-keyword">${escapeHtml(match[0])}</strong>`;
    cursor = match.index + match[0].length;
  }
  html += escapeHtml(line.slice(cursor));
  return html;
}

function renderTraceHtml(text, highlightHints = false) {
  return String(text || "")
    .split("\n")
    .map((line) => {
      if (highlightHints && /\bhints?\b/i.test(line)) {
        return formatHintKeywords(line);
      }
      return escapeHtml(line);
    })
    .join("\n");
}

function setTraceContent(node, text, { highlightHints = false } = {}) {
  const rawText = String(text || "");
  node.dataset.rawText = rawText;
  node.innerHTML = renderTraceHtml(rawText, highlightHints);
}

function appendTraceContent(node, text, { highlightHints = false } = {}) {
  const nextText = `${node.dataset.rawText || ""}${text}`;
  setTraceContent(node, nextText, { highlightHints });
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

function initializeVerifierSelection() {
  const options = verifierOptions();
  if (!options.length) {
    state.verifierModelId = null;
    return;
  }
  const configured = state.payload?.verifier?.defaultId;
  state.verifierModelId = options.some((option) => option.id === configured)
    ? configured
    : options[0].id;
}

function renderVerifierSelector() {
  const options = verifierOptions();
  nodes.verifierModel.innerHTML = "";
  options.forEach((option) => {
    const element = document.createElement("option");
    element.value = option.id;
    element.textContent = option.label;
    nodes.verifierModel.appendChild(element);
  });

  if (!options.length) {
    nodes.verifierModel.disabled = true;
    return;
  }

  if (!options.some((option) => option.id === state.verifierModelId)) {
    state.verifierModelId = options[0].id;
  }
  nodes.verifierModel.disabled = false;
  nodes.verifierModel.value = state.verifierModelId;
}

function initializeSkillDatasetSelection() {
  const options = skillDatasetOptions();
  const defaults = state.payload?.skillDatasets?.defaultSelectedIds || [];
  const available = new Set(options.map((option) => option.id));
  const selected = defaults.filter((id) => available.has(id));
  state.skillDatasetIds = selected.length ? selected : options.slice(0, 1).map((option) => option.id);
}

function updateSkillDatasetMeta() {
  const selected = selectedSkillDatasets();
  if (!selected.length) {
    nodes.customCorpusMeta.textContent = "Select at least one skill dataset.";
    return;
  }

  const totalDocCount = selected.reduce((sum, option) => sum + (option.docCount || 0), 0);
  const label = selected.map((option) => option.label).join(" + ");
  nodes.customCorpusMeta.textContent = `Live retrieval over ${formatNumber(totalDocCount)} skill cards from ${label}.`;
}

function renderSkillDatasetControls() {
  nodes.skillDatasetControls.innerHTML = "";
  const selected = new Set(state.skillDatasetIds);
  skillDatasetOptions().forEach((option) => {
    const label = document.createElement("label");
    label.className = selected.has(option.id) ? "dataset-toggle active" : "dataset-toggle";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = selected.has(option.id);
    input.addEventListener("change", async (event) => {
      const next = new Set(state.skillDatasetIds);
      if (event.target.checked) {
        next.add(option.id);
      } else {
        if (next.size === 1) {
          event.target.checked = true;
          renderSkillDatasetControls();
          return;
        }
        next.delete(option.id);
      }
      state.skillDatasetIds = skillDatasetOptions()
        .map((dataset) => dataset.id)
        .filter((datasetId) => next.has(datasetId));
      renderSkillDatasetControls();
      updateSkillDatasetMeta();
      clearLiveResults();
      try {
        if (state.sourceMode === "custom") {
          if (!state.customDirty && state.customDraft.question.trim() && state.customDraft.answer.trim()) {
            await prepareCustomProblem({ clearResults: false, force: true });
          } else {
            renderSelection();
          }
        } else {
          await prepareExamplePreview({ clearResults: false, force: true });
        }
      } catch (error) {
        nodes.runStatus.textContent = error instanceof Error ? error.message : String(error);
      }
    });

    const mark = document.createElement("span");
    mark.className = "dataset-toggle-mark";
    mark.textContent = "✓";

    const text = document.createElement("span");
    text.textContent = option.label;

    label.append(input, mark, text);
    nodes.skillDatasetControls.appendChild(label);
  });
}

function selectedExample() {
  return state.payload.examples.find((example) => example.id === state.exampleId);
}

function examplePreviewCacheKey(exampleId = state.exampleId, datasetIds = state.skillDatasetIds) {
  return `${exampleId}@@${datasetSelectionKey(datasetIds)}`;
}

function currentExamplePreview() {
  return state.examplePreviewCache[examplePreviewCacheKey()] || null;
}

function exampleGroupId(group) {
  return group.id || group.label;
}

function groupSelectedOption(group) {
  return group.options.find((option) => option.id === state.exampleId) || group.options[0] || null;
}

function cancelExampleLookup() {
  if (state.exampleLookupAbortController) {
    state.exampleLookupAbortController.abort();
    state.exampleLookupAbortController = null;
  }
  state.exampleLookupPending = false;
}

function renderSourcePanels() {
  const customActive = state.sourceMode === "custom";
  nodes.examplesModeButton.classList.toggle("active", !customActive);
  nodes.customModeButton.classList.toggle("active", customActive);
  nodes.examplesPanel.classList.toggle("hidden", customActive);
  nodes.customPanel.classList.toggle("hidden", !customActive);
}

function buildExamplePendingContext() {
  const example = selectedExample();
  if (!example) {
    return null;
  }
  return {
    ...example,
    skillText: "(Searching the selected skill datasets...)",
    retrieval: {
      datasetLabel: "",
      sourceLabel: "",
    },
  };
}

function buildCustomPlaceholderContext() {
  return {
    id: "custom-problem-placeholder",
    title: "Custom Problem",
    subtitle: state.customLookupPending
      ? "Searching the selected skill datasets..."
      : "Fill in the question and answer, then apply the problem to retrieve a matching skill card.",
    question: "Your custom question will appear here after you apply it.",
    answer: "—",
    topic: "Custom Input",
    difficulty: state.customLookupPending ? "Searching" : "Awaiting Retrieval",
    skillText: state.customLookupPending
      ? "(Searching the selected skill datasets...)"
      : "(No skill card retrieved yet.)",
  };
}

function buildPendingCustomContext() {
  const question = state.customDraft.question.trim();
  const answer = state.customDraft.answer.trim();
  return {
    id: "custom-problem-pending",
    title: "Custom Problem",
    subtitle: "Searching the selected skill datasets...",
    question: question || "Your custom question will appear here after you apply it.",
    answer: answer || "—",
    topic: "Custom Input",
    difficulty: "Searching",
    skillText: "(Searching the selected skill datasets...)",
  };
}

function currentProblemContext() {
  if (state.sourceMode === "custom") {
    if (state.customLookupPending) {
      return buildPendingCustomContext();
    }
    if (state.customContext) {
      return state.customContext;
    }
    return buildCustomPlaceholderContext();
  }
  return currentExamplePreview() || buildExamplePendingContext();
}

function describeCustomMatch(custom) {
  const retrieval = custom?.retrieval || {};
  if (retrieval.noExperience) {
    return `No matching skill card found in ${retrieval.sourceLabel || "the selected skill datasets"}. Using no experience.`;
  }
  const parts = [];
  if (retrieval.sourceLabel) {
    parts.push(`Retrieved from ${retrieval.sourceLabel}`);
  }
  if (retrieval.matchedTopic) {
    parts.push(retrieval.matchedTopic);
  }
  if (Number.isFinite(retrieval.score)) {
    parts.push(`score ${retrieval.score.toFixed(2)}`);
  }
  return parts.join(" · ") || "Retrieved skill card ready.";
}

function cancelCustomLookup() {
  if (state.customLookupAbortController) {
    state.customLookupAbortController.abort();
    state.customLookupAbortController = null;
  }
  state.customLookupPending = false;
}

function setSourceMode(mode) {
  if (mode === "example") {
    cancelCustomLookup();
  } else {
    cancelExampleLookup();
  }
  state.sourceMode = mode;
  renderSourcePanels();
  renderExamples();
  renderSelection();
}

function applyCustomSelection(custom, options = {}) {
  const { clearResults = true } = options;
  state.customContext = custom;
  state.sourceMode = "custom";
  state.customDirty = false;
  state.customLookupPending = false;
  nodes.customStatus.textContent = describeCustomMatch(custom);
  renderSourcePanels();
  renderExamples();
  renderSelection();
  if (clearResults) {
    clearLiveResults();
  }
}

async function prepareExamplePreview(options = {}) {
  const { clearResults = true } = options;
  const example = selectedExample();
  if (!example) {
    return null;
  }

  const cachedPreview = currentExamplePreview();
  if (cachedPreview) {
    state.exampleLookupPending = false;
    renderSelection();
    if (clearResults) {
      clearLiveResults();
    }
    return cachedPreview;
  }

  const requestId = state.exampleLookupRequestId + 1;
  state.exampleLookupRequestId = requestId;
  if (state.exampleLookupAbortController) {
    state.exampleLookupAbortController.abort();
  }
  const controller = new AbortController();
  state.exampleLookupAbortController = controller;
  state.exampleLookupPending = true;
  renderSelection();

  try {
    const response = await fetch("/api/retrieve_skill", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      cache: "no-store",
      signal: controller.signal,
      body: JSON.stringify({
        id: example.id,
        questionId: example.questionId || "",
        sourceMode: "example",
        title: example.title,
        subtitle: example.subtitle,
        topic: example.topic,
        difficulty: example.difficulty,
        question: example.question,
        referenceAnswer: example.answer,
        skillDatasetIds: state.skillDatasetIds,
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Failed to retrieve the skill card for this example.");
    }
    if (requestId !== state.exampleLookupRequestId) {
      return null;
    }
    state.examplePreviewCache[examplePreviewCacheKey(example.id, state.skillDatasetIds)] = payload.preview;
    renderSelection();
    if (clearResults) {
      clearLiveResults();
    }
    return currentExamplePreview();
  } catch (error) {
    if (error?.name === "AbortError") {
      return null;
    }
    nodes.runStatus.textContent = error instanceof Error ? error.message : String(error);
    throw error;
  } finally {
    if (requestId === state.exampleLookupRequestId) {
      state.exampleLookupPending = false;
      state.exampleLookupAbortController = null;
      renderSelection();
    }
  }
}

function syncCustomDraftFromInputs() {
  state.customDraft = {
    question: nodes.customQuestion.value,
    answer: nodes.customAnswer.value,
  };
}

function updateCustomApplyState() {
  const ready =
    Boolean(state.customDraft.question.trim()) &&
    Boolean(state.customDraft.answer.trim()) &&
    !state.customLookupPending;
  nodes.applyCustomButton.disabled = !ready;
}

function markCustomDirty() {
  if (state.customLookupPending) {
    cancelCustomLookup();
  }
  syncCustomDraftFromInputs();
  state.customDirty = true;
  updateCustomApplyState();
  if (state.sourceMode === "custom") {
    nodes.customStatus.textContent = "Custom draft updated. Click Apply Custom Problem to retrieve the skill card.";
  }
}

async function prepareCustomProblem(options = {}) {
  const { clearResults = true, force = false } = options;
  syncCustomDraftFromInputs();
  const question = state.customDraft.question.trim();
  const answer = state.customDraft.answer.trim();
  if (!question || !answer) {
    throw new Error("Custom mode requires both a question and a reference answer.");
  }

  const requestId = state.customLookupRequestId + 1;
  state.customLookupRequestId = requestId;
  if (state.customLookupAbortController) {
    state.customLookupAbortController.abort();
  }
  const controller = new AbortController();
  state.customLookupAbortController = controller;
  state.customLookupPending = true;
  updateCustomApplyState();
  nodes.customStatus.textContent = "Retrieving the closest TRS skill card...";
  renderSelection();

  try {
    const response = await fetch("/api/retrieve_skill", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      cache: "no-store",
      signal: controller.signal,
      body: JSON.stringify({
        id: "custom-problem",
        question,
        referenceAnswer: answer,
        sourceMode: "custom",
        skillDatasetIds: state.skillDatasetIds,
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Failed to retrieve a skill card.");
    }
    if (requestId !== state.customLookupRequestId) {
      return null;
    }
    applyCustomSelection(payload.preview, { clearResults });
    return payload.preview;
  } catch (error) {
    if (error?.name === "AbortError") {
      return null;
    }
    state.customLookupPending = false;
    updateCustomApplyState();
    nodes.customStatus.textContent = error instanceof Error ? error.message : String(error);
    renderSelection();
    throw error;
  } finally {
    if (requestId === state.customLookupRequestId) {
      state.customLookupPending = false;
      state.customLookupAbortController = null;
      updateCustomApplyState();
      renderSelection();
    }
  }
}

function renderExamples() {
  nodes.exampleList.innerHTML = "";
  (state.payload.exampleGroups || []).forEach((group) => {
    const groupId = exampleGroupId(group);
    const card = document.createElement("article");
    const active = (group.optionIds || group.options.map((option) => option.id)).includes(state.exampleId);
    const open = state.openExampleGroupId === groupId;
    card.className = "example-group-card";
    if (active) {
      card.classList.add("active");
    }
    if (open) {
      card.classList.add("open");
    }

    const header = document.createElement("div");
    header.className = "example-group-header";

    const copy = document.createElement("div");
    copy.className = "example-group-copy";

    const top = document.createElement("div");
    top.className = "example-group-topline";

    const kicker = document.createElement("span");
    kicker.className = "example-group-kicker";
    kicker.textContent = group.kind === "benchmark" ? "Benchmark" : "Curated";

    const count = document.createElement("span");
    count.className = "example-group-count";
    count.textContent = `${group.options.length} problems`;

    const title = document.createElement("strong");
    title.className = "example-group-title";
    title.textContent = group.label;

    const subtitle = document.createElement("div");
    subtitle.className = "example-group-subtitle";
    subtitle.textContent = group.subtitle || "";

    top.append(kicker, count);
    copy.append(top, title);
    if (group.subtitle) {
      copy.append(subtitle);
    }
    header.append(copy);

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "example-group-trigger";
    trigger.setAttribute("aria-expanded", open ? "true" : "false");
    trigger.addEventListener("click", () => {
      state.openExampleGroupId = open ? null : groupId;
      renderExamples();
    });

    const current = groupSelectedOption(group);
    const triggerCopy = document.createElement("span");
    triggerCopy.className = "example-group-trigger-copy";

    const triggerLabel = document.createElement("strong");
    triggerLabel.textContent = current?.label || "Select a problem";

    const triggerMeta = document.createElement("span");
    triggerMeta.textContent = active
      ? "Current selection"
      : "Open the stack";

    const chevron = document.createElement("span");
    chevron.className = "example-group-chevron";
    chevron.textContent = open ? "−" : "+";

    triggerCopy.append(triggerLabel, triggerMeta);
    trigger.append(triggerCopy, chevron);
    card.append(header, trigger);

    if (open) {
      const stack = document.createElement("div");
      stack.className = "example-option-stack";

      group.options.forEach((option, index) => {
        const optionButton = document.createElement("button");
        optionButton.type = "button";
        optionButton.className = option.id === state.exampleId ? "example-option-card active" : "example-option-card";
        optionButton.addEventListener("click", () => {
          state.exampleId = option.id;
          state.openExampleGroupId = null;
          nodes.customStatus.textContent = "Switch back to Custom Problem to search the selected skill datasets.";
          setSourceMode("example");
          clearLiveResults();
          prepareExamplePreview({ clearResults: false }).catch((error) => {
            nodes.runStatus.textContent = error instanceof Error ? error.message : String(error);
          });
        });

        const optionIndex = document.createElement("span");
        optionIndex.className = "example-option-index";
        optionIndex.textContent = String(index + 1).padStart(2, "0");

        const optionText = document.createElement("span");
        optionText.className = "example-option-text";
        optionText.textContent = option.label;

        optionButton.append(optionIndex, optionText);
        stack.appendChild(optionButton);
      });

      card.appendChild(stack);
    }

    nodes.exampleList.appendChild(card);
  });
}

function renderSelection() {
  const problem = currentProblemContext();
  if (!problem) {
    return;
  }
  const isCustom = state.sourceMode === "custom";
  const isResolvedCustom = isCustom && state.customContext && !state.customDirty;
  nodes.topicBadge.textContent = isCustom
    ? "Custom Input"
    : problem.topic.split(" -> ").slice(-2).join(" • ");
  nodes.difficultyBadge.textContent = isCustom
    ? isResolvedCustom
      ? problem.retrieval?.noExperience
        ? "No Experience"
        : "Retrieved Skill"
      : state.customLookupPending
        ? "Searching"
        : "Awaiting Retrieval"
    : Number.isFinite(Number(problem.difficulty))
      ? `Difficulty ${problem.difficulty}`
      : String(problem.difficulty || "Curated");
  nodes.questionTitle.textContent = problem.title;
  nodes.questionSubtitle.textContent = problem.subtitle;
  renderBenchmarkHint(problem);
  nodes.questionText.textContent = problem.question;
  nodes.referenceAnswer.textContent = problem.answer;
  nodes.currentModel.textContent = state.payload.models[state.modelId]?.label || "-";
  if (state.verifierModelId) {
    nodes.verifierModel.value = state.verifierModelId;
  }
  nodes.skillCard.textContent =
    problem.skillText || problem.archived?.[state.modelId]?.trs?.skill_text || "(No skill card retrieved yet.)";
  nodes.skillCardSource.textContent = problem.retrieval?.datasetLabel ? `· ${problem.retrieval.datasetLabel}` : "";
  typesetMath([nodes.questionText, nodes.referenceAnswer, nodes.skillCard]);
}

function renderBenchmarkHint(problem) {
  const stats = problem?.benchmarkDirectStats;
  if (!stats || !Number.isFinite(Number(stats.total)) || Number(stats.total) <= 0) {
    nodes.benchmarkHint.textContent = "";
    nodes.benchmarkHint.classList.add("hidden");
    return;
  }

  const correct = Math.max(0, Number(stats.correct) || 0);
  const total = Math.max(1, Number(stats.total) || 0);
  let note = "";
  if (correct === 0) {
    note = " Extremely hard. Correct answers may be unreachable, and max-length failure is possible.";
  } else if (correct >= 1 && correct <= 4) {
    note = " Hard benchmark problem. Expect long reasoning.";
  }

  nodes.benchmarkHint.innerHTML = "";
  const lead = document.createElement("strong");
  lead.textContent = `Doubao direct: ${correct}/${total}.`;
  nodes.benchmarkHint.appendChild(lead);
  if (note) {
    nodes.benchmarkHint.appendChild(document.createTextNode(note));
  }
  nodes.benchmarkHint.classList.remove("hidden");
}

function laneNodes(lane) {
  return lane === "direct"
    ? {
        metrics: nodes.directMetrics,
        reasoning: nodes.directReasoning,
        answer: nodes.directAnswer,
        highlightHints: false,
      }
    : {
        metrics: nodes.trsMetrics,
        reasoning: nodes.trsReasoning,
        answer: nodes.trsAnswer,
        highlightHints: true,
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
    setTraceContent(laneNode.reasoning, "", { highlightHints: laneNode.highlightHints });
    setTraceContent(laneNode.answer, "", { highlightHints: laneNode.highlightHints });
    setLaneStreaming(lane, false);
  });
}

function seedLanePlaceholders(lane, retry = false) {
  const laneNode = laneNodes(lane);
  const answerPlaceholder = retry
    ? "(Retrying after a transient API error...)"
    : "(Waiting for the response...)";
  setTraceContent(laneNode.answer, answerPlaceholder, { highlightHints: laneNode.highlightHints });
  setTraceContent(
    laneNode.reasoning,
    state.activeModel?.showsReasoningTrace
      ? retry
        ? "(Retrying. The chain of thought will restart if the model returns one.)"
        : "(Waiting for the chain of thought...)"
      : "(This model does not return a separate chain of thought.)",
    { highlightHints: laneNode.highlightHints }
  );
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

function summarizeTrend(value, formatter) {
  if (!Number.isFinite(value)) {
    return {
      tone: "flat",
      arrow: "→",
      text: "N/A",
    };
  }
  if (value > 0) {
    return {
      tone: "down",
      arrow: "↓",
      text: formatter(value),
    };
  }
  if (value < 0) {
    return {
      tone: "up",
      arrow: "↑",
      text: formatter(Math.abs(value)),
    };
  }
  return {
    tone: "flat",
    arrow: "→",
    text: formatter(0),
  };
}

function renderLiveMetrics(container, result) {
  const correctness = result.correctness || {};
  container.innerHTML = "";
  const rows = [
    metricRow("Input tokens", formatMaybeNumber(result.prompt_tokens)),
    metricRow("Output tokens (CoT + response)", formatMaybeNumber(result.completion_tokens), "accent"),
    metricRow("Cost (input + output pricing)", formatMaybeYuan(result.cost_yuan)),
    metricRow("Reference answer", correctness.reference_answer || "—", "muted"),
    metricRow("Verifier verdict", formatVerifierVerdict(correctness), verdictTone(correctness.status))
  ];
  if (result.stop_label) {
    rows.push(
      metricRow(
        "Stop reason",
        result.stop_warning || result.stop_label,
        result.truncated || result.possible_repetition ? "warning" : "muted"
      )
    );
  }
  container.append(...rows);
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

function formatVerifierVerdict(correctness) {
  const label = correctness.label || "Verifier Unclear";
  if (correctness.status === "correct") {
    return `✅ ${label}`;
  }
  if (correctness.status === "incorrect") {
    return `❌ ${label}`;
  }
  return `❔ ${label}`;
}

function renderLiveSummary(summary) {
  nodes.liveSummary.classList.remove("hidden");
  nodes.liveSummary.innerHTML = "";
  const cards = [
    {
      label: "Output Tokens Saved",
      trend: summarizeTrend(summary.completion_tokens_saved, formatNumber),
    },
    {
      label: "Output Reduction",
      trend: summarizeTrend(summary.completion_reduction_pct, formatReductionPercent),
    },
    {
      label: "Cost Saved",
      trend: summarizeTrend(summary.cost_reduction_pct, formatReductionPercent),
    },
  ];
  cards.forEach((card) => {
    const div = document.createElement("div");
    div.className = `summary-card live ${card.trend.tone}`;
    const span = document.createElement("span");
    span.textContent = card.label;
    const strong = document.createElement("strong");
    const arrow = document.createElement("span");
    arrow.className = "summary-arrow";
    arrow.textContent = card.trend.arrow;
    const text = document.createElement("span");
    text.textContent = card.trend.text;
    strong.append(arrow, text);
    div.append(span, strong);
    nodes.liveSummary.appendChild(div);
  });
}

function openTracePanels() {
  document.querySelectorAll(".comparison-panel .trace-panel").forEach((panel) => {
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
  if (state.activeModel?.prefersStandardRequest) {
    nodes.runStatus.textContent = `${state.activeModel.label} is running in usage-accurate mode. Waiting for the full result and token accounting.`;
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
  setTraceContent(
    laneNode.reasoning,
    result.reasoning_text ||
      (state.activeModel?.showsReasoningTrace
        ? "(The API did not return a separate chain of thought.)"
        : "(This model does not return a separate chain of thought.)"),
    { highlightHints: laneNode.highlightHints }
  );
  setTraceContent(
    laneNode.answer,
    result.answer_text || "(No response returned.)",
    { highlightHints: laneNode.highlightHints }
  );
  setLaneStreaming(lane, false);
  typesetMath([laneNode.reasoning, laneNode.answer]);
}

function appendLaneDelta(lane, kind, text) {
  const laneNode = laneNodes(lane);
  if (kind === "reasoning") {
    if ((laneNode.reasoning.dataset.rawText || "").startsWith("(")) {
      setTraceContent(laneNode.reasoning, "", { highlightHints: laneNode.highlightHints });
    }
    appendTraceContent(laneNode.reasoning, text, { highlightHints: laneNode.highlightHints });
    return;
  }
  if ((laneNode.answer.dataset.rawText || "").startsWith("(")) {
    setTraceContent(laneNode.answer, "", { highlightHints: laneNode.highlightHints });
  }
  appendTraceContent(laneNode.answer, text, { highlightHints: laneNode.highlightHints });
}

function seedLaneFallback(lane) {
  const laneNode = laneNodes(lane);
  laneNode.metrics.innerHTML = "";
  setTraceContent(laneNode.reasoning, "(Stream interrupted. Recovering the full result...)", {
    highlightHints: laneNode.highlightHints,
  });
  setTraceContent(laneNode.answer, "(Recovering with a standard request...)", {
    highlightHints: laneNode.highlightHints,
  });
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
      if (payload.mode === "custom" && state.customContext) {
        state.customContext = {
          ...state.customContext,
          subtitle: payload.questionSubtitle || state.customContext.subtitle,
          topic: payload.topic || state.customContext.topic,
          difficulty: payload.difficulty ?? state.customContext.difficulty,
          retrieval: payload.retrieval || state.customContext.retrieval,
          skillText: payload.retrievedSkill || state.customContext.skillText,
        };
        renderSelection();
      } else if (payload.mode === "example") {
        const preview = currentExamplePreview();
        if (preview) {
          state.examplePreviewCache[examplePreviewCacheKey()] = {
            ...preview,
            subtitle: payload.questionSubtitle || preview.subtitle,
            topic: payload.topic || preview.topic,
            difficulty: payload.difficulty ?? preview.difficulty,
            retrieval: payload.retrieval || preview.retrieval,
            skillText: payload.retrievedSkill || preview.skillText,
          };
          renderSelection();
        }
      }
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

function buildRunRequestBody(runId) {
  const problem = currentProblemContext();
  return {
    modelId: state.modelId,
    verifierModelId: state.verifierModelId,
    runId,
    id: problem.id,
    questionId: problem.questionId || "",
    sourceMode: state.sourceMode,
    title: problem.title,
    subtitle: problem.subtitle,
    topic: problem.topic,
    difficulty: problem.difficulty,
    question: problem.question,
    referenceAnswer: problem.answer,
    skillText: problem.skillText || "",
    skillScore: problem.skillScore || 0,
    skillDatasetIds: state.skillDatasetIds,
  };
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
        body: JSON.stringify(buildRunRequestBody(runId)),
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

  if (state.sourceMode === "custom") {
    try {
      if (state.customDirty || !state.customContext) {
        await prepareCustomProblem();
      }
    } catch (error) {
      nodes.runStatus.textContent = error instanceof Error ? error.message : String(error);
      return;
    }
  } else {
    try {
      if (!currentExamplePreview()) {
        await prepareExamplePreview({ clearResults: false });
      }
    } catch (error) {
      nodes.runStatus.textContent = error instanceof Error ? error.message : String(error);
      return;
    }
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
  state.exampleId =
    state.payload.exampleGroups?.[0]?.optionIds?.[0] || state.payload.examples?.[0]?.id || null;
  state.openExampleGroupId = null;
  state.examplePreviewCache = {
    ...(state.payload.precomputedExamplePreviews || {}),
  };
  initializeFamilySelections();
  initializeVerifierSelection();
  initializeSkillDatasetSelection();
  nodes.customQuestion.value = state.customDraft.question;
  nodes.customAnswer.value = state.customDraft.answer;
  renderSkillDatasetControls();
  updateSkillDatasetMeta();
  renderModelSelector();
  renderVerifierSelector();
  renderSourcePanels();
  renderExamples();
  renderSelection();
  clearLiveResults();
  updateCustomApplyState();
  nodes.runButton.addEventListener("click", runComparison);
  nodes.stopButton.addEventListener("click", stopAndClearRun);
  nodes.examplesModeButton.addEventListener("click", () => {
    setSourceMode("example");
    clearLiveResults();
    prepareExamplePreview({ clearResults: false }).catch((error) => {
      nodes.runStatus.textContent = error instanceof Error ? error.message : String(error);
    });
  });
  nodes.customModeButton.addEventListener("click", () => {
    setSourceMode("custom");
    nodes.customQuestion.focus();
    updateCustomApplyState();
  });
  nodes.applyCustomButton.addEventListener("click", async () => {
    try {
      await prepareCustomProblem();
    } catch (error) {
      nodes.customStatus.textContent = error instanceof Error ? error.message : String(error);
    }
  });
  nodes.customQuestion.addEventListener("input", markCustomDirty);
  nodes.customAnswer.addEventListener("input", markCustomDirty);
  nodes.verifierModel.addEventListener("change", (event) => {
    state.verifierModelId = event.target.value;
    clearLiveResults();
  });
  nodes.stopButton.disabled = true;
  await prepareExamplePreview({ clearResults: false });
}

boot().catch((error) => {
  nodes.runStatus.textContent = `Failed to load demo data: ${error.message}`;
});
