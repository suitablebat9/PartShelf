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
document.querySelectorAll('[data-tag]').forEach(button=>button.addEventListener('click',()=>{
  const input=document.querySelector('#part-tags');
  const tags=input.value.split(',').map(t=>t.trim()).filter(Boolean);
  if(!tags.some(t=>t.toLocaleLowerCase()===button.dataset.tag.toLocaleLowerCase()))tags.push(button.dataset.tag);
  input.value=tags.join(', ');dirty=true;
}));
document.querySelector('#label-preset')?.addEventListener('change',e=>{if(e.target.value){const [w,h]=e.target.value.split(',');document.querySelector('#label-width').value=w;document.querySelector('#label-height').value=h}});
const labelForm=document.querySelector('#label-form');
if(labelForm){
  const checkboxes=[...labelForm.querySelectorAll('[name="component_ids"]')];
  function countLabels(){const count=checkboxes.filter(c=>c.checked).length;document.querySelector('#label-count').textContent=`${count} components · ${count*Number(labelForm.elements.copies.value||0)} labels`}
  document.querySelector('#select-all-labels').addEventListener('click',()=>{checkboxes.forEach(c=>c.checked=true);countLabels()});
  document.querySelector('#clear-labels').addEventListener('click',()=>{checkboxes.forEach(c=>c.checked=false);countLabels()});
  labelForm.addEventListener('input',()=>{countLabels();document.querySelector('#preview-status').textContent='Settings changed — update preview to see the current layout.'});
  labelForm.addEventListener('submit',e=>{
    if(e.submitter?.getAttribute('formtarget')==='label-preview')document.querySelector('#preview-status').textContent='Preview requested with current settings.';
    else if(!checkboxes.some(c=>c.checked)){e.preventDefault();alert('Select at least one component.');}
  });
  countLabels();
}
