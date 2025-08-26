const api = (path) => `http://localhost:8000${path}`;
const $ = (id)=>document.getElementById(id);

function toCSV(rows){
  if(!rows.length) return '';
  const headers = Object.keys(rows[0]);
  const head = headers.join(',');
  const body = rows.map(r => headers.map(h => JSON.stringify(r[h] ?? '')).join(',')).join('\n');
  return head + '\n' + body;
}
function download(name, text){
  const blob = new Blob([text], {type:'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function saveIdent(){
  localStorage.setItem('upn', $('upn').value.trim());
  localStorage.setItem('role', $('role').value);
  statusMsg('Saved user/role', 'success');
}
function loadIdent(){
  $('upn').value = localStorage.getItem('upn') || 'admin@example.com';
  $('role').value = localStorage.getItem('role') || 'PartsAdmin';
}
function headers(){
  const upn = $('upn').value.trim();
  const role = $('role').value;
  return { 'x-user-upn': upn, 'x-user-role': role };
}
function statusMsg(msg, type=''){
  const el = $('status');
  el.className = type ? type : 'muted';
  el.textContent = msg;
}

function statusMsg(msg, type=''){
  const el = $('status');
  el.className = type ? type : 'muted';
  el.textContent = msg;
}

function identOk(){
  const upn = $('upn').value.trim();
  const role = $('role').value;
  if(!upn || !role){
    statusMsg('Set User (UPN) and Role, then click Save', 'error');
    return false;
  }
  return true;
}

async function listParts(){
  const q = $('search').value.trim();
  const url = api(`/parts${q ? `?search=${encodeURIComponent(q)}`:''}`);
  const res = await fetch(url);
  const data = await res.json();
  const body = $('partsBody');
  body.innerHTML = '';
  data.forEach(r=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="radio" name="partPick" value="${r.part_no}"></td>
      <td><span class="tag">${r.part_no}</span></td>
      <td>${r.description || ''}</td>
      <td>${r.available}</td>
      <td>${r.location || ''}</td>
    `;
    body.appendChild(tr);
  });
}

async function loadStock(){
  if(!identOk()) return;
  const u = new URL(api('/stock'));
  const q = $('dash_search').value.trim();
  if(q) u.searchParams.set('search', q);
  const res = await fetch(u, { headers: headers() });
  if(!res.ok){ const t=await res.text(); return statusMsg(`Stock error: ${t}`,'error'); }
  const rows = await res.json();
  const tb = document.querySelector('#stock_tbl tbody');
  tb.innerHTML = rows.map(r => `
    <tr>
      <td>${r.part_no}</td>
      <td>${r.description}</td>
      <td>${r.available}</td>
      <td>${r.location||''}</td>
    </tr>`).join('');
  window.__lastStock = rows;
}

async function loadLedger(){
  if(!identOk()) return;
  const u = new URL(api('/ledger'));
  const a = $('lg_action').value; if(a) u.searchParams.set('action', a);
  const p = $('lg_part').value.trim(); if(p) u.searchParams.set('part_no', p);
  const wo = $('lg_wo').value.trim(); if(wo) u.searchParams.set('work_order_no', wo);
  const s = $('lg_since').value; if(s) u.searchParams.set('since', s);
  const un = $('lg_until').value; if(un) u.searchParams.set('until', un);
  const res = await fetch(u, { headers: headers() });
  if(!res.ok){ const t=await res.text(); return statusMsg(`Ledger error: ${t}`,'error'); }
  const rows = await res.json();
  const tb = document.querySelector('#ledger_tbl tbody');
  tb.innerHTML = rows.map(r => `
    <tr>
      <td>${new Date(r.event_time).toLocaleString()}</td>
      <td>${r.user_upn||''}</td>
      <td>${r.action}</td>
      <td>${r.part_no}</td>
      <td>${r.qty}</td>
      <td>${r.work_order_no||''}</td>
      <td>${r.vendor_claim_no||''}</td>
      <td>${r.prev_qty} → ${r.new_qty}</td>
    </tr>`).join('');
}

async function ensureCart(){
  if(!identOk()) throw new Error('Missing identity');
  const res = await fetch(api('/cart'), { method:'POST', headers: headers() });
  if(!res.ok){ throw new Error('Create cart failed'); }
  return res.json();
}


async function addSelected(){
  const pick = document.querySelector('input[name="partPick"]:checked');
  if(!pick){ return statusMsg('Pick a part first','error'); }
  await ensureCart();
  const part_no = pick.value;
  const u = new URL(api('/cart/lines'));
  u.searchParams.set('part_no', part_no);
  const res = await fetch(u, { method:'POST', headers: headers() });
  if(!res.ok){
    const txt = await res.text();
    return statusMsg(`Add failed: ${txt}`, 'error');
  }
  statusMsg(`Added ${part_no} to summary`,'success');
  await refreshSummary();
}

async function refreshSummary(){
  const res = await fetch(api('/cart/summary'), { headers: headers() });
  if(!res.ok){ $('summary').textContent = 'None selected.'; $('commit').disabled = true; return; }
  const lines = await res.json();
  $('commit').disabled = (lines.length === 0);
  if(!lines.length){ $('summary').textContent = 'None selected.'; return; }
  $('summary').innerHTML = lines.map(d=>`• ${d.part_no} (qty 1)`).join('<br>');
}

async function commitCheckout(){
  if(!identOk()) return;
  const wo = $('wo').value.trim();
  if(!wo){ return statusMsg('Enter a Work Order number','error'); }

  try{
    // send as ?work_order_no=... (query param), not form body
    const u = new URL(api('/checkout/commit'));
    u.searchParams.set('work_order_no', wo);

    const res = await fetch(u, { method:'POST', headers: headers() });
    if(!res.ok){
      const txt = await res.text();
      return statusMsg(`Checkout failed: ${txt}`, 'error');
    }

    statusMsg(`Issued parts to ${wo}`,'success');
    await refreshSummary();
    await listParts();
  }catch(e){
    statusMsg(e.message, 'error');
  }
}

async function clearSummary(){
  if(!identOk()) return;
  try{
    const res = await fetch(api('/cart/clear'), { method:'DELETE', headers: headers() });
    if(!res.ok){
      const txt = await res.text();
      return statusMsg(`Clear failed: ${txt}`, 'error');
    }
    statusMsg('Cleared cart','success');
    await refreshSummary();
  }catch(e){
    statusMsg(e.message, 'error');
  }
}

async function checkIn(){
  const p = $('in_part').value.trim();
  const wo = $('in_wo').value.trim();
  const vc = $('in_claim').value.trim();
  if(!(p && wo && vc)){ return statusMsg('Fill Part, Work Order, and Vendor Claim','error'); }
  const form = new FormData();
  form.set('part_no', p);
  form.set('work_order_no', wo);
  form.set('vendor_claim_no', vc);
  const res = await fetch(api('/checkin'), { method:'POST', headers: headers(), body: form });
  if(!res.ok){
    const txt = await res.text();
    return statusMsg(`Check-in failed: ${txt}`, 'error');
  }
  statusMsg(`Checked in ${p} to ${wo}`,'success');
  await listParts();
}

window.onload = async () => {
  loadIdent();
  $('saveIdent').onclick = saveIdent;
  $('addSelected').onclick = addSelected;
  $('commit').onclick = commitCheckout;
  $('refreshParts').onclick = listParts;
  $('checkin').onclick = checkIn;
  const clearBtn = document.getElementById('clearCart');
  if (clearBtn) clearBtn.onclick = clearSummary;

  // dashboard
  const dr = $('dash_refresh'); if(dr) dr.onclick = loadStock;
  const de = $('dash_export'); if(de) de.onclick = () => download('stock.csv', toCSV(window.__lastStock||[]));
  const lr = $('lg_refresh'); if(lr) lr.onclick = loadLedger;

  await listParts();
  await refreshSummary();
  await loadStock();
  await loadLedger();
};
