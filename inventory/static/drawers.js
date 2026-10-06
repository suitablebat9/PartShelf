(() => {
  const app=document.querySelector('#drawer-app'); if(!app)return;
  const cells=[...app.querySelectorAll('[data-slot]')], status=document.querySelector('#drawer-status'), assignment=document.querySelector('#drawer-assignment');
  const light=document.querySelector('#drawer-light'), open=document.querySelector('#drawer-open'), check=document.querySelector('#drawer-check'), dialog=document.querySelector('#drawer-open-dialog');
  let selected=null, active=app.dataset.active, sending=false, timer=null, polls=0;
  function controls(){light.disabled=open.disabled=!selected||app.dataset.enabled!=='1'||!!active||sending;check.hidden=!active;}
  function select(cell){selected=cell;cells.forEach(c=>c.setAttribute('aria-pressed',String(c===cell)));document.querySelector('#selected-drawer-title').textContent='Drawer '+cell.dataset.label;document.querySelector('#drawer-empty-selection').hidden=true;document.querySelector('#drawer-controls').hidden=false;document.querySelectorAll('[data-contents]').forEach(p=>p.hidden=p.dataset.contents!==cell.dataset.slot);if(assignment){assignment.hidden=false;const [row,col]=cell.dataset.slot.split('-');assignment.elements.row.value=row;assignment.elements.col.value=col;}controls();if(matchMedia('(max-width:1100px)').matches)document.querySelector('.drawer-inspector').scrollIntoView({behavior:'smooth',block:'start'});}
  cells.forEach(cell=>cell.addEventListener('click',()=>select(cell)));
  document.querySelector('#drawer-search').addEventListener('input',e=>{const term=e.target.value.trim().toLowerCase();cells.forEach(cell=>cell.classList.toggle('dimmed',!cell.dataset.search.includes(term)));});
  document.querySelector('#assign-search')?.addEventListener('input',e=>{const term=e.target.value.toLowerCase();[...assignment.elements.component_id.options].forEach(o=>o.hidden=o.value&&!o.textContent.toLowerCase().includes(term));});
  function display(result){
    const messages={sending:'Sending command…',accepted:'Accepted by controller. Waiting for motion to finish…',running:'Carriage is moving. Waiting for completion…',completed:'Controller reports the command completed.',failed:'Controller reports the command failed. Check the mechanism before trying again.',unknown:'Delivery or completion is uncertain. Controls remain locked. Check status; do not resend the command.'};
    status.textContent=messages[result.status]||'Check the controller before continuing.';
    if(['completed','failed','manually resolved'].includes(result.status)){active='';clearTimeout(timer);}else if(polls<30){timer=setTimeout(poll,2000);}
    controls();
  }
  async function poll(){if(!active)return;clearTimeout(timer);polls++;try{const response=await fetch(`/drawers/${app.dataset.cabinet}/status/${active}`,{headers:{Accept:'application/json'}});if(!response.ok)throw Error();display(await response.json());}catch{status.textContent='Could not reach the controller. Controls remain locked. Check status or reload this page.';controls();}}
  async function send(action){if(!selected||active||sending)return;sending=true;controls();status.textContent='Sending command…';const [row,col]=selected.dataset.slot.split('-');const body=new FormData();body.set('csrf',document.querySelector('meta[name=csrf-token]').content);body.set('row',row);body.set('col',col);body.set('action',action);if(action==='open')body.set('confirmed','1');try{const response=await fetch(`/drawers/${app.dataset.cabinet}/command`,{method:'POST',body,headers:{Accept:'application/json'}});if(!response.ok)throw Error();const result=await response.json();active=result.command_id;polls=0;sending=false;display(result);}catch{status.textContent='Command status is uncertain. Reload this page to check before issuing another command.';/* Keep controls locked until reload retrieves the persisted command. */}}
  light.addEventListener('click',()=>send('light'));
  open.addEventListener('click',()=>{document.querySelector('#open-drawer-name').textContent=selected.dataset.label;dialog.showModal();});
  document.querySelector('#cancel-drawer-open').addEventListener('click',()=>dialog.close());
  document.querySelector('#confirm-drawer-open').addEventListener('click',()=>{dialog.close();send('open');});
  check.addEventListener('click',()=>{polls=0;poll();});
  const requested=new URLSearchParams(location.search).get('slot');if(requested){const cell=cells.find(c=>c.dataset.slot===requested);if(cell)select(cell);}controls();if(active)poll();
})();
