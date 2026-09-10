const state = {
  view: location.hash.slice(1) || 'overview',
  data: null,
  token: sessionStorage.getItem('ba-token') || '',
  lastEvent: 0,
  streaming: false,
  selectedMission: null,
};

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '—').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[character]));
const formatTime = value => value ? new Date(value).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '—';
const formatDate = value => value ? new Date(value).toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'}) : '—';
const shortId = value => value ? esc(String(value).slice(0, 8)) : '—';
const status = value => `<span class="status ${esc(value)}">${esc(String(value ?? 'unknown').replaceAll('_', ' '))}</span>`;
const empty = label => `<div class="empty"><strong>No ${esc(label)}</strong><span>The runtime has not reported any matching records.</span></div>`;

const viewMeta = {
  overview: ['System overview', 'Live operational state from the authoritative runtime.'],
  voice: ['Voice center', 'Live AssemblyAI input state, finalized commands, and runtime outcomes.'],
  perception: ['Visual perception', 'On-demand fused observations from runtime-authorized perception sources.'],
  missions: ['Mission center', 'Long-running objectives, progress, and controlled lifecycle actions.'],
  missionDetail: ['Mission detail', 'Objective, policy, task graph, agents, and correlated execution history.'],
  tasks: ['Task center', 'Verified work derived from active and historical mission graphs.'],
  schedules: ['Scheduler', 'Upcoming runtime wakeups and event-driven triggers.'],
  agents: ['Agent control center', 'Registered agents, delegated authority, work, and health.'],
  hierarchy: ['Agent hierarchy', 'The live parent-child delegation structure.'],
  actions: ['Computer activity', 'Audited actions that passed through runtime governance.'],
  world: ['World model', 'Read-only facts observed or inferred by the runtime.'],
  resources: ['Resource monitor', 'Logical ownership, queue pressure, and runtime capacity.'],
  approvals: ['Approval center', 'Sensitive actions suspended pending an independent decision.'],
  recovery: ['Recovery center', 'Failures and runtime recovery escalation activity.'],
  security: ['Security decisions', 'Policy outcomes and blocked action attempts.'],
  leases: ['Capability leases', 'Temporary task-scoped permissions issued by the runtime.'],
  activity: ['Event stream', 'Correlated runtime events in reverse chronological order.'],
  memory: ['Memory inspector', 'Redacted, bounded execution metadata from persistent memory.'],
  skills: ['Skill registry', 'Controlled reusable artifacts and their verification state.'],
  analytics: ['Autonomy scorecard', 'Metrics computed only from real terminal runtime records.'],
  inventory: ['System inventory', 'Authoritative capabilities discovered from active registries.'],
  health: ['System health', 'Availability and last-seen state for runtime components.'],
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {'Authorization': `Bearer ${state.token}`, 'Content-Type': 'application/json', ...(options.headers || {})},
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { detail = (await response.json()).error || detail; } catch (_) { /* response had no JSON body */ }
    throw new Error(detail);
  }
  return response.json();
}

function table(headers, rows, label = 'records') {
  if (!rows.length) return empty(label);
  return `<div class="table-wrap"><table><thead><tr>${headers.map(header => `<th>${esc(header)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
}

function overview() {
  const {overview: metrics, events, health} = state.data;
  const cards = Object.entries(metrics).map(([key, value], index) => `<article class="card ${index < 3 ? 'accent' : ''}"><span>${esc(key.replaceAll('_', ' ').toUpperCase())}</span><strong>${value}</strong><small>${value === 0 ? 'No current records' : 'Live runtime count'}</small></article>`).join('');
  const activity = events.slice(-9).reverse().map(event => `<div class="row"><div><b>${esc(event.event_type.replaceAll('_', ' '))}</b><br><small>${esc(event.mission_id || 'System')} · ${esc(event.payload?.command || event.payload?.error || event.status || 'Runtime event')}</small></div><time>${formatTime(event.timestamp)}</time></div>`).join('') || empty('events');
  const components = health.slice(0, 9).map(item => `<div class="row"><span>${esc(item.component.replaceAll('_', ' '))}</span>${status(item.status)}</div>`).join('');
  return `<div class="cards">${cards}</div><div class="grid"><section class="panel"><div class="panel-header"><h2>Live activity</h2><small>${events.length} retained events</small></div><div class="timeline">${activity}</div></section><section class="panel"><div class="panel-header"><h2>Component health</h2><small>Last snapshot</small></div>${components}</section></div>`;
}

function voice() {
  const voice = state.data.voice;
  const commands = voice.history || [];
  const confidence = commands.length ? commands.reduce((sum, item) => sum + Number(item.confidence || 0), 0) / commands.length : null;
  return `<div class="voice-toolbar"><button class="button" data-voice-configure>Configure AssemblyAI</button><button class="button button-primary push-to-talk" data-voice-talk ${voice.configured ? '' : 'disabled'}>Hold to talk</button><button class="button" data-command="stop_voice">Stop voice</button><small>Push-to-talk starts on press and stops on release.</small></div><div class="cards"><article class="card accent"><span>VOICE STATUS</span><strong>${esc(voice.status).toUpperCase()}</strong><small>${esc(voice.mode || 'Not configured')}</small></article><article class="card"><span>ASSEMBLYAI</span><strong>${esc(voice.connection).toUpperCase()}</strong><small>${esc(voice.model || 'No model')}</small></article><article class="card"><span>VOICE COMMANDS</span><strong>${commands.length}</strong><small>Bounded current session</small></article><article class="card"><span>AVG CONFIDENCE</span><strong>${confidence == null ? 'N/A' : Math.round(confidence * 100) + '%'}</strong><small>Finalized turns only</small></article></div><div class="grid"><section class="panel transcript-panel"><div class="panel-header"><h2>Live transcript</h2>${status(voice.status)}</div><p class="partial">${esc(voice.current_transcript || 'Waiting for speech…')}</p><p class="final">${voice.final_transcript ? '✓ ' + esc(voice.final_transcript) : 'No finalized turn'}</p><dl><dt>Session</dt><dd><code>${shortId(voice.session_id)}</code></dd><dt>Microphone</dt><dd>${esc(voice.microphone)}</dd><dt>Sample rate</dt><dd>${voice.sample_rate ? voice.sample_rate + ' Hz PCM16 mono' : '—'}</dd><dt>Active mission</dt><dd><code>${shortId(voice.active_mission)}</code></dd></dl>${voice.error ? `<p class="voice-error">${esc(voice.error)}</p>` : ''}</section><section class="panel"><h2>Privacy boundary</h2><p class="muted">Partial turns update ephemeral session state only. Final turns enter structured intent processing. Raw audio is never stored. Transcript persistence is disabled by default.</p><p class="muted">Speech confidence does not grant action authority. Every accepted mission still passes through the governor, policy, permissions, tools, observation, and verification.</p></section></div><section style="margin-top:13px">${table(['Time', 'Transcript', 'Intent', 'Mission', 'Status', 'Confidence', 'Result'], commands.slice().reverse().map(item => `<tr><td>${formatTime(item.timestamp)}</td><td>${esc(item.transcript || '[NOT STORED]')}</td><td>${status(item.intent)}</td><td><code>${shortId(item.mission_id)}</code></td><td>${status(item.status)}</td><td>${Math.round(Number(item.confidence || 0) * 100)}%</td><td>${esc(item.result)}</td></tr>`), 'voice commands')}</section>`;
}

function perception() {
  const view = state.data.perception;
  const latency = view.average_latency_ms == null ? 'N/A' : `${Math.round(view.average_latency_ms)} ms`;
  const sourceNames = (view.sources || []).map(item => item.source).join(', ') || 'No observation yet';
  const flow = ['OBSERVE', 'UNDERSTAND', 'TARGET', 'ACTION', 'OBSERVE', 'VERIFY']
    .map((step, index) => `<span>${esc(step)}</span>${index < 5 ? '<i>→</i>' : ''}`).join('');
  return `<div class="perception-toolbar"><button class="button button-primary" data-command="observe_environment">Observe now</button><small>Capture is requested through the runtime; this page has no direct screen access.</small></div><div class="cards"><article class="card accent"><span>PERCEPTION</span><strong>${esc(view.status).toUpperCase()}</strong><small>${view.observations} authorized observations</small></article><article class="card"><span>CONFIDENCE</span><strong>${view.confidence == null ? 'N/A' : Math.round(view.confidence * 100) + '%'}</strong><small>Fused source confidence</small></article><article class="card"><span>UI ELEMENTS</span><strong>${view.elements.length}</strong><small>Visible structured elements</small></article><article class="card"><span>AVG LATENCY</span><strong>${latency}</strong><small>Observed runtime measurements</small></article></div><div class="perception-flow">${flow}</div><div class="grid"><section class="panel"><div class="panel-header"><h2>Environment</h2>${status(view.status)}</div><dl class="environment-list"><dt>Application</dt><dd>${esc(view.active_application)}</dd><dt>Window</dt><dd>${esc(view.active_window)}</dd><dt>Browser URL</dt><dd>${esc(view.browser?.url)}</dd><dt>Observed</dt><dd>${formatDate(view.timestamp)}</dd><dt>Sources</dt><dd>${esc(sourceNames)}</dd><dt>Screenshot</dt><dd>${view.screenshot_available ? 'AVAILABLE' : 'UNAVAILABLE'}</dd></dl>${view.screenshot_available ? '<div class="screen-preview"><span>Loading authorized capture…</span></div>' : ''}</section><section class="panel"><h2>Trust boundary</h2><p class="muted">DOM, accessibility, OCR, screenshots, and webpage text are untrusted observation data. They cannot create commands, grant permissions, mutate policy, or execute tools.</p><p class="muted">A screenshot is shown only when an existing authorized perception source provides a safe reference. No independent dashboard capture path exists.</p></section></div><section style="margin-top:13px">${table(['Role', 'Label / text', 'Source', 'Confidence', 'Bounds', 'State'], view.elements.map(item => `<tr><td>${status(item.role)}</td><td><b>${esc(item.label || item.text)}</b></td><td>${esc(item.source)}</td><td>${Math.round(item.confidence * 100)}%</td><td><code>${esc(item.bounds ? item.bounds.join(', ') : 'semantic')}</code></td><td>${item.clickable ? 'Clickable' : item.editable ? 'Editable' : 'Read only'}</td></tr>`), 'UI elements')}</section>`;
}

function missions() {
  return table(['Mission', 'Objective', 'Status', 'Priority', 'Progress', 'Updated', 'Controls'], state.data.missions.map(mission => {
    const completed = mission.progress.tasks_completed || 0;
    const remaining = mission.progress.tasks_remaining || 0;
    const total = completed + remaining;
    const width = total ? Math.round(completed / total * 100) : 0;
    const terminal = ['completed', 'failed', 'cancelled'].includes(mission.status);
    return `<tr><td><button class="link-button" data-mission-view="${esc(mission.mission_id)}"><code>${shortId(mission.mission_id)}</code></button></td><td><button class="link-button" data-mission-view="${esc(mission.mission_id)}"><b>${esc(mission.objective)}</b></button></td><td>${status(mission.status)}</td><td>${mission.priority}</td><td>${completed} done · ${remaining} left<div class="metric-bar"><i style="width:${width}%"></i></div></td><td>${formatDate(mission.updated_at)}</td><td>${terminal ? '<span class="muted">Final</span>' : `<button data-command="${mission.status === 'paused' ? 'resume_mission' : 'pause_mission'}" data-mission="${esc(mission.mission_id)}">${mission.status === 'paused' ? 'Resume' : 'Pause'}</button> <button class="danger" data-command="cancel_mission" data-mission="${esc(mission.mission_id)}">Cancel</button>`}</td></tr>`;
  }), 'missions');
}

function missionDetail() {
  const mission = state.data.missions.find(item => item.mission_id === state.selectedMission);
  if (!mission) return empty('mission');
  const relatedAgents = state.data.agents.filter(agent => agent.mission_id === mission.mission_id);
  const relatedEvents = state.data.events.filter(event => event.mission_id === mission.mission_id);
  const governance = state.data.governance.find(item => item.mission_id === mission.mission_id);
  const taskNodes = mission.tasks.map((task, index) => `<div class="task-node"><span>${index + 1}</span><div><b>${esc(task.description)}</b><small><code>${shortId(task.task_id)}</code> · ${task.retries || 0} retries</small></div>${status(task.status)}</div>`).join('') || empty('tasks');
  return `<button class="back-button" data-back="missions">← Back to missions</button><div class="detail-hero"><div><p class="eyebrow">MISSION ${shortId(mission.mission_id)}</p><h2>${esc(mission.objective)}</h2><p>${esc(mission.owner)} · Created ${formatDate(mission.created_at)}</p></div>${status(mission.status)}</div><div class="detail-grid"><section class="panel"><div class="panel-header"><h2>Task graph</h2><small>${mission.tasks.length} nodes</small></div><div class="task-graph">${taskNodes}</div></section><section class="panel detail-list"><h2>Mission policy</h2><dl><dt>Priority</dt><dd>${mission.priority}</dd><dt>Deadline</dt><dd>${formatDate(mission.deadline)}</dd><dt>Next wakeup</dt><dd>${formatDate(mission.next_wakeup)}</dd><dt>Active agents</dt><dd>${relatedAgents.length}</dd>${governance ? `<dt>Action budget</dt><dd>${governance.actions_used} / ${governance.actions_limit}</dd><dt>Failure budget</dt><dd>${governance.failures_used} / ${governance.failures_limit}</dd><dt>Confidence floor</dt><dd>${Math.round(governance.minimum_confidence * 100)}%</dd>` : ''}</dl><h2>Allowed authority</h2>${governance ? `<p><small>TOOLS</small><br>${governance.allowed_tools.map(esc).join(', ') || 'Any contracted tool'}</p><p><small>PERMISSIONS</small><br>${governance.allowed_permissions.map(esc).join(', ') || 'Any contracted permission'}</p>` : '<p class="muted">No mission-specific governor contract</p>'}<h2>Acceptance criteria</h2>${mission.acceptance_criteria.length ? `<ul>${mission.acceptance_criteria.map(item => `<li>${esc(item)}</li>`).join('')}</ul>` : '<p class="muted">No explicit criteria recorded</p>'}<h2>Constraints</h2>${mission.constraints.length ? `<ul>${mission.constraints.map(item => `<li>${esc(item)}</li>`).join('')}</ul>` : '<p class="muted">No constraints recorded</p>'}</section></div><section class="panel" style="margin-top:13px"><div class="panel-header"><h2>Correlated execution timeline</h2><small>${relatedEvents.length} events</small></div><div class="timeline">${relatedEvents.slice().reverse().map(event => `<div class="row"><div><b>${esc(event.event_type.replaceAll('_', ' '))}</b><br><small>Task ${shortId(event.task_id)} · Agent ${shortId(event.agent_id)} · Correlation ${shortId(event.correlation_id)}</small></div><time>${formatTime(event.timestamp)}</time></div>`).join('') || empty('events')}</div></section>`;
}

function tasks() {
  return table(['Task', 'Mission', 'Description', 'Status', 'Retries', 'Verification / error'], state.data.tasks.map(task => `<tr><td><code>${shortId(task.task_id)}</code></td><td><code>${shortId(task.mission_id)}</code></td><td>${esc(task.description)}</td><td>${status(task.status)}</td><td>${task.retries || 0}</td><td>${esc(task.verification || task.error)}</td></tr>`), 'tasks');
}

function agents() {
  return table(['Agent', 'Role', 'Parent', 'Status', 'Current task', 'Permissions', 'Health'], state.data.agents.map(agent => `<tr><td><b>${esc(agent.name)}</b><br><code>${shortId(agent.agent_id)}</code></td><td>${esc(agent.role)}</td><td><code>${shortId(agent.parent_agent_id)}</code></td><td>${status(agent.status)}</td><td>${esc(agent.current_task)}</td><td>${agent.permissions.map(esc).join('<br>') || '—'}</td><td>${status(agent.health)}</td></tr>`), 'agents');
}

function activity() {
  return table(['Time', 'Event', 'Mission', 'Agent', 'Status', 'Correlation'], state.data.events.slice().reverse().map(event => `<tr><td>${formatTime(event.timestamp)}</td><td><b>${esc(event.event_type.replaceAll('_', ' '))}</b></td><td><code>${shortId(event.mission_id)}</code></td><td><code>${shortId(event.agent_id)}</code></td><td>${status(event.status || event.severity)}</td><td><code>${shortId(event.correlation_id)}</code></td></tr>`), 'events');
}

function schedules() {
  return table(['Schedule', 'Mission', 'Trigger', 'Next', 'Previous', 'Status'], state.data.schedules.map(item => `<tr><td><code>${shortId(item.schedule_id)}</code></td><td><code>${shortId(item.mission_id)}</code></td><td>${esc(item.trigger)}</td><td>${formatDate(item.next_execution)}</td><td>${formatDate(item.previous_execution)}</td><td>${status(item.enabled ? 'enabled' : 'disabled')}</td></tr>`), 'schedules');
}

function actions() {
  return table(['Time', 'Action', 'Agent', 'Tool', 'Permission', 'Policy', 'Approval', 'Result'], state.data.actions.slice().reverse().map(action => `<tr><td>${formatTime(action.timestamp)}</td><td><code>${shortId(action.action_id)}</code></td><td><code>${shortId(action.agent_id)}</code></td><td><b>${esc(action.tool)}</b></td><td>${esc(action.permission)}</td><td>${status(action.policy_decision)}</td><td>${status(action.approval_status)}</td><td>${esc(action.error || action.result)}</td></tr>`), 'computer actions');
}

function approvals() {
  return table(['Requested', 'Task', 'Agent', 'Action', 'Risk', 'Reason', 'Decision'], state.data.approvals.map(item => `<tr><td>${formatDate(item.requested_at)}</td><td><code>${shortId(item.task_id)}</code></td><td><code>${shortId(item.agent_id)}</code></td><td><b>${esc(item.tool)}</b><br><small>${esc(item.permission)}</small></td><td>${status(item.risk_level)}</td><td>${esc(item.reason)}</td><td><button data-command="approve" data-approval="${esc(item.approval_id)}">Approve</button> <button class="danger" data-command="deny" data-approval="${esc(item.approval_id)}">Deny</button></td></tr>`), 'pending approvals');
}

function resources() {
  const resource = state.data.resources;
  const cards = [['Agents', resource.agent_count], ['Tasks', resource.task_count], ['Event queue', resource.queue_depth], ['Active locks', Object.keys(resource.locks).length]].map(([label, value]) => `<article class="card"><span>${label.toUpperCase()}</span><strong>${value}</strong><small>Runtime reported</small></article>`).join('');
  return `<div class="cards">${cards}</div><div style="margin-top:13px">${table(['Logical resource', 'Current owner'], Object.entries(resource.locks).map(([name, owner]) => `<tr><td>${esc(name)}</td><td><code>${esc(owner)}</code></td></tr>`), 'active resource locks')}</div>`;
}

function hierarchy() {
  const children = id => `<ul>${state.data.agents.filter(agent => agent.parent_agent_id === id).map(agent => `<li><details open><summary><b>${esc(agent.name)}</b> ${status(agent.status)}</summary><small>${esc(agent.role)} · ${esc(agent.current_task)}</small>${children(agent.agent_id)}</details></li>`).join('')}</ul>`;
  const roots = state.data.agents.filter(agent => !agent.parent_agent_id).map(agent => `<li><details open><summary><b>${esc(agent.name)}</b> ${status(agent.status)}</summary><small>${esc(agent.role)}</small>${children(agent.agent_id)}</details></li>`).join('');
  return `<section class="panel"><div class="panel-header"><h2>Runtime-issued delegation tree</h2><small>${state.data.agents.length} registered agents</small></div><ul class="hierarchy">${roots || '<li>' + empty('agents') + '</li>'}</ul></section>`;
}

function world() { return table(['Fact', 'Value', 'Kind', 'Confidence', 'Source', 'Observed'], state.data.world.map(fact => `<tr><td><b>${esc(fact.key)}</b></td><td>${esc(JSON.stringify(fact.value))}</td><td>${status(fact.kind)}</td><td>${Math.round(fact.confidence * 100)}%<div class="metric-bar"><i style="width:${Math.round(fact.confidence * 100)}%"></i></div></td><td>${esc(fact.source)}</td><td>${formatDate(fact.timestamp)}</td></tr>`), 'world facts'); }
function health() { return table(['Component', 'Status', 'Last seen'], state.data.health.map(item => `<tr><td><b>${esc(item.component.replaceAll('_', ' '))}</b></td><td>${status(item.status)}</td><td>${formatDate(item.last_seen)}</td></tr>`), 'health checks'); }
function recovery() { return table(['Time', 'Event', 'Mission', 'Status', 'Detail'], state.data.recovery.slice().reverse().map(event => `<tr><td>${formatDate(event.timestamp)}</td><td>${esc(event.event_type)}</td><td><code>${shortId(event.mission_id)}</code></td><td>${status(event.status || event.severity)}</td><td>${esc(JSON.stringify(event.payload))}</td></tr>`), 'recovery activity'); }
function security() { return table(['Time', 'Agent', 'Tool', 'Permission', 'Policy', 'Result'], state.data.security.slice().reverse().map(action => `<tr><td>${formatDate(action.timestamp)}</td><td><code>${shortId(action.agent_id)}</code></td><td>${esc(action.tool)}</td><td>${esc(action.permission)}</td><td>${status(action.policy_decision)}</td><td>${esc(action.error || action.result)}</td></tr>`), 'security decisions'); }
function leases() { return table(['Capability', 'Agent', 'Mission', 'Task scope', 'Granted', 'Expires', 'Status'], state.data.leases.map(lease => `<tr><td><b>${esc(lease.permission)}</b><br><code>${shortId(lease.lease_id)}</code></td><td><code>${shortId(lease.agent_id)}</code></td><td><code>${shortId(lease.mission_id)}</code></td><td><code>${shortId(lease.task_id)}</code></td><td>${formatDate(lease.granted_at)}</td><td>${formatDate(lease.expires_at)}</td><td>${status(lease.status)}</td></tr>`), 'active capability leases'); }
function memory() { return table(['Task', 'Time', 'Provider', 'Status', 'Duration', 'Result'], state.data.memory.map(item => `<tr><td><code>${shortId(item.task_id)}</code></td><td>${formatDate(item.timestamp)}</td><td>${esc(item.provider)}</td><td>${status(item.status)}</td><td>${esc(item.duration_seconds)}s</td><td>${esc(item.error || item.final_result)}</td></tr>`), 'memory records'); }
function skills() { return table(['Skill', 'Status', 'Capabilities', 'Permissions', 'Verification', 'Success'], state.data.skills.map(skill => `<tr><td><b>${esc(skill.name)}</b><br><small>${esc(skill.description)}</small></td><td>${status(skill.status)}</td><td>${skill.required_capabilities.map(esc).join('<br>') || '—'}</td><td>${skill.required_permissions.map(esc).join('<br>') || '—'}</td><td>${esc(skill.verification_method)}</td><td>${skill.success_rate == null ? 'N/A' : Math.round(skill.success_rate * 100) + '%'}</td></tr>`), 'skills'); }
function inventory() { return table(['Registry', 'Authoritative values'], Object.entries(state.data.inventory).map(([key, value]) => `<tr><td><b>${esc(key.replaceAll('_', ' '))}</b></td><td>${esc(JSON.stringify(value))}</td></tr>`), 'inventory entries'); }
function analytics() { return `<div class="cards">${Object.entries(state.data.analytics).map(([key, value]) => `<article class="card"><span>${esc(key.replaceAll('_', ' ').toUpperCase())}</span><strong>${value == null ? 'N/A' : key.includes('rate') || key.includes('score') ? Math.round(value * 100) + '%' : Math.round(value)}</strong><small>${value == null ? 'Insufficient runtime data' : 'Observed outcomes only'}</small></article>`).join('')}</div><section class="panel" style="margin-top:13px"><h2>Metric integrity</h2><p class="muted">Rates use successful observed outcomes divided by corresponding real terminal runtime records. N/A means no valid denominator exists; the command center never invents a score.</p></section>`; }

const views = {overview, voice, perception, missions, missionDetail, tasks, schedules, agents, hierarchy, actions, world, resources, approvals, recovery, security, leases, activity, memory, skills, analytics, inventory, health};

function setConnection(mode, label) {
  $('#streamBadge').className = `connection ${mode}`;
  $('#streamBadge').innerHTML = `<i></i>${esc(label)}`;
  $('.runtime-card').className = `runtime-card ${mode}`;
  $('#runtimeBadge').textContent = label;
}

function render() {
  if (!state.data) return;
  const meta = viewMeta[state.view] || viewMeta.overview;
  $('#pageTitle').textContent = meta[0];
  $('#pageDescription').textContent = meta[1];
  $('#content').innerHTML = (views[state.view] || overview)();
  $('#content').setAttribute('aria-busy', 'false');
  $('#missionCount').textContent = state.data.overview.active_missions;
  $('#approvalCount').textContent = state.data.overview.pending_approvals;
  $('#lastSync').textContent = `Synced ${formatTime(state.data.generated_at)}`;
  $('#takeover').textContent = state.data.takeover_mode === 'takeover' ? 'Return control' : 'Take control';
  document.querySelectorAll('nav button').forEach(button => button.classList.toggle('active', button.dataset.view === state.view));
  setConnection('online', 'Runtime online');
  if (state.view === 'perception' && state.data.perception.screenshot_reference) loadPerceptionScreenshot();
}

async function loadPerceptionScreenshot() {
  const preview = $('.screen-preview');
  if (!preview) return;
  try {
    const response = await fetch('/api/perception/screenshot', {headers: {Authorization: `Bearer ${state.token}`}});
    if (!response.ok) throw new Error('Screenshot unavailable');
    const blob = await response.blob();
    const source = URL.createObjectURL(blob);
    preview.innerHTML = `<img alt="Latest runtime-authorized screen observation">`;
    preview.querySelector('img').src = source;
    preview.querySelector('img').addEventListener('load', () => URL.revokeObjectURL(source), {once: true});
  } catch (_) { preview.innerHTML = '<span>Screenshot unavailable or not permitted</span>'; }
}

function toast(message, type = '') {
  const element = document.createElement('div');
  element.className = `toast ${type}`;
  element.textContent = message;
  $('#toastRegion').append(element);
  setTimeout(() => element.remove(), 4500);
}

async function refresh({quiet = false} = {}) {
  try {
    state.data = await api('/api/system');
    state.lastEvent = Math.max(0, ...state.data.events.map(event => event.sequence));
    render();
    if (!quiet) toast('Runtime snapshot refreshed');
  } catch (error) {
    setConnection('offline', 'Runtime offline');
    if (!quiet) toast(error.message, 'error');
    if (!state.token || /401|authorized/i.test(error.message)) $('#auth').showModal();
  }
}

async function stream() {
  if (state.streaming) return;
  state.streaming = true;
  while (state.token) {
    try {
      const response = await fetch(`/api/stream?since=${state.lastEvent}`, {headers: {Authorization: `Bearer ${state.token}`}});
      if (!response.ok) throw new Error(`Event stream unavailable (${response.status})`);
      const text = await response.text();
      for (const block of text.split('\n\n')) {
        const id = block.match(/^id: (\d+)/m);
        if (id) state.lastEvent = Math.max(state.lastEvent, Number(id[1]));
      }
      if (text) await refresh({quiet: true});
    } catch (error) {
      setConnection('offline', 'Reconnecting');
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
  }
  state.streaming = false;
}

async function command(name, payload = {}) {
  try {
    await api('/api/commands', {method: 'POST', body: JSON.stringify({command: name, payload})});
    toast(`${name.replaceAll('_', ' ')} accepted by runtime`);
    await refresh({quiet: true});
  } catch (error) { toast(error.message, 'error'); }
}

document.querySelectorAll('nav button').forEach(button => button.addEventListener('click', () => {
  state.view = button.dataset.view;
  location.hash = state.view;
  $('#sidebar').classList.remove('open');
  $('#menu').setAttribute('aria-expanded', 'false');
  render();
}));
$('#menu').addEventListener('click', event => { const open = $('#sidebar').classList.toggle('open'); event.currentTarget.setAttribute('aria-expanded', String(open)); });
$('#refresh').addEventListener('click', () => refresh());
$('#takeover').addEventListener('click', () => command(state.data?.takeover_mode === 'takeover' ? 'release_takeover' : 'take_over'));
$('#newMission').addEventListener('click', () => $('#missionDialog').showModal());
$('#connect').addEventListener('click', event => { event.preventDefault(); state.token = $('#token').value.trim(); sessionStorage.setItem('ba-token', state.token); $('#auth').close(); refresh(); stream(); });
$('#submitMission').addEventListener('click', event => { event.preventDefault(); const goal = $('#missionGoal').value.trim(); if (!goal) return $('#missionGoal').reportValidity(); $('#missionDialog').close(); command('create_mission', {goal, priority: Number($('#missionPriority').value)}); $('#missionGoal').value = ''; });
$('#submitVoiceConfig').addEventListener('click', async event => { event.preventDefault(); const input = $('#assemblyApiKey'); if (!input.reportValidity()) return; const payload = {api_key: input.value.trim(), model: $('#assemblyModel').value.trim(), min_confidence: Number($('#voiceConfidence').value)}; const language = $('#voiceLanguage').value.trim(); if (language) payload.language = language; input.value = ''; $('#voiceDialog').close(); await command('configure_voice', payload); });
$('#content').addEventListener('click', event => { const button = event.target.closest('[data-command]'); if (button) command(button.dataset.command, {mission_id: button.dataset.mission, approval_id: button.dataset.approval}); });
$('#content').addEventListener('click', event => { if (event.target.closest('[data-voice-configure]')) $('#voiceDialog').showModal(); });
let voicePressed = false;
$('#content').addEventListener('pointerdown', event => { if (!event.target.closest('[data-voice-talk]')) return; event.preventDefault(); voicePressed = true; command('start_voice'); });
document.addEventListener('pointerup', () => { if (!voicePressed) return; voicePressed = false; command('stop_voice'); });
document.addEventListener('pointercancel', () => { if (!voicePressed) return; voicePressed = false; command('stop_voice'); });
$('#content').addEventListener('click', event => { const button = event.target.closest('[data-mission-view]'); if (!button) return; state.selectedMission = button.dataset.missionView; state.view = 'missionDetail'; history.replaceState(null, '', '#missions'); $('#pageTitle').textContent = 'Mission detail'; render(); });
$('#content').addEventListener('click', event => { const button = event.target.closest('[data-back]'); if (!button) return; state.selectedMission = null; state.view = button.dataset.back; location.hash = state.view; render(); });
$('#search').addEventListener('keydown', async event => { if (event.key !== 'Enter') return; try { const results = await api(`/api/search?q=${encodeURIComponent(event.target.value)}`); $('#pageTitle').textContent = 'Search results'; $('#pageDescription').textContent = `${results.length} structured runtime records matched “${event.target.value}”.`; $('#content').innerHTML = table(['Category', 'Record'], results.map(result => `<tr><td>${status(result.category)}</td><td><pre>${esc(JSON.stringify(result.item, null, 2))}</pre></td></tr>`), 'search results'); } catch (error) { toast(error.message, 'error'); } });
document.addEventListener('keydown', event => { if (event.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) { event.preventDefault(); $('#search').focus(); } });
window.addEventListener('hashchange', () => { state.view = location.hash.slice(1) || 'overview'; render(); });

if (!state.token) $('#auth').showModal(); else { refresh({quiet: true}); stream(); }
