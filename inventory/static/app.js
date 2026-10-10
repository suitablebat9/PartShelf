const savedTheme=localStorage.getItem('partshelf-theme');
document.body.dataset.theme=savedTheme||'light';
document.querySelector('#theme-toggle')?.addEventListener('click',()=>{const theme=document.body.dataset.theme==='dark'?'light':'dark';document.body.dataset.theme=theme;localStorage.setItem('partshelf-theme',theme)});
let dirty=false;document.addEventListener('input',()=>{dirty=true});
if(document.querySelector('[data-auto-refresh]'))setInterval(()=>{if(!dirty&&!document.hidden&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName))location.reload()},20000);
document.querySelectorAll('form[data-confirm]').forEach(form=>form.addEventListener('submit',e=>{if(!confirm(form.dataset.confirm))e.preventDefault()}));
// Select zero on focus so the first typed digit replaces it without extra clicks.
document.querySelectorAll('input[type="number"]').forEach(input=>{
  input.addEventListener('focus',()=>{if(input.value!==''&&Number(input.value)===0)input.select()});
  input.addEventListener('click',()=>{if(input.value!==''&&Number(input.value)===0)input.select()});
});
const partName=document.querySelector('#part-name'),partId=document.querySelector('#part-id'),partCode=document.querySelector('#part-code');
if(partName&&partId){
  let manualId=Boolean(partId.value&&partId.value!==partName.value);
  let manualCode=Boolean(partCode.value&&partCode.value!==partId.value);
  function syncCode(){if(!manualCode)partCode.value=partId.value||partName.value}
  partCode.addEventListener('input',()=>{manualCode=Boolean(partCode.value)});
  partId.addEventListener('input',()=>{manualId=Boolean(partId.value);syncCode()});
  partName.addEventListener('input',()=>{if(!manualId)partId.value=partName.value;syncCode()});
}
const purchaseQty=document.querySelector('#purchase-quantity'),unitPrice=document.querySelector('#unit-price'),purchaseTotal=document.querySelector('#purchase-total'),priceMode=document.querySelector('#price-mode');
function prices(){
  if(!purchaseQty)return;
  const quantity=Number(purchaseQty.value),mode=priceMode.value;
  if(quantity>0 && (mode==='purchase'?purchaseTotal.value:unitPrice.value)!==''){
    if(mode==='purchase')unitPrice.value=String(Number((Number(purchaseTotal.value||0)/quantity).toFixed(6)));
    else purchaseTotal.value=String(Number((Number(unitPrice.value||0)*quantity).toFixed(6)));
    document.querySelector('#price-summary').textContent=`${quantity} × ${unitPrice.value||0} per unit = ${purchaseTotal.value||0} purchase total`;
  }else {if(mode==='purchase')unitPrice.value='';else purchaseTotal.value='';document.querySelector('#price-summary').textContent='';}
}
if(purchaseQty){
  let manualQuantity=Boolean(purchaseQty.value);
  purchaseQty.addEventListener('input',()=>{manualQuantity=true;prices()});
  unitPrice.addEventListener('input',()=>{priceMode.value='unit';prices()});
  purchaseTotal.addEventListener('input',()=>{priceMode.value='purchase';prices()});
  priceMode.addEventListener('change',prices);
  document.querySelector('#stock').addEventListener('input',e=>{if(document.querySelector('#component-form').dataset.new==='true'&&!manualQuantity){purchaseQty.value=Number(e.target.value)>0?e.target.value:'';prices()}});
  prices();
}
const componentForm=document.querySelector('#component-form');
if(componentForm){
  const tagInput=document.querySelector('#part-tags'),savedTags=document.querySelector('#saved-tags'),tagList=document.querySelector('#selected-tags'),tagStatus=document.querySelector('#tag-status');
  let tags=savedTags.value.split(',').map(t=>t.trim()).filter(Boolean);
  function renderTags(){
    savedTags.value=tags.join(', ');tagList.replaceChildren();
    tags.forEach(tag=>{const button=document.createElement('button');button.type='button';button.className='tag-choice secondary';button.textContent=tag+' ×';button.setAttribute('aria-label','Remove tag '+tag);button.addEventListener('click',()=>{tags=tags.filter(t=>t!==tag);renderTags();dirty=true});tagList.append(button)});
  }
  function addTags(value=tagInput.value){
    const next=[...tags];
    value.split(',').map(t=>t.trim()).filter(Boolean).forEach(tag=>{if(!next.some(t=>t.toLocaleLowerCase()===tag.toLocaleLowerCase()))next.push(tag)});
    if(next.length>30||next.some(t=>t.length>60)){tagStatus.textContent='Use up to 30 tags, each at most 60 characters.';return false}
    tags=next;renderTags();tagInput.value='';tagStatus.textContent='';dirty=true;return true;
  }
  componentForm.addEventListener('keydown',e=>{
    if(e.key==='Enter'&&!e.isComposing&&e.target.tagName==='INPUT'){
      e.preventDefault();if(e.target===tagInput)addTags();
    }
  });
  componentForm.addEventListener('submit',e=>{if(!addTags())e.preventDefault()});
  document.querySelector('#add-tag').addEventListener('click',()=>{addTags();tagInput.focus()});
  document.querySelectorAll('[data-tag]').forEach(button=>button.addEventListener('click',()=>{if(addTags())addTags(button.dataset.tag)}));
  document.querySelectorAll('[data-custom-choice]').forEach(select=>{
    const label=document.getElementById(select.dataset.customChoice),input=label.querySelector('input');
    function update(){const custom=select.value==='__new__';label.hidden=!custom;input.disabled=!custom;input.required=custom}
    select.addEventListener('change',update);update();
  });
  document.querySelectorAll('[data-create-dialog]').forEach(select=>{
    const dialog=document.getElementById(select.dataset.createDialog);
    let previous=select.value;
    select.addEventListener('change',()=>{
      if(select.value==='__new__'){select.value=previous;dialog.showModal()}
      else{previous=select.value;if(select.id==='storage-select')componentForm.elements.create_storage.value=select.value==='__pending_storage__'?'1':''}
    });
    dialog.querySelector('[data-close-dialog]').addEventListener('click',()=>dialog.close());
    dialog.querySelector('form').addEventListener('submit',e=>{
      e.preventDefault();
      const storage=select.id==='storage-select';
      const input=dialog.querySelector(storage?'#dialog-storage-name':'#dialog-category-name');
      const name=input.value.trim();if(!name){input.setCustomValidity('Enter a name.');input.reportValidity();return}
      input.setCustomValidity('');
      const value=storage?'__pending_storage__':name;
      let option=[...select.options].find(o=>o.value===value);
      if(!option){option=new Option(name,value);select.add(option,select.options.length-1)}
      option.textContent=name+(storage?' (new)':'');select.value=value;previous=value;
      if(storage){
        componentForm.elements.create_storage.value='1';componentForm.elements.new_location_name.value=name;
        componentForm.elements.new_location_kind.value=dialog.querySelector('#dialog-storage-kind').value;
        componentForm.elements.new_location_parent.value=dialog.querySelector('#dialog-storage-parent').value;
      }
      dirty=true;dialog.close();select.focus();
    });
    dialog.querySelector('input').addEventListener('input',e=>e.target.setCustomValidity(''));
  });
  renderTags();
}
document.querySelectorAll('.facet-search').forEach(input=>input.addEventListener('input',()=>{
  const query=input.value.trim().toLocaleLowerCase();input.closest('.facet').querySelectorAll('[data-facet-value]').forEach(row=>{row.hidden=!row.dataset.facetValue.includes(query)});
}));
const filterForm=document.querySelector('#inventory-filters');
if(filterForm){
  function renderFilterChips(){
    const chips=document.querySelector('#active-filters');chips.replaceChildren();const scope=filterForm.elements.location_scope;scope.hidden=!filterForm.elements.location_id.value;scope.disabled=scope.hidden;
    [...filterForm.elements].filter(el=>el.name&&el.value&&(!['checkbox','radio'].includes(el.type)||el.checked)&&!['sort','location_scope'].includes(el.name)).forEach(el=>{
      const button=document.createElement('button');button.type='button';button.className='secondary filter-chip';
      const value=el.tagName==='SELECT'?el.selectedOptions[0].textContent:el.value;
      button.textContent=value+' ×';button.setAttribute('aria-label','Remove filter '+value);
      button.addEventListener('click',()=>{if(el.type==='checkbox')el.checked=false;else el.value='';scheduleFilters();renderFilterChips()});chips.append(button);
    });
    document.querySelector('#filter-count').textContent=chips.children.length||'';
  }
  const status=document.querySelector('#filter-status'),results=document.querySelector('#inventory-results');
  let timer,controller,revision=0;
  async function applyFilters(version){
    controller=new AbortController();const url=filterForm.getAttribute('action')+'?'+new URLSearchParams(new FormData(filterForm));
    try{
      const response=await fetch(url,{signal:controller.signal});
      if(!response.ok)throw new Error('Request failed');
      const page=new DOMParser().parseFromString(await response.text(),'text/html');
      if(version!==revision)return;
      const next=page.querySelector('#inventory-results');if(!next)throw new Error('Sign in again');
      results.innerHTML=next.innerHTML;
      const storageContext=document.querySelector('#storage-context');if(storageContext)storageContext.innerHTML=page.querySelector('#storage-context')?.innerHTML||'';
      const choices=[...page.querySelectorAll('.filter-choice input')];
      filterForm.querySelectorAll('.filter-choice input').forEach(input=>{
        const match=choices.find(c=>c.name===input.name&&c.value===input.value);
        if(match){input.disabled=match.disabled;const count=input.closest('label').querySelector('small');if(count)count.textContent=match.closest('label').querySelector('small').textContent}
      });
      history.replaceState(null,'',url);renderFilterChips();status.textContent='';results.removeAttribute('aria-busy');
    }catch(error){if(error.name!=='AbortError'&&version===revision){status.textContent='Could not update filters. Change a selection or press Search to retry.';results.removeAttribute('aria-busy')}}
  }
  function scheduleFilters(){clearTimeout(timer);controller?.abort();const version=++revision;status.textContent='Updating results…';results.setAttribute('aria-busy','true');timer=setTimeout(()=>applyFilters(version),250)}
  filterForm.addEventListener('change',e=>{if(e.target.name)scheduleFilters()});
  filterForm.querySelector('[name="q"]').addEventListener('input',scheduleFilters);
  filterForm.addEventListener('submit',e=>{e.preventDefault();scheduleFilters()});
  renderFilterChips();
}
document.querySelector('#label-preset')?.addEventListener('change',e=>{if(e.target.value){const [w,h]=e.target.value.split(',');document.querySelector('#label-width').value=w;document.querySelector('#label-height').value=h;if(document.querySelector('#label-unit')?.value==='mm'){document.querySelector('#label-width').value=Number(w)*25.4;document.querySelector('#label-height').value=Number(h)*25.4}}});
const labelForm=document.querySelector('#label-form');
if(labelForm){
  const checkboxes=[...labelForm.querySelectorAll('[name="component_ids"]')];
  function countLabels(){const count=checkboxes.filter(c=>c.checked).length;document.querySelector('#label-count').textContent=`${count} ${count===1?'component':'components'} · ${count*Number(labelForm.elements.copies.value||0)} ${count*Number(labelForm.elements.copies.value||0)===1?'label':'labels'}`}
  document.querySelector('#select-all-labels').addEventListener('click',()=>{checkboxes.filter(c=>!c.closest('label').hidden).forEach(c=>c.checked=true);countLabels()});
  document.querySelector('#clear-labels').addEventListener('click',()=>{checkboxes.forEach(c=>c.checked=false);countLabels()});
  let batchEdited=false;labelForm.querySelector('.label-batch').addEventListener('change',e=>{if(e.target.name==='component_ids')batchEdited=true});['select-all-labels','clear-labels'].forEach(id=>document.getElementById(id).addEventListener('click',()=>{batchEdited=true}));document.querySelector('#label-component').addEventListener('change',e=>{if(!batchEdited){checkboxes.forEach(c=>c.checked=c.value===e.target.value);countLabels()}});
  const previewFrame=labelForm.querySelector('iframe'),status=document.querySelector('#preview-status');
  let timer,controller,revision=0;
  async function updatePreview(version){
    if(!labelForm.checkValidity()){status.textContent='Complete the label settings to update the preview.';return}
    controller=new AbortController();status.textContent='Updating preview…';
    const body=new FormData(labelForm);body.delete('component_ids');body.set('copies','1');
    try{
      const response=await fetch('/labels/pdf?preview=1&render=image',{method:'POST',body,signal:controller.signal});
      const html=await response.text();if(version!==revision)return;
      previewFrame.srcdoc=html;status.textContent=response.ok?'':'Preview could not be generated. Check the message below.';
    }catch(error){if(error.name!=='AbortError'&&version===revision)status.textContent='Could not update preview. Check your connection and try again.'}
  }
  function schedulePreview(immediate=false){clearTimeout(timer);controller?.abort();const version=++revision;status.textContent='Updating preview…';timer=setTimeout(()=>updatePreview(version),immediate?0:400)}
  function settingsChanged(e){countLabels();if(!['component_ids','copies'].includes(e.target.name))schedulePreview()}
  labelForm.addEventListener('input',settingsChanged);
  labelForm.addEventListener('change',settingsChanged);
  labelForm.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();schedulePreview(true)}});
  labelForm.addEventListener('submit',e=>{
    if(!checkboxes.some(c=>c.checked)){e.preventDefault();alert('Select at least one component.');}
  });
  countLabels();
}

const settingsForm=document.querySelector('#appearance-settings');
settingsForm?.querySelectorAll('[name="palette"]').forEach(input=>input.addEventListener('change',()=>document.body.dataset.palette=input.value));
settingsForm?.querySelectorAll('[data-move]').forEach(button=>button.addEventListener('click',()=>{const row=button.closest('.sidebar-preference'),other=button.dataset.move==='up'?row.previousElementSibling:row.nextElementSibling;if(other){if(button.dataset.move==='up')other.before(row);else other.after(row);button.focus()}}));

const fixedFooter=document.querySelector('footer');
if(fixedFooter)new ResizeObserver(()=>document.documentElement.style.setProperty('--footer-height',fixedFooter.offsetHeight+'px')).observe(fixedFooter);

// Open a collapsed optional section when native validation finds an error.
document.addEventListener('invalid',e=>{let section=e.target.closest('details');while(section){section.open=true;section=section.parentElement.closest('details')}},true);
document.querySelectorAll('[data-show-password]').forEach(toggle=>toggle.addEventListener('change',()=>toggle.closest('form').querySelectorAll('[name=password],[name=password_confirm]').forEach(input=>input.type=toggle.checked?'text':'password')));
document.querySelectorAll('[data-local-time]').forEach(el=>{const date=new Date(el.dateTime.replace(' ','T'));if(!Number.isNaN(date.getTime()))el.textContent=new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'long'}).format(date)});
const storageSearch=document.querySelector('#storage-search');
storageSearch?.addEventListener('input',()=>{const q=storageSearch.value.toLocaleLowerCase().trim();document.querySelectorAll('.storage-node').forEach(node=>{node.hidden=!node.dataset.storagePath.includes(q)&&![...node.querySelectorAll('.storage-node')].some(child=>child.dataset.storagePath.includes(q));if(q)node.querySelectorAll('details:not(.storage-edit)').forEach(d=>d.open=true)})});
const buildForm=document.querySelector('#build-form');
if(buildForm){
 const count=buildForm.elements.build_count,parts=[...buildForm.querySelectorAll('[data-build-part]')],status=document.querySelector('#build-readiness'),button=buildForm.querySelector('button');
 function updateBuild(){const n=Number(count.value),missing=[];parts.forEach(row=>{const required=Number(row.dataset.quantity)*n,shortage=Math.max(0,required-Number(row.dataset.stock));row.textContent=`${required.toLocaleString()} ${row.dataset.unit} · ${row.dataset.name}`;row.classList.toggle('low-stock',shortage>0);if(shortage)missing.push(`${shortage.toLocaleString()} ${row.dataset.unit==='pcs'&&shortage===1?'pc':row.dataset.unit} of ${row.dataset.name}`)});button.disabled=!count.checkValidity()||!count.value||missing.length>0;status.dataset.ready=String(!button.disabled);status.textContent=missing.length?'Cannot build yet: missing '+missing.join(', '):button.disabled?'Choose a valid build quantity.':'Ready to build.';return !button.disabled}
 count.addEventListener('input',updateBuild);buildForm.addEventListener('submit',e=>{if(!updateBuild()||!confirm('Deduct these parts?\n'+parts.map(row=>row.textContent).join('\n')))e.preventDefault()});
}
if(labelForm){
 const unit=document.querySelector('#label-unit'),dimensions=[...labelForm.querySelectorAll('[name=width],[name=height],[name^=margin_]')];let previousUnit='in';
 unit.addEventListener('change',()=>{const factor=unit.value==='mm'?25.4:1/25.4;if(unit.value!==previousUnit)dimensions.forEach(input=>{input.value=Number((Number(input.value)*factor).toFixed(6));input.min=Number(input.min)*factor;input.max=Number(input.max)*factor;input.step='any'});previousUnit=unit.value;document.querySelectorAll('[data-dimension-unit]').forEach(el=>el.textContent=unit.value);labelForm.dispatchEvent(new Event('input',{bubbles:true}))});
 const text=document.querySelector('#label-text');
 document.querySelector('#label-field').addEventListener('change',e=>{if(e.target.value){text.setRangeText(e.target.value,text.selectionStart,text.selectionEnd,'end');e.target.value='';text.focus();text.dispatchEvent(new Event('input',{bubbles:true}))}});
 document.querySelector('#label-starter').addEventListener('change',e=>{if(e.target.value){text.value=e.target.value;text.dispatchEvent(new Event('input',{bubbles:true}))}});
 const search=document.querySelector('#label-search'),category=document.querySelector('#label-category');
 function filterLabels(){const query=search.value.trim().toLocaleLowerCase();labelForm.querySelectorAll('.bulk-list label').forEach(row=>row.hidden=!row.textContent.toLocaleLowerCase().includes(query)||(category.value&&row.dataset.labelCategory!==category.value))}
 search.addEventListener('input',filterLabels);category.addEventListener('change',filterLabels);
 function encoded(){const option=document.querySelector('#label-component').selectedOptions[0],target=document.querySelector('#encoded-value');target.replaceChildren(document.createTextNode(labelForm.elements.mode.value==='none'?'No code':'Encoded value'));if(labelForm.elements.mode.value!=='none'){const code=document.createElement('code');code.textContent=option.dataset.code;target.append(code)}const context=document.createElement('span');context.className='encoded-context';context.textContent=option.textContent;target.append(context)}
 document.querySelector('#label-component').addEventListener('change',encoded);labelForm.elements.mode.addEventListener('change',encoded);encoded();
}

const addProjectForm=document.querySelector('#add-project-form');
if(addProjectForm){function projectQuantity(){const current=Number(addProjectForm.elements.project_id.selectedOptions[0].dataset.quantity),added=Number(addProjectForm.elements.quantity.value);document.querySelector('#project-quantity-result').textContent=`Currently ${current.toLocaleString()} required → ${(current+added).toLocaleString()} after adding.`}addProjectForm.addEventListener('input',projectQuantity);addProjectForm.addEventListener('change',projectQuantity);projectQuantity()}

const menuToggle=document.querySelector('.mobile-menu-toggle');
if(menuToggle){const sidebar=menuToggle.closest('.sidebar');function closeMenu(){sidebar.classList.remove('menu-open');menuToggle.setAttribute('aria-expanded','false')}
 menuToggle.addEventListener('click',()=>{const open=sidebar.classList.toggle('menu-open');menuToggle.setAttribute('aria-expanded',String(open))});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&sidebar.classList.contains('menu-open')){closeMenu();menuToggle.focus()}})}
document.addEventListener('change',e=>{if(e.target.id==='show-extra-columns')document.querySelector('.inventory-table')?.classList.toggle('show-extra',e.target.checked)});
if(labelForm){function syncPreset(){const scale=labelForm.elements.dimension_unit.value==='mm'?25.4:1,w=Number(labelForm.elements.width.value)/scale,h=Number(labelForm.elements.height.value)/scale,preset=document.querySelector('#label-preset');preset.value=[...preset.options].find(o=>o.value&&Math.abs(Number(o.value.split(',')[0])-w)<.00001&&Math.abs(Number(o.value.split(',')[1])-h)<.00001)?.value||'';const starter=document.querySelector('#label-starter');starter.value=[...starter.options].find(o=>o.value===labelForm.elements.text.value)?.value||''}labelForm.addEventListener('input',e=>{if(!['label-starter','label-preset'].includes(e.target.id))syncPreset()});labelForm.addEventListener('change',syncPreset);syncPreset()}

const footerMore=document.querySelector('.footer-more');
if(footerMore){document.addEventListener('click',e=>{if(!footerMore.contains(e.target))footerMore.open=false});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&footerMore.open){footerMore.open=false;footerMore.querySelector('summary').focus()}})}

const stockToggle=document.querySelector('#stock-toggle'),stockPanel=document.querySelector('#adjust-stock');
if(stockToggle&&stockPanel){const mobile=matchMedia('(max-width:700px)');function showStock(open){stockPanel.hidden=!open;stockToggle.setAttribute('aria-expanded',String(open))}function stockLayout(){showStock(!mobile.matches)}stockLayout();mobile.addEventListener('change',stockLayout);stockToggle.addEventListener('click',()=>{const open=mobile.matches?stockPanel.hidden:true;showStock(open);if(open){stockPanel.scrollIntoView({block:'nearest',behavior:'smooth'});stockPanel.querySelector('[name=quantity]').focus({preventScroll:true})}})}
