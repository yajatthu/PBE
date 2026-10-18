function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
let last=null;let registering=false;const tokenKey='pbe_session_token';
async function api(url,opt={}){const headers={'Content-Type':'application/json',...(opt.headers||{})};const token=sessionStorage.getItem(tokenKey);if(token)headers.Authorization='Bearer '+token;let r=await fetch(url,{...opt,headers});let j={};try{j=await r.json()}catch{}if(!r.ok)throw Error(j.detail||'Request failed');return j}
function showAuth(){document.getElementById('auth-panel').style.display='block';document.getElementById('app-content').hidden=true}
function showApp(){document.getElementById('auth-panel').style.display='none';document.getElementById('app-content').hidden=false;refresh().catch(e=>{sessionStorage.removeItem(tokenKey);showAuth();document.getElementById('auth-error').textContent=e.message})}
function logout(){sessionStorage.removeItem(tokenKey);showAuth()}
document.getElementById('auth-toggle').addEventListener('click',()=>{registering=!registering;document.getElementById('register-fields').hidden=!registering;document.getElementById('auth-submit').textContent=registering?'CREATE ACCOUNT':'LOGIN';document.getElementById('auth-toggle').textContent=registering?'BACK TO LOGIN':'CREATE ACCOUNT';document.getElementById('auth-password').autocomplete=registering?'new-password':'current-password';document.getElementById('auth-error').textContent=''});
document.getElementById('auth-form').addEventListener('submit',async ev=>{ev.preventDefault();const error=document.getElementById('auth-error');error.textContent='';const body={email:document.getElementById('auth-email').value,password:document.getElementById('auth-password').value};if(registering){body.tenant_name=document.getElementById('tenant-name').value;body.workspace_name=document.getElementById('workspace-name').value}try{const result=await api(registering?'/api/auth/register':'/api/auth/login',{method:'POST',body:JSON.stringify(body)});sessionStorage.setItem(tokenKey,result.access_token);showApp()}catch(e){error.textContent=e.message}});

async function refresh(){let s=await api('/api/state');last=s;document.getElementById('mode').textContent=s.runtime_mode;renderModules(s.modules);renderTrace(s.audit);let active=[...s.modules].reverse().find(x=>x.state==='ACTIVE'||x.state==='STAGED');renderDetail(active);loadServices().catch(()=>{});loadHistory().catch(()=>{})}
function renderModules(ms){document.getElementById('modules').innerHTML=ms.length?ms.slice().reverse().map(m=>`<div class="module ${m.state==='ACTIVE'?'active':''}"><span class="state">${m.state}</span><h3>${esc(m.name)} · v${m.version}</h3><p>${esc(m.purpose)}</p><small>hash ${esc(m.generated_module_hash.slice(0,18))}… · ${m.validation.passed||0}/${m.validation.total||0} validation checks</small>${m.state==='STAGED'?`<button class="approve" onclick="approve('${m.module_id}')">APPROVE (REGISTRY ONLY)</button>`:''}</div>`).join(''):'<div class="empty">No generated capability yet.</div>'}
function renderTrace(ts){document.getElementById('trace').innerHTML=ts.length?ts.slice().reverse().map(x=>`<div class="traceitem"><b>${esc(x.action)}</b><small>${esc(x.detail)}</small></div>`).join(''):'<div class="empty">Waiting for observation.</div>'}
function renderDetail(m){if(!m){document.getElementById('detail').innerHTML='<div class="empty">Inject a business signal to begin the Observation-to-Code cycle.</div>';return}let tests=(m.validation.tests||[]).map(t=>`${t.name}: ${t.status} — ${t.detail}`).join('\n');document.getElementById('validation').textContent=`${m.validation.passed}/${m.validation.total} CHECKS PASSED`;document.getElementById('detail').innerHTML=`<div class="kpis"><div class="kpi"><strong>${m.version}</strong>VERSION</div><div class="kpi"><strong>${m.validation.passed}/${m.validation.total}</strong>VALIDATION</div><div class="kpi"><strong>${m.state}</strong>STATE</div></div><p>${esc(m.reasoning||'')}</p><h4>Validation trace</h4><pre>${esc(tests)}</pre><h4>Dynamic UI contract</h4><pre>${esc(JSON.stringify(m.frontend_json_layout_schema,null,2))}</pre><h4>Permission manifest</h4><pre>${esc(JSON.stringify(m.security_permission_manifest,null,2))}</pre>`}
async function inject(){await api('/api/demo/inject',{method:'POST',body:JSON.stringify({})});await refresh()}async function approve(id){await api('/api/modules/'+id+'/approve',{method:'POST'});await refresh()}async function fail(){await api('/api/demo/failure',{method:'POST'});await refresh()}async function reset(){await api('/api/demo/reset',{method:'POST'});await refresh()}if(sessionStorage.getItem(tokenKey))showApp();else showAuth();

// v0.7: outcome-first capability replacement and PBE engine submission workflow.
let serviceCatalog=[];let connectedAccounts=[];let currentPlans=[];let selectedServices=new Set();
async function loadServices(){
  const box=document.getElementById('services'); if(!box)return;
  try{
    const [catalog,accounts]=await Promise.all([api('/api/composio/catalog'),api('/api/composio/accounts').catch(()=>({}))]);
    serviceCatalog=catalog.services||[];connectedAccounts=flattenAccounts(accounts);renderConnectedAccess();
    box.innerHTML=serviceCatalog.map(s=>`<article class="service-card"><label class="service-pick"><input type="checkbox" ${selectedServices.has(s.slug)?'checked':''} onchange="toggleService('${esc(s.slug)}',this.checked)"/><span><h3>${esc(s.name)}</h3></span></label><p>${esc(s.description)}</p><span class="configured">${s.configured?'READY TO CONNECT':'ADMIN SETUP NEEDED'}</span><button ${s.configured?'':'disabled'} onclick="connectService('${esc(s.slug)}')">CONNECT ${esc(s.name.toUpperCase())}</button></article>`).join('');
    document.getElementById('connect-status').textContent=catalog.message||'';
  }catch(e){box.innerHTML=`<div class="empty">${esc(e.message)}. Check the server's Composio setup.</div>`}
}
function flattenAccounts(raw){
  const found=[];const seen=new Set();
  function walk(v){if(Array.isArray(v)){v.forEach(walk);return}if(!v||typeof v!=='object')return;
    const id=v.id||v.connected_account_id||v.connectedAccountId;
    let toolkit=v.toolkit_slug||v.toolkit||v.app||v.integration_name||v.appName||v.integration; if(toolkit&&typeof toolkit==='object')toolkit=toolkit.slug||toolkit.name;
    if(id&&!seen.has(String(id))){seen.add(String(id));const rawScopes=v.scopes||v.permissions||v.granted_scopes||v.scope||v.permission;const access=Array.isArray(rawScopes)?rawScopes.map(x=>typeof x==='string'?x:(x.name||x.scope||x.permission||'')).filter(Boolean):typeof rawScopes==='string'?rawScopes.split(/[ ,]+/).filter(Boolean):[];found.push({id:String(id),toolkit:String(toolkit||'unknown'),name:String(v.name||v.display_name||toolkit||'Connected account'),status:String(v.status||v.state||'UNKNOWN'),access})}
    Object.values(v).forEach(x=>{if(x&&typeof x==='object')walk(x)});
  }walk(raw);return found;
}
function renderConnectedAccess(){
 const box=document.getElementById('connected-access');if(!box)return;
 if(!connectedAccounts.length){box.innerHTML='<div class="empty">No connected accounts were returned for this workspace user. Connect a service above, finish the provider consent screen, then refresh access.</div>';return}
 box.innerHTML=connectedAccounts.map(a=>{
  const status=a.status.toUpperCase(),active=!['PENDING','EXPIRED','FAILED','DISCONNECTED','REVOKED','INACTIVE','UNKNOWN'].includes(status);
  const access=a.access&&a.access.length?'Provider-reported permissions: '+a.access.join(', '):'Permission scope is controlled by the provider consent grant; this account response did not expose a detailed scope list.';
  return `<article class="access-card"><div><h4>${esc(a.name)} · ${esc(a.toolkit)}</h4><p>Account ID: ${esc(a.id)}</p><p>${esc(access)}</p></div><span class="access-state ${active?'':'warn'}">${esc(status)}</span></article>`;
 }).join('');
}
async function connectService(slug){
  const status=document.getElementById('connect-status');status.textContent='Opening the provider authorization page…';
  // Open synchronously during the click so browser popup blockers do not swallow the auth window.
  const authWindow=window.open('about:blank','_blank');
  try{const r=await api('/api/composio/connect',{method:'POST',body:JSON.stringify({toolkit_slug:slug})});
    const url=r.redirect_url||r.auth_url||r.link||r.url||r.data?.redirect_url||r.data?.auth_url||r.data?.link||r.data?.url;
    if(url){if(authWindow)authWindow.location.href=url;else window.location.href=url;status.textContent='Finish authorization with the provider, then refresh services.'}
    else {if(authWindow)authWindow.close();status.textContent='Composio did not return an authorization URL. Check the server integration configuration.';console.info('Composio auth response',r)}
  }catch(e){if(authWindow)authWindow.close();status.textContent=e.message}
}
async function createPlan(){
  const objective=document.getElementById('pbe-objective').value.trim();const status=document.getElementById('plan-status');
  if(objective.length<8){status.textContent='Tell PBE a little more about the work you want to replace.';return}
  const services=[...selectedServices];status.textContent='PBE is mapping the work and checking available tool actions…';
  try{const p=await api('/api/pbe/plan',{method:'POST',body:JSON.stringify({objective,services})});currentPlans=[p,...currentPlans.filter(x=>x.id!==p.id)];status.textContent='Plan created. Review it before running anything.';renderPlan(p);loadTimeline(p.id).catch(()=>{});loadHistory().catch(()=>{})}catch(e){status.textContent=e.message}
}
function renderPlan(p){
  const plan=p.plan||{};const actions=plan.tool_actions||[];const native=plan.native_capabilities||[];
  const chips=(p.services||[]).map(s=>`<span class="plan-chip">${esc(s)}</span>`).join('');
  const actionsHtml=actions.length?actions.map((a,i)=>{
    const matches=connectedAccounts.filter(ac=>ac.toolkit!=='unknown'&&(ac.toolkit.toLowerCase().replaceAll('_','').replaceAll('-','').includes(String(a.toolkit).toLowerCase().replaceAll('_','').replaceAll('-',''))||String(a.toolkit).toLowerCase().replaceAll('_','').replaceAll('-','').includes(ac.toolkit.toLowerCase().replaceAll('_','').replaceAll('-',''))));
    const options=matches.map(ac=>`<option value="${esc(ac.id)}">${esc(ac.name)} · ${esc(ac.id)}</option>`).join('');
    return `<div class="plan-action"><b>${i+1}. ${esc(a.title)}</b><p>${esc(a.purpose)}</p><small>Tool: ${esc(a.tool_slug)} · Approval required</small><pre>${esc(JSON.stringify(a.arguments||{},null,2))}</pre><div><select id="acct-${esc(p.id)}-${i}"><option value="">Choose connected account</option>${options}</select></div><button ${p.status==='APPROVED'&&matches.length?'':'disabled'} onclick="runPlanAction('${esc(p.id)}',${i})">RUN THIS ACTION</button>${matches.length?'':'<p class="warning-copy">No matching connected account found. Connect this service first.</p>'}</div>`
  }).join(''):'<p class="warning-copy">No executable tool actions were selected. Connect the relevant service(s), then create a new plan. PBE will still outline the native capability it could build.</p>';
  const nativeHtml=native.map((n,i)=>`<div class="plan-action"><b>${esc(n.name)} <span class="plan-chip">${esc(n.readiness||'PROPOSED')}</span></b><p><b>Potential replacement:</b> ${esc(n.replaces)}</p><p>${esc(n.capability)}</p><h4>Build path</h4><ul>${(n.implementation_steps||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul><h4>Before cancelling a subscription</h4><ul>${(n.subscription_cancel_gate||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul><button ${['APPROVED','COMPLETED'].includes(p.status)&&!n.generated_module_id&&!n.source_event_id&&n.engine_submission_status!=='SUBMITTED'?'':'disabled'} onclick="submitCapability('${esc(p.id)}',${i})">SEND TO PBE ENGINE</button>${n.generated_module_id?`<p>Module: ${esc(n.generated_module_id)} · ${esc(n.engine_validation?.state||'GENERATED')}</p>`:''}</div>`).join('');
  const limits=(plan.limitations||[]).map(x=>`<li>${esc(x)}</li>`).join('');
  document.getElementById('plan-results').innerHTML=`<article class="plan-card"><span class="plan-chip">${esc(p.status||'PLANNED')}</span>${chips}<h3>${esc(plan.title||'PBE Capability Plan')}</h3><p>${esc(plan.objective_summary||p.objective)}</p>
<div class="plan-estimate"><strong>Estimated workflow time:</strong> ${esc(plan.estimated_duration_minutes||15)} minutes · This is an estimate, not a guarantee. <br><strong>Current status:</strong> ${esc(p.status||'PLANNED')} · <span id="final-check-note">External application state still requires verification.</span></div>
${(plan.workflow_steps||[]).length?`<h4>Expected process timeline</h4><div class="plan-steps">${plan.workflow_steps.map((st,i)=>`<div class="plan-step"><span class="timeline-dot">${i+1}</span><div><b>${esc(st.title||'Workflow step')}</b><p>${esc(st.description||'')}</p></div><small>${esc(st.estimated_minutes||0)} min · ${esc(st.status||'PENDING')}</small></div>`).join('')}</div>`:''}
<h4>What PBE understands</h4><ul>${(plan.capabilities_observed||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul><h4>Actions in your connected tools</h4>${actionsHtml}<h4>Capabilities PBE could build internally</h4>${nativeHtml}<h4>Potential economics</h4><p>${esc(plan.savings_logic||'Savings need to be measured against the cost of operating the replacement.')}</p>${limits?`<h4>Prototype boundaries</h4><ul>${limits}</ul>`:''}<p class="warning-copy">A proposal is not a working replacement yet. Do not cancel a paid service until the PBE capability is implemented, tested with your real workflow, and accepted.</p><button ${p.status==='APPROVED'?'disabled':''} onclick="approvePlan('${esc(p.id)}')" ${p.status==='PLANNED'?'':'disabled'}>APPROVE PLAN</button></article>`;
}
async function submitCapability(id,index){
  const p=currentPlans.find(x=>x.id===id);if(!p)return;
  if(!confirm('Send this approved capability request through PBE Observation-to-Code? This creates a business event and may generate a staged module. It will not deploy code live.'))return;
  document.getElementById('plan-status').textContent='Submitting capability to PBE Observation-to-Code…';
  try{const r=await api(`/api/pbe/plans/${id}/capabilities/${index}/submit-to-engine`,{method:'POST'});if(p.plan.native_capabilities[index]){Object.assign(p.plan.native_capabilities[index],{engine_submission_status:r.status,source_event_id:r.event_id,generated_module_id:r.module?.module_id,engine_validation:r.module?{passed:r.module.validation?.passed||0,total:r.module.validation?.total||0,state:r.module.state,deployment_status:r.module.deployment_status}:undefined,readiness:r.module?(r.module.state==='STAGED'?'GENERATED_AND_VALIDATED':'VALIDATION_BLOCKED'):'IN_REVIEW'})}document.getElementById('plan-status').textContent=r.message||'Submitted to PBE engine';renderPlan(p);await refresh();loadTimeline(id).catch(()=>{});loadHistory().catch(()=>{})}catch(e){document.getElementById('plan-status').textContent=e.message}
}
async function approvePlan(id){try{const r=await api(`/api/pbe/plans/${id}/approve`,{method:'POST'});const p=currentPlans.find(x=>x.id===id);if(p)p.status=r.status;document.getElementById('plan-status').textContent=r.message||'Plan approved';if(p)renderPlan(p);loadTimeline(id).catch(()=>{});loadHistory().catch(()=>{})}catch(e){document.getElementById('plan-status').textContent=e.message}}
async function runPlanAction(id,index){
  const account=document.getElementById(`acct-${id}-${index}`)?.value;if(!account){document.getElementById('plan-status').textContent='Choose the connected account first.';return}
  const p=currentPlans.find(x=>x.id===id);const action=p?.plan?.tool_actions?.[index];if(!action)return;
  if(!confirm(`Run “${action.title}” in ${action.toolkit}? This sends the listed action and arguments to the connected service.`))return;
  document.getElementById('plan-status').textContent='Running the approved action…';
  try{const r=await api(`/api/pbe/plans/${id}/actions/${index}/execute`,{method:'POST',body:JSON.stringify({connected_account_id:account,confirm:true})});p.status=r.workflow_status||p.status;document.getElementById('plan-status').textContent=r.workflow_status==='COMPLETED'?'All planned actions have success records and OpenRouter reviewed the execution trace. Verify the resulting app state manually.':'Action executed. Review the provider result below.';const note=document.getElementById('final-check-note');if(note&&r.final_review)note.textContent='OpenRouter review: '+r.final_review.status+' — '+(r.final_review.summary||'');renderPlan(p);loadTimeline(id).catch(()=>{});loadHistory().catch(()=>{});const results=document.createElement('pre');results.textContent=JSON.stringify(r.result,null,2);document.getElementById('plan-results').appendChild(results)}catch(e){document.getElementById('plan-status').textContent=e.message}
}
async function loadPlans(){try{const r=await api('/api/pbe/plans');currentPlans=r.plans||[];if(currentPlans.length){const p=currentPlans[0];renderPlan(p);document.getElementById('plan-status').textContent='Loaded your latest saved plan.'}}catch(e){console.warn('Could not load saved plans',e.message)}}
const oldShowApp=showApp;showApp=function(){oldShowApp();loadServices().catch(()=>{});loadPlans().catch(()=>{})};

function toggleService(slug,checked){if(checked)selectedServices.add(slug);else selectedServices.delete(slug)}

if(sessionStorage.getItem(tokenKey)){loadServices().catch(()=>{});loadPlans().catch(()=>{})}


// v0.9: persisted process timeline, expected completion estimate, and workspace history.
function fmtDate(value){
 if(!value)return 'Time not available';
 const d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleString([], {year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
}
async function loadTimeline(id){
 const box=document.getElementById('workflow-timeline');if(!box||!id)return;
 try{
  const t=await api(`/api/pbe/plans/${encodeURIComponent(id)}/timeline`);
  const eta=t.expected_completion_at?fmtDate(t.expected_completion_at):`${t.estimated_duration_minutes} minutes from start`;
  box.innerHTML=`<div class="timeline-card"><div class="timeline-summary"><span>STATUS · ${esc(t.status)}</span><span>PROGRESS · ${esc(t.progress)}%</span><span>ESTIMATE · ${esc(t.estimated_duration_minutes)} min</span></div><p><b>Expected completion:</b> ${esc(eta)}</p><p><b>Started:</b> ${esc(fmtDate(t.created_at))} · <b>Latest activity:</b> ${esc(fmtDate(t.latest_activity_at))}</p><p>${t.completion_is_verified?'PBE workflow status is marked completed; independently verify the resulting business state.':'Completion time is an estimate and can change with provider latency, permissions, retries, and human approval.'}</p></div>`+
   (t.timeline.length?t.timeline.map((e,i)=>`<div class="timeline-item"><span class="timeline-dot">${i+1}</span><div><strong>${esc(e.title)}</strong><p>${esc(e.detail||'')}</p><small>${esc(fmtDate(e.timestamp))} · ${esc(e.progress==null?'':e.progress+'% progress')}</small></div></div>`).join(''):'<div class="empty">No timeline events have been recorded yet.</div>')+
   (t.executions.length?`<div class="timeline-card"><h4>Execution records</h4>${t.executions.map(e=>`<p>Action ${Number(e.action_index)+1} · ${esc(e.status)} · ${esc(fmtDate(e.created_at))}</p>`).join('')}</div>`:'');
 }catch(e){box.innerHTML=`<div class="empty">${esc(e.message)}. Timeline becomes available after the v0.9 database migration is applied.</div>`}
}
async function loadHistory(){
 const box=document.getElementById('workflow-history');if(!box)return;
 try{
  const r=await api('/api/pbe/history');const items=r.items||[];
  if(!items.length){box.innerHTML='<div class="empty">No saved workflows yet. Create a plan to start a persistent history.</div>';return}
  box.innerHTML=items.map(p=>`<article class="history-card" role="button" tabindex="0" onclick="loadTimeline('${esc(p.id)}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();loadTimeline('${esc(p.id)}')}"><h4>${esc(p.objective.length>115?p.objective.slice(0,112)+'…':p.objective)}</h4><p>Created ${esc(fmtDate(p.created_at))}</p><div class="history-meta"><span>${esc(p.status)}</span><span>${esc(p.estimated_duration_minutes)} min estimate</span><span>${esc(p.tool_action_count)} tool actions</span><span>${esc(p.native_capability_count)} native proposals</span></div></article>`).join('');
 }catch(e){box.innerHTML=`<div class="empty">${esc(e.message)}</div>`}
}
