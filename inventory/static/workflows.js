(()=>{
 function refreshBulk(){
  const form=document.querySelector('#bulk-form');if(!form)return;
  const choices=[...document.querySelectorAll('[data-bulk-select]')],count=choices.filter(el=>el.checked).length,action=form.elements.action.value;
  document.querySelector('#bulk-count').textContent=`${count} selected`;
  document.querySelector('#bulk-submit').disabled=!count;
  form.closest('.bulk-tools').hidden=!count;
  document.querySelectorAll('[data-bulk-field]').forEach(label=>{const active=action.startsWith(label.dataset.bulkField);label.hidden=!active;label.querySelectorAll('input,select').forEach(input=>{input.disabled=!active;input.required=active&&['quantity','tags'].includes(input.name)})});
  const all=document.querySelector('#bulk-select-all');if(all){all.checked=count>0&&count===choices.length;all.indeterminate=count>0&&count<choices.length}
 }
 document.addEventListener('change',e=>{if(e.target.id==='bulk-select-all')document.querySelectorAll('[data-bulk-select]').forEach(input=>input.checked=e.target.checked);if(e.target.closest('#inventory-results'))refreshBulk()});
 document.addEventListener('click',e=>{const quick=e.target.closest('[data-quick-stock]');if(!quick)return;document.querySelectorAll('[data-bulk-select]').forEach(input=>input.checked=input.value===quick.dataset.quickStock);const form=document.querySelector('#bulk-form');form.elements.action.value='stock_add';refreshBulk();form.scrollIntoView({block:'center',behavior:'smooth'});form.elements.quantity.focus()});
 const results=document.querySelector('#inventory-results');if(results){new MutationObserver(refreshBulk).observe(results,{childList:true});refreshBulk()}
})();
