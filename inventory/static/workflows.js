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
 document.addEventListener('click',e=>{const quick=e.target.closest('[data-quick-stock]');if(!quick)return;
 const dialog=document.createElement('dialog'),name=quick.closest('tr').querySelector('.item-name').textContent;
 dialog.innerHTML='<form method="post" action="/inventory/bulk"><h2>Adjust stock</h2><p class="quick-part"></p><input type="hidden" name="csrf"><input type="hidden" name="component_ids"><label>Action<select name="action"><option value="stock_add">Add stock</option><option value="stock_remove">Remove stock</option></select></label><label>Quantity<input name="quantity" type="number" min="0.000001" step="any" required></label><label>Reason (optional)<input name="reason" maxlength="500"></label><div class="actions"><button type="button" class="secondary" data-cancel>Cancel</button><button>Preview change</button></div></form>';
 dialog.querySelector('.quick-part').textContent=name;dialog.querySelector('[name=csrf]').value=document.querySelector('meta[name=csrf-token]').content;dialog.querySelector('[name=component_ids]').value=quick.dataset.quickStock;dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{dialog.remove();quick.focus()});document.body.append(dialog);dialog.showModal();dialog.querySelector('[name=quantity]').focus();
 });
 const results=document.querySelector('#inventory-results');if(results){new MutationObserver(refreshBulk).observe(results,{childList:true});refreshBulk()}
})();
