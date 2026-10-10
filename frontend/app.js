const state = {
  uploads: [],
  submitting: false,
  page: "overview",
  workflows: [],
  workflow: null,
  bundle: null,
  health: null,
  session: null,
  workflowId: null,
  detailRevision: 0,
  storageAvailable: true,
};

const byId = (id) => document.getElementById(id);
const node = (tag, className, text) => {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined && text !== null) item.textContent = String(text);
  return item;
};

class ApiError extends Error {
  constructor(message, status, detail = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options = {}) {
  const session = state.session;
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    const detail = payload && typeof payload === "object" ? payload.detail : payload;
    const message = typeof detail === "string" ? detail
      : typeof detail?.message === "string" ? detail.message : `Request failed (${response.status})`;
    if (response.status === 401 && state.session === session && (path === "/workflows" || path.startsWith("/workflows/") || path.startsWith("/uploads") || path === "/image-workflows")) {
      showLogin("Your tenant session has expired. Sign in again to continue.");
    }
    throw new ApiError(message, response.status, detail);
  }
  return payload;
}

function recentKey() {
  return `cube-operations.recent-workflows:${state.session?.org_id || "anonymous"}`;
}

function showNotice(message, kind = "info") {
  const notice = byId("global-notice");
  notice.textContent = message;
  notice.className = `notice${kind === "error" ? " is-error" : ""}`;
  notice.hidden = !message;
}

function setFormMessage(element, message, kind = "") {
  element.textContent = message;
  element.className = `form-message${kind ? ` is-${kind}` : ""}`;
}

function showLogin(message = "") {
  clearUploads();
  state.detailRevision += 1;
  state.session = null;
  state.workflows = [];
  state.workflow = null;
  state.bundle = null;
  state.workflowId = null;
  byId("app-shell").hidden = true;
  byId("login-screen").hidden = false;
  setFormMessage(byId("login-message"), message, message ? "error" : "");
  byId("login-form").elements.token.value = "";
  byId("login-form").elements.org_id.focus();
}

function showWorkspace(session) {
  state.session = session;
  byId("login-screen").hidden = true;
  byId("app-shell").hidden = false;
  byId("session-org").textContent = session.org_id;
  byId("create-form").elements.org_id.value = session.org_id;
  state.workflows = [];
  setPage("overview");
}

function recentIds() {
  try {
    const parsed = JSON.parse(localStorage.getItem(recentKey()) || "[]");
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : [];
  } catch {
    state.storageAvailable = false;
    return [];
  }
}

function rememberWorkflow(workflowId) {
  try {
    const ids = [workflowId, ...recentIds().filter((id) => id !== workflowId)].slice(0, 50);
    localStorage.setItem(recentKey(), JSON.stringify(ids));
    state.storageAvailable = true;
  } catch {
    state.storageAvailable = false;
  }
}

function dropWorkflow(workflowId) {
  try {
    localStorage.setItem(recentKey(), JSON.stringify(recentIds().filter((id) => id !== workflowId)));
  } catch {
    state.storageAvailable = false;
  }
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function label(value) {
  return String(value || "Unknown").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function badge(value) {
  const normalized = String(value || "unknown").toLowerCase().replaceAll("_", "-");
  const known = new Set([
    "completed", "clean", "pass", "in-progress", "pending", "uncertain", "failed", "exception",
    "fail", "blocked", "recovery-required", "needs-review", "incomplete", "skipped",
  ]);
  return node("span", `badge badge-${known.has(normalized) ? normalized : "pending"}`, label(value));
}

function setPage(page) {
  state.page = page;
  document.querySelectorAll("[data-page]").forEach((section) => {
    section.hidden = section.dataset.page !== page;
  });
  document.querySelectorAll("[data-page-target]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.pageTarget === page || (page === "detail" && button.dataset.pageTarget === "workflows"));
  });
  const names = { overview: "Overview", workflows: "Workflows", detail: "Workflow detail" };
  byId("breadcrumb-current").textContent = names[page] || "Overview";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function loadHealth() {
  const dot = byId("health-dot");
  const healthLabel = byId("health-label");
  try {
    const health = await request("/health");
    state.health = health;
    const agents = Object.entries(health.agents || {});
    const allUp = health.status === "ok" && agents.every(([, agent]) => agent.status === "ok");
    dot.className = `health-dot ${allUp ? "is-healthy" : "is-degraded"}`;
    healthLabel.textContent = allUp ? `${agents.length} stage handlers available` : "Agent connections need attention";
    healthLabel.title = agents.map(([, agent]) => agent.error).filter(Boolean).join("; ");
    renderAgentGrid();
  } catch (error) {
    state.health = null;
    dot.className = "health-dot is-down";
    healthLabel.textContent = "Orchestrator unavailable";
    healthLabel.title = error.message;
    showNotice(`Could not load system health: ${error.message}`, "error");
  }
}

function renderAgentGrid() {
  const grid = byId("agent-grid");
  const entries = Object.entries(state.health?.agents || {});
  byId("agent-count").textContent = `${entries.length} workflow stages`;
  if (!entries.length) {
    emptyState(grid, "Agent status unavailable", "The orchestrator did not return stage health.", null, null);
    return;
  }
  const cards = entries.map(([stage, agent]) => {
    const card = node("article", "agent-card");
    const head = node("div", "agent-card-title");
    head.append(node("strong", "", label(stage)));
    const connected = agent.status === "ok";
    const inProcess = agent.mode === "inproc";
    const status = node("span", `agent-card-status${connected ? "" : agent.status === "degraded" ? " is-degraded" : " is-down"}`,
      inProcess && connected ? "Handler loaded" : label(agent.status));
    head.append(status);
    card.append(
      head,
      node("p", "agent-card-id", agent.agent_id || agent.version || "Agent identity unavailable"),
      node("p", "agent-card-mode", inProcess ? "In-process · configuration is server-managed" : "HTTP service"),
    );
    if (agent.error) card.title = agent.error;
    return card;
  });
  grid.replaceChildren(...cards);
}

async function loadRecentWorkflows() {
  if (!state.session) return;
  const session = state.session;
  const ids = recentIds();
  const results = await Promise.all(ids.map(async (id) => {
    try {
      return await request(`/workflows/${encodeURIComponent(id)}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        if (state.session === session) dropWorkflow(id);
        return null;
      }
      throw error;
    }
  }));
  if (state.session !== session) return;
  state.workflows = results.filter(Boolean);
  renderWorkflowTables();
  renderMetrics();
  if (!state.storageAvailable) {
    showNotice("Browser storage is unavailable. Recent workflows will not persist after this page is closed.");
  } else if (state.health?.status === "ok") {
    showNotice("");
  }
}

function renderMetrics() {
  const workflows = state.workflows;
  byId("metric-total").textContent = workflows.length;
  byId("metric-active").textContent = workflows.filter((workflow) => ["PENDING", "IN_PROGRESS"].includes(workflow.status)).length;
  byId("metric-attention").textContent = workflows.filter((workflow) => ["FAILED", "BLOCKED", "RECOVERY_REQUIRED"].includes(workflow.status)).length;
  byId("metric-claims").textContent = workflows.filter((workflow) => workflow.final_outcome?.outcome === "CLAIM_RECOMMENDED").length;
}

function emptyState(container, title, description, actionText, actionTarget) {
  const stateNode = node("div", "empty-state");
  stateNode.append(node("strong", "", title), node("span", "", description));
  if (actionText) {
    const button = node("button", "button button-secondary", actionText);
    button.type = "button";
    button.dataset.pageTarget = actionTarget;
    stateNode.append(button);
  }
  container.replaceChildren(stateNode);
}

function renderWorkflowTable(container, workflows) {
  if (!workflows.length) {
    emptyState(container, "No recent workflows", "Create one or open an existing workflow by its ID.", "Start a workflow", "overview");
    return;
  }
  const wrap = node("div", "workflow-table-wrap");
  const table = node("table", "workflow-table");
  const head = node("thead");
  const headRow = node("tr");
  ["SUBJECT", "STATUS", "OUTCOME", "UPDATED", ""].forEach((title) => {
    headRow.append(node("th", "", title));
  });
  head.append(headRow);
  const body = node("tbody");
  workflows.forEach((workflow) => {
    const row = node("tr");
    const subjectCell = node("td", "subject-cell");
    subjectCell.append(node("span", "", workflow.subject_id || "—"));
    subjectCell.append(node("span", "sub-cell", workflow.org_id || "—"));
    const statusCell = node("td");
    statusCell.append(badge(workflow.status));
    const outcomeCell = node("td");
    outcomeCell.append(workflow.final_outcome ? badge(workflow.final_outcome.outcome) : node("span", "sub-cell", "Not available"));
    const updatedCell = node("td", "", formatDate(workflow.timestamps?.updated_at));
    const actionCell = node("td");
    const open = node("button", "open-link", "Open");
    open.type = "button";
    open.dataset.workflowId = workflow.workflow_id;
    actionCell.append(open);
    row.append(subjectCell, statusCell, outcomeCell, updatedCell, actionCell);
    body.append(row);
  });
  table.append(head, body);
  wrap.append(table);
  container.replaceChildren(wrap);
}

function renderWorkflowTables() {
  renderWorkflowTable(byId("overview-workflows"), state.workflows.slice(0, 6));
  applyWorkflowFilter();
}

function applyWorkflowFilter() {
  const query = byId("workflow-filter").value.trim().toLowerCase();
  const filtered = state.workflows.filter((workflow) => [
    workflow.workflow_id, workflow.subject_id, workflow.org_id, workflow.status,
    workflow.final_outcome?.outcome,
  ].some((value) => String(value || "").toLowerCase().includes(query)));
  renderWorkflowTable(byId("all-workflows"), filtered);
}

function metricText(name, value) {
  const span = node("span");
  span.append(node("strong", "", `${name}: `), document.createTextNode(value));
  return span;
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function renderCheck(check) {
  const row = node("div", "check-row");
  const title = node("div", "check-title");
  title.append(node("span", "", label(check.check_key)), badge(check.verdict));
  const detail = node("div");
  detail.append(node("p", "check-detail", check.detail || check.uncertain_reason || "No additional detail supplied."));
  const values = [];
  if (check.expected !== undefined) values.push(`Expected ${formatValue(check.expected)}`);
  if (check.observed !== undefined) values.push(`Observed ${formatValue(check.observed)}`);
  if (check.confidence !== undefined && check.confidence !== null) values.push(`Confidence ${Math.round(check.confidence * 100)}%`);
  if (check.evidence_refs?.length) values.push(`Evidence ${check.evidence_refs.join(", ")}`);
  if (values.length) detail.append(node("div", "check-values", values.join(" · ")));
  row.append(title, detail);
  return row;
}

function renderCharge(charge) {
  const item = node("article", "charge-row");
  const title = node("div", "charge-title");
  const description = node("div");
  description.append(
    node("strong", "", charge.charge_type || charge.line_id || "Charge"),
    node("span", "sub-cell", charge.line_id || "Report line"),
  );
  title.append(description, badge(charge.position || charge.outcome || "UNCERTAIN"));
  const details = [];
  if (charge.amount_usd !== undefined && charge.amount_usd !== null) {
    details.push(new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(charge.amount_usd));
  }
  if (charge.reason) details.push(charge.reason);
  if (charge.evidence_record_ids?.length) details.push(`Evidence: ${charge.evidence_record_ids.join(", ")}`);
  item.append(title);
  if (details.length) item.append(node("p", "charge-detail", details.join(" · ")));
  return item;
}

function createOverrideForm(recordId) {
  const details = node("details", "override-details");
  details.append(node("summary", "", "Record a human override"));
  const form = node("form", "override-form");
  form.dataset.recordId = recordId;
  const actor = node("label", "field");
  actor.append(node("span", "", "Actor"));
  const actorInput = node("input");
  actorInput.name = "actor";
  actorInput.value = state.session?.actor || "";
  actorInput.readOnly = true;
  actor.append(actorInput);
  const verdict = node("label", "field");
  verdict.append(node("span", "", "Effective verdict"));
  const select = node("select");
  select.name = "new_verdict";
  ["PASS", "FAIL", "UNCERTAIN"].forEach((value) => {
    const option = node("option", "", value);
    option.value = value;
    select.append(option);
  });
  verdict.append(select);
  const reason = node("label", "field field-reason");
  reason.append(node("span", "", "Reason"));
  const reasonInput = node("input");
  reasonInput.name = "reason";
  reasonInput.required = true;
  reasonInput.maxLength = 500;
  reasonInput.placeholder = "Why does the recorded decision need to change?";
  reason.append(reasonInput);
  const warning = node("p", "override-warning", "This appends an override under the tenant-token operator identity. The original evidence record is not changed.");
  const submit = node("button", "button button-secondary", "Save override");
  submit.type = "submit";
  form.append(actor, verdict, reason, warning, submit);
  details.append(form);
  return details;
}

function renderStage(stage, evidence, effectiveVerdict) {
  const card = node("article", "stage-card");
  const heading = node("div", "stage-card-head");
  const left = node("div", "stage-name");
  const name = node("div");
  name.append(node("strong", "", label(stage.stage)));
  if (stage.record_id) name.append(node("span", "stage-record", stage.record_id));
  left.append(name);
  const right = node("div");
  right.append(badge(stage.state), effectiveVerdict ? badge(effectiveVerdict) : document.createTextNode(""));
  heading.append(left, right);
  card.append(heading);

  if (stage.state === "skipped") {
    card.append(node("div", "stage-card-body", stage.skipped_reason || "This stage did not apply to the workflow."));
    return card;
  }

  const body = node("div", "stage-card-body");
  if (!stage.record_id || !evidence) {
    body.append(node("p", "record-missing", stage.error?.message || "No evidence record is available for this stage."));
    card.append(body);
    return card;
  }
  const metadata = node("div", "stage-meta");
  metadata.append(
    metricText("Agent", evidence.agent_id || stage.agent_id || "—"),
    metricText("Agent status", evidence.status || stage.evidence_status || "—"),
    metricText("Model", `${evidence.model?.name || "—"} ${evidence.model?.version || ""}`.trim()),
    metricText("Duration", stage.duration_ms === null || stage.duration_ms === undefined ? "—" : `${stage.duration_ms} ms`),
  );
  body.append(metadata);
  if (evidence.decision?.reason) body.append(node("p", "stage-reason", evidence.decision.reason));
  if (evidence.checks?.length) {
    const checks = node("div", "check-list");
    evidence.checks.forEach((check) => checks.append(renderCheck(check)));
    body.append(checks);
  } else {
    body.append(node("p", "stage-reason", "No check-level evidence was recorded for this stage."));
  }
  if (Array.isArray(evidence.payload?.charges) && evidence.payload.charges.length) {
    body.append(node("p", "eyebrow", "RECOVERY CHARGE ASSESSMENT"));
    const charges = node("div", "charge-list");
    evidence.payload.charges.forEach((charge) => charges.append(renderCharge(charge)));
    body.append(charges);
  }
  if (evidence.inputs?.length) {
    const inputTitle = node("p", "eyebrow", "CONTENT-ADDRESSED INPUTS");
    body.append(inputTitle);
    const inputs = node("ul", "input-list");
    evidence.inputs.forEach((input) => {
      const item = node("li", "", `${input.kind || "Input"} · ${input.ref || "reference unavailable"}`);
      if (input.sha256) item.append(node("code", "", `SHA-256 ${input.sha256}`));
      inputs.append(item);
    });
    body.append(inputs);
  }
  const raw = node("details", "evidence-json");
  raw.append(node("summary", "", "View complete evidence record"));
  raw.append(node("pre", "", JSON.stringify(evidence, null, 2)));
  body.append(raw, createOverrideForm(stage.record_id));
  card.append(body);
  return card;
}

function renderDetail() {
  const container = byId("workflow-detail");
  const workflow = state.workflow;
  const bundle = state.bundle;
  if (!workflow) return;

  const wrap = node("div");
  const header = node("div", "detail-head");
  const heading = node("div");
  heading.append(
    node("p", "detail-id", workflow.workflow_id),
    node("h1", "", workflow.subject_id || "Workflow"),
    node("p", "page-subtitle", `${workflow.org_id || "Organization unavailable"} · ${label(workflow.context?.route || "unknown route")}`),
  );
  const actions = node("div", "detail-head-actions");
  if (["PENDING", "IN_PROGRESS", "FAILED", "BLOCKED", "RECOVERY_REQUIRED"].includes(workflow.status)) {
    const resume = node("button", "button button-secondary", "Resume workflow");
    resume.type = "button";
    resume.id = "resume-button";
    actions.append(resume);
  }
  header.append(heading, actions);
  wrap.append(header);

  const outcome = workflow.final_outcome;
  const summary = node("section", `summary-banner${outcome ? ` outcome-${outcome.outcome}` : ""}`);
  const summaryCopy = node("div");
  const summaryTitle = node("div", "summary-title-row");
  summaryTitle.append(node("h2", "", outcome ? label(outcome.outcome) : label(workflow.status)), badge(workflow.status));
  summaryCopy.append(summaryTitle);
  summaryCopy.append(node("p", "summary-reason", outcome?.reason || workflow.status_reason || "The workflow has not produced a final outcome."));
  const summaryMeta = node("div", "summary-meta");
  summaryMeta.append(
    node("span", "", `Flow ${workflow.flow_id || "—"}`),
    node("span", "", `Created ${formatDate(workflow.timestamps?.created_at)}`),
    node("span", "", outcome?.provisional ? "Provisional outcome" : "Orchestrator-derived outcome"),
  );
  summaryCopy.append(summaryMeta);
  summary.append(summaryCopy);
  if (outcome?.claimable_usd !== null && outcome?.claimable_usd !== undefined) {
    const amount = node("div", "summary-amount");
    amount.append(node("span", "", "CLAIMABLE AMOUNT"), node("strong", "", new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(outcome.claimable_usd)));
    summary.append(amount);
  }
  wrap.append(summary);

  const columns = node("div", "detail-columns");
  const stagePanel = node("section", "panel stage-panel");
  const stageHeading = node("div", "panel-title-row");
  stageHeading.append(node("h2", "", "Stage evidence"), node("p", "", `${workflow.evidence_references?.length || 0} evidence records`));
  stagePanel.append(stageHeading);
  const stageList = node("div", "stage-list");
  (workflow.stage_results || []).forEach((stage) => {
    stageList.append(renderStage(stage, bundle?.evidence?.[stage.record_id], outcome?.effective_verdicts?.[stage.stage] || stage.verdict));
  });
  stagePanel.append(stageList);

  const contextPanel = node("section", "panel context-panel");
  const contextHeading = node("div", "panel-title-row");
  contextHeading.append(node("h2", "", "Workflow context"));
  contextPanel.append(contextHeading);
  const context = node("dl", "context-list");
  [
    ["Status", workflow.status],
    ["Current stage", workflow.current_stage ? label(workflow.current_stage) : "None"],
    ["Route", workflow.context?.route || "unknown"],
    ["Returned", workflow.context?.returned === undefined ? "Unknown" : (workflow.context.returned ? "Yes" : "No")],
    ["Evidence records", workflow.evidence_references?.length || 0],
    ["Overrides", workflow.overrides?.length || 0],
    ["Updated", formatDate(workflow.timestamps?.updated_at)],
  ].forEach(([term, value]) => {
    const item = node("div", "context-item");
    item.append(node("dt", "", term), node("dd", "", value));
    context.append(item);
  });
  const healthDetails = node("details", "audit-details");
  healthDetails.append(node("summary", "", "Agent health"));
  const healthList = node("dl", "context-list");
  Object.entries(state.health?.agents || {}).forEach(([stage, agent]) => {
    const item = node("div", "context-item");
    item.append(node("dt", "", label(stage)), node("dd", "", agent.status || "unknown"));
    healthList.append(item);
  });
  if (!Object.keys(state.health?.agents || {}).length) healthList.append(node("p", "stage-reason", "Agent health has not been loaded."));
  healthDetails.append(healthList);
  const audit = node("details", "audit-details");
  audit.append(node("summary", "", `Workflow audit trail (${workflow.transitions?.length || 0})`));
  const auditList = node("ol", "audit-list");
  (workflow.transitions || []).slice().reverse().forEach((entry) => {
    const item = node("li");
    item.append(node("time", "", formatDate(entry.at)), node("span", "", `${label(entry.event)}${entry.stage ? ` · ${label(entry.stage)}` : ""}${entry.detail ? ` · ${entry.detail}` : ""}`));
    auditList.append(item);
  });
  audit.append(auditList);
  contextPanel.append(context, healthDetails, audit);
  columns.append(stagePanel, contextPanel);
  wrap.append(columns);
  container.replaceChildren(wrap);

  const resumeButton = byId("resume-button");
  if (resumeButton) resumeButton.addEventListener("click", resumeWorkflow);
  stageList.querySelectorAll(".override-form").forEach((form) => form.addEventListener("submit", submitOverride));
}

async function openWorkflow(workflowId) {
  const id = workflowId.trim();
  if (!id) return;
  const session = state.session;
  const revision = ++state.detailRevision;
  const current = () => state.session === session && state.detailRevision === revision;
  state.workflowId = id;
  state.workflow = null;
  state.bundle = null;
  byId("workflow-detail").replaceChildren(node("div", "loading-state", "Loading workflow and evidence…"));
  setPage("detail");
  try {
    const evidenceBundle = await request(`/workflows/${encodeURIComponent(id)}/evidence`);
    if (!current()) return;
    state.bundle = evidenceBundle;
    state.workflow = evidenceBundle.workflow;
    rememberWorkflow(evidenceBundle.workflow.workflow_id);
    await loadRecentWorkflows();
    if (!current()) return;
    renderDetail();
    setFormMessage(byId("lookup-message"), "");
  } catch (error) {
    if (!current()) return;
    byId("workflow-detail").replaceChildren(node("p", "detail-error", `Could not open workflow: ${error.message}`));
    setFormMessage(byId("lookup-message"), error.message, "error");
  }
}

async function refreshWorkflow() {
  if (!state.workflowId) return false;
  const session = state.session;
  const revision = ++state.detailRevision;
  const current = () => state.session === session && state.detailRevision === revision;
  try {
    const evidenceBundle = await request(`/workflows/${encodeURIComponent(state.workflowId)}/evidence`);
    if (!current()) return false;
    state.bundle = evidenceBundle;
    state.workflow = evidenceBundle.workflow;
    rememberWorkflow(evidenceBundle.workflow.workflow_id);
    await loadRecentWorkflows();
    if (!current()) return false;
    renderDetail();
    return true;
  } catch (error) {
    if (current()) showNotice(`Could not refresh workflow: ${error.message}`, "error");
    return false;
  }
}

async function resumeWorkflow() {
  if (!state.workflowId || !window.confirm("Resume this workflow? The orchestrator may call agents again.")) return;
  const button = byId("resume-button");
  const session = state.session;
  const id = state.workflowId;
  if (button) button.disabled = true;
  try {
    await request(`/workflows/${encodeURIComponent(state.workflowId)}/resume`, { method: "POST" });
    if (state.session !== session || state.workflowId !== id) return;
    if (await refreshWorkflow()) showNotice("Workflow resumed. Its stage states and evidence have been refreshed.");
  } catch (error) {
    if (state.session === session && state.workflowId === id) showNotice(`Could not resume workflow: ${error.message}`, "error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function submitOverride(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const recordId = form.dataset.recordId;
  const session = state.session;
  const id = state.workflowId;
  if (!window.confirm("Append this override? The original evidence will remain unchanged.")) return;
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  const values = new FormData(form);
  try {
    await request(`/workflows/${encodeURIComponent(state.workflowId)}/overrides`, {
      method: "POST",
      body: JSON.stringify({
        record_id: recordId,
        new_verdict: values.get("new_verdict"),
        actor: state.session.actor,
        reason: String(values.get("reason") || "").trim(),
      }),
    });
    if (state.session !== session || state.workflowId !== id) return;
    if (await refreshWorkflow()) showNotice(`Override recorded for ${recordId}. The evidence record remains immutable.`);
  } catch (error) {
    if (state.session === session && state.workflowId === id) showNotice(`Could not record override: ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
}

function clearUploads() {
  state.uploads.forEach(item => URL.revokeObjectURL(item.url));
  state.uploads = [];
  byId("upload-list").replaceChildren();
}

function uploadError(file) {
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) return "Use JPEG, PNG or WebP images.";
  if (!file.size || file.size > 10000000) return "Each image must be nonempty and at most 10 MB.";
  return "";
}

function renderUploads() {
  const list = byId("upload-list");
  list.replaceChildren();
  state.uploads.forEach((item, index) => {
    const card = node("div", "upload-card");
    const preview = node("img", "upload-preview");
    preview.src = item.url; preview.alt = item.file.name;
    const fields = node("div", "upload-fields");
    fields.append(node("strong", "upload-name", item.file.name));
    const unitLabel = node("label", "field", "Registered unit / order subject ID");
    const unit = node("input"); unit.value = item.unit; unit.required = true; unit.maxLength = 160;
    unit.placeholder = "e.g. UNIT-0014";
    unit.addEventListener("input", () => {
      item.unit = unit.value.trim(); item.receipt = null; item.status = "Association will be revalidated";
    });
    unitLabel.append(unit);
    fields.append(unitLabel);
    if (item.needsCaptureRef) {
      const captureLabel = node("label", "field", "Existing capture reference");
      const capture = node("input"); capture.value = item.captureRef || ""; capture.maxLength = 512;
      capture.placeholder = "Reference from the trusted capture record";
      capture.addEventListener("input", () => { item.captureRef = capture.value.trim(); item.receipt = null; });
      captureLabel.append(capture, node("small", "", "The bytes match multiple captures. Supply the record reference or have the registration operator correct the bindings, then retry."));
      fields.append(captureLabel);
    }
    const remove = node("button", "text-button", "Remove image"); remove.type = "button";
    remove.addEventListener("click", () => { if (state.submitting) return; URL.revokeObjectURL(item.url); state.uploads.splice(index, 1); renderUploads(); });
    fields.append(node("small", "", item.status || "The system will resolve the evidence association"), remove);
    card.append(preview, fields); list.append(card);
  });
}

function addImages(files) {
  if (state.submitting) return;
  const errors = [];
  for (const file of files) {
    const error = uploadError(file);
    if (error) { errors.push(`${file.name}: ${error}`); continue; }
    if (state.uploads.length >= 24) { errors.push("Maximum 24 images per submission."); break; }
    const last = state.uploads.at(-1);
    state.uploads.push({file, url: URL.createObjectURL(file), unit: last?.unit || "", receipt: null});
  }
  renderUploads();
  setFormMessage(byId("create-message"), errors.join(" "), errors.length ? "error" : "");
}

byId("image-picker").addEventListener("change", event => { addImages(event.target.files); event.target.value = ""; });
byId("upload-drop").addEventListener("dragover", event => { event.preventDefault(); });
byId("upload-drop").addEventListener("drop", event => { event.preventDefault(); addImages(event.dataTransfer.files); });

async function submitImages(event) {
  event.preventDefault();
  const session = state.session;
  const form = event.currentTarget;
  if (!session || state.submitting) return;
  const message = byId("create-message");
  const values = new FormData(event.currentTarget);
  if (!state.uploads.length) { setFormMessage(message, "Add at least one image to begin.", "error"); return; }
  if (state.uploads.some(i => !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(i.unit)) || !values.get("route") || values.get("returned") === "") {
    setFormMessage(message, "Confirm each registered subject, fulfilment route and return status. Evidence associations are resolved automatically.", "error"); return;
  }
  state.submitting = true;
  const items = [...state.uploads];
  const created = [];
  form.querySelectorAll("input, select, button").forEach(el => { el.disabled = true; });
  try {
    for (const [index, item] of items.entries()) {
      setFormMessage(message, `Uploading and validating image ${index + 1} of ${items.length}…`);
      try {
        const captureQuery = item.captureRef ? `&capture_ref=${encodeURIComponent(item.captureRef)}` : "";
        if (!item.receipt) item.receipt = await request(`/uploads?unit_id=${encodeURIComponent(item.unit)}${captureQuery}`, {
          method: "PUT", headers: {"Content-Type": item.file.type}, body: item.file,
          signal: AbortSignal.timeout(60000),
        });
      } catch (error) {
        item.status = `Unresolved: ${error.message}`;
        if (error.detail?.required_information === "capture_ref") item.needsCaptureRef = true;
        throw error;
      }
      if (state.session !== session) return;
      item.status = "Upload successful · registered evidence accepted";
    }
    const units = [...new Set(items.map(i => i.unit))];
    for (const unit of units) {
      setFormMessage(message, `Evidence accepted. Processing ${unit} (${created.length + 1}/${units.length})…`);
      const workflow = await request("/image-workflows", {method: "POST", signal: AbortSignal.timeout(240000), body: JSON.stringify({
        unit_id: unit, route: values.get("route"), returned: values.get("returned") === "true",
        receipts: [...new Set(items.filter(i => i.unit === unit).map(i => i.receipt.receipt_id))],
      })});
      if (state.session !== session) return;
      rememberWorkflow(workflow.workflow_id); created.push(workflow.workflow_id);
    }
    clearUploads();
    setFormMessage(message, `${created.length} workflow(s) initialized. Review recorded outcomes; acceptance is not approval.`, "success");
    showNotice(`${created.length} workflow(s) available in recent history. Each subject has a separate record.`);
    await openWorkflow(created[0]);
  } catch (error) {
    if (state.session === session) {
      setFormMessage(message, `${error.message} ${created.length ? `${created.length} workflow(s) already saved in history.` : ""} Retry safely; completed submissions are not rerun.`, "error");
      renderUploads();
    }
  } finally {
    state.submitting = false;
    form.querySelectorAll("input, select, button").forEach(el => { el.disabled = false; });
  }
}
byId("create-form").addEventListener("submit", submitImages);

byId("registered-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const session = state.session;
  const button = form.querySelector("button");
  if (!session || button.disabled) return;
  const unit = new FormData(form).get("unit_id");
  button.disabled = true;
  setFormMessage(byId("registered-message"), "Processing registered evidence…");
  try {
    const wf = await request("/workflows", {method: "POST", body: JSON.stringify({org_id: session.org_id, unit_id: unit})});
    if (state.session !== session) return;
    rememberWorkflow(wf.workflow_id);
    setFormMessage(byId("registered-message"), "Workflow recorded; review its outcome.");
    await openWorkflow(wf.workflow_id);
  } catch (error) {
    if (state.session === session) setFormMessage(byId("registered-message"), error.message, "error");
  } finally { button.disabled = false; }
});

byId("lookup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = new FormData(event.currentTarget);
  const workflowId = String(values.get("workflow_id") || "").trim();
  setFormMessage(byId("lookup-message"), "Loading workflow…");
  await openWorkflow(workflowId);
});

document.addEventListener("click", (event) => {
  const pageButton = event.target.closest("[data-page-target]");
  if (pageButton) {
    setPage(pageButton.dataset.pageTarget);
    if (pageButton.dataset.pageTarget === "workflows") byId("workflow-filter").focus();
  }
  const button = event.target.closest("[data-workflow-id]");
  if (button) openWorkflow(button.dataset.workflowId);
});

byId("workflow-filter").addEventListener("input", applyWorkflowFilter);
byId("refresh-button").addEventListener("click", async () => {
  await Promise.all([loadHealth(), loadRecentWorkflows().catch((error) => showNotice(`Could not refresh workflows: ${error.message}`, "error"))]);
  if (state.page === "detail") await refreshWorkflow();
});
byId("detail-refresh-button").addEventListener("click", refreshWorkflow);

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const button = byId("login-submit");
  button.disabled = true;
  setFormMessage(byId("login-message"), "Verifying organization access…");
  try {
    await request("/auth/session", {
      method: "POST",
      body: JSON.stringify({
        org_id: values.get("org_id"),
        token: values.get("token"),
      }),
    });
    form.elements.token.value = "";
    const session = await request("/auth/session");
    if (!session.authenticated) throw new Error("The tenant session could not be established.");
    showWorkspace(session);
    setFormMessage(byId("login-message"), "");
    await Promise.all([
      loadHealth(),
      loadRecentWorkflows().catch((error) => showNotice(`Could not load recent workflows: ${error.message}`, "error")),
    ]);
  } catch (error) {
    form.elements.token.value = "";
    setFormMessage(byId("login-message"), error.message, "error");
    form.elements.token.focus();
  } finally {
    button.disabled = false;
  }
});

byId("logout-button").addEventListener("click", async () => {
  try {
    await request("/auth/session", { method: "DELETE" });
    showNotice("");
    showLogin();
  } catch (error) {
    showNotice(`Could not sign out cleanly: ${error.message}`, "error");
  }
});

async function initialize() {
  try {
    const session = await request("/auth/session");
    if (!session.authenticated) {
      showLogin();
      return;
    }
    showWorkspace(session);
    await Promise.all([
      loadHealth(),
      loadRecentWorkflows().catch((error) => showNotice(`Could not load recent workflows: ${error.message}`, "error")),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      return;
    }
    showLogin(`Could not check the current session: ${error.message}`);
  }
}

initialize();
