const savedTheme=localStorage.getItem('partshelf-theme');
document.body.dataset.theme=savedTheme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
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
  if(quantity>0){
    if(mode==='purchase')unitPrice.value=String(Number((Number(purchaseTotal.value||0)/quantity).toFixed(6)));
    else purchaseTotal.value=String(Number((Number(unitPrice.value||0)*quantity).toFixed(6)));
    document.querySelector('#price-summary').textContent=`${quantity} × ${unitPrice.value||0} per unit = ${purchaseTotal.value||0} purchase total`;
  }else document.querySelector('#price-summary').textContent='Enter the original purchase quantity to calculate both prices.';
}
if(purchaseQty){
  let manualQuantity=Boolean(purchaseQty.value);
  purchaseQty.addEventListener('input',()=>{manualQuantity=true;prices()});
  unitPrice.addEventListener('input',()=>{priceMode.value='unit';prices()});
  purchaseTotal.addEventListener('input',()=>{priceMode.value='purchase';prices()});
  priceMode.addEventListener('change',prices);
  document.querySelector('#stock').addEventListener('input',e=>{if(document.querySelector('#component-form').dataset.new==='true'&&!manualQuantity){purchaseQty.value=e.target.value;prices()}});
  prices();
}
document.querySelector('#create-storage')?.addEventListener('change',e=>{
  document.querySelector('#new-storage-fields').hidden=!e.target.checked;
  document.querySelector('[name="new_location_name"]').required=e.target.checked;
  document.querySelector('[name="location_id"]').disabled=e.target.checked;
});
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
  renderTags();
}
document.querySelectorAll('.facet-search').forEach(input=>input.addEventListener('input',()=>{
  const query=input.value.trim().toLocaleLowerCase();input.closest('.facet').querySelectorAll('[data-facet-value]').forEach(row=>{row.hidden=!row.dataset.facetValue.includes(query)});
}));
document.querySelector('#label-preset')?.addEventListener('change',e=>{if(e.target.value){const [w,h]=e.target.value.split(',');document.querySelector('#label-width').value=w;document.querySelector('#label-height').value=h}});
const labelForm=document.querySelector('#label-form');
if(labelForm){
  const checkboxes=[...labelForm.querySelectorAll('[name="component_ids"]')];
  function countLabels(){const count=checkboxes.filter(c=>c.checked).length;document.querySelector('#label-count').textContent=`${count} components · ${count*Number(labelForm.elements.copies.value||0)} labels`}
  document.querySelector('#select-all-labels').addEventListener('click',()=>{checkboxes.forEach(c=>c.checked=true);countLabels()});
  document.querySelector('#clear-labels').addEventListener('click',()=>{checkboxes.forEach(c=>c.checked=false);countLabels()});
  const previewFrame=labelForm.querySelector('iframe'),status=document.querySelector('#preview-status');
  let timer,controller,revision=0;
  async function updatePreview(version){
    if(!labelForm.checkValidity()){status.textContent='Complete the label settings to update the preview.';return}
    controller=new AbortController();status.textContent='Updating preview…';
    const body=new FormData(labelForm);body.delete('component_ids');body.set('copies','1');
    try{
      const response=await fetch('/labels/pdf?preview=1&render=image',{method:'POST',body,signal:controller.signal});
      const html=await response.text();if(version!==revision)return;
      previewFrame.srcdoc=html;status.textContent=response.ok?'Preview is up to date.':'Preview could not be generated. Check the message below.';
    }catch(error){if(error.name!=='AbortError'&&version===revision)status.textContent='Could not update preview. Check your connection and try again.'}
  }
  function schedulePreview(immediate=false){clearTimeout(timer);controller?.abort();const version=++revision;status.textContent='Updating preview…';timer=setTimeout(()=>updatePreview(version),immediate?0:400)}
  function settingsChanged(e){countLabels();if(!['component_ids','copies'].includes(e.target.name))schedulePreview()}
  labelForm.addEventListener('input',settingsChanged);
  labelForm.addEventListener('change',settingsChanged);
  labelForm.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();schedulePreview(true)}});
  labelForm.addEventListener('submit',e=>{
    if(e.submitter?.getAttribute('formtarget')==='label-preview'){e.preventDefault();schedulePreview(true)}
    else if(!checkboxes.some(c=>c.checked)){e.preventDefault();alert('Select at least one component.');}
  });
  countLabels();
}
