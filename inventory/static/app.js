const savedTheme=localStorage.getItem('partshelf-theme');
document.body.dataset.theme=savedTheme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
document.querySelector('#theme-toggle')?.addEventListener('click',()=>{const theme=document.body.dataset.theme==='dark'?'light':'dark';document.body.dataset.theme=theme;localStorage.setItem('partshelf-theme',theme)});
let dirty=false;document.addEventListener('input',()=>{dirty=true});
if(document.querySelector('[data-auto-refresh]'))setInterval(()=>{if(!dirty&&!document.hidden&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName))location.reload()},20000);
document.querySelectorAll('form[data-confirm]').forEach(form=>form.addEventListener('submit',e=>{if(!confirm(form.dataset.confirm))e.preventDefault()}));
const partName=document.querySelector('#part-name'),partId=document.querySelector('#part-id');
if(partName&&partId){let manual=Boolean(partId.value&&partId.value!==partName.value);partId.addEventListener('input',()=>manual=Boolean(partId.value));partName.addEventListener('input',()=>{if(!manual)partId.value=partName.value})}
function prices(){const price=document.querySelector('#price');if(!price)return;const quantity=Number(document.querySelector('#purchase-quantity').value);const amount=Number(price.value);const purchase=document.querySelector('#price-mode').value==='purchase';document.querySelector('#price-summary').textContent=purchase?`Unit price: ${quantity>0?(amount/quantity).toFixed(6):'enter quantity'}`:`Purchase total: ${(amount*quantity).toFixed(2)}`}
['price','purchase-quantity','price-mode'].forEach(id=>document.getElementById(id)?.addEventListener('input',prices));prices();
document.querySelector('#label-preset')?.addEventListener('change',e=>{if(e.target.value){const [w,h]=e.target.value.split(',');document.querySelector('#label-width').value=w;document.querySelector('#label-height').value=h}});
document.querySelector('#label-component')?.addEventListener('change',e=>{const option=e.target.selectedOptions[0];document.querySelector('#label-text').value=option.dataset.name+(option.dataset.identifier!==option.dataset.name?'\n'+option.dataset.identifier:'')});
function fitLabels(){document.querySelectorAll('.label-text').forEach(el=>{let size=parseFloat(getComputedStyle(el.parentElement).fontSize);el.style.fontSize=size+'px';while((el.scrollHeight>el.clientHeight||el.scrollWidth>el.clientWidth)&&size>3){size-=.5;el.style.fontSize=size+'px'}})}
window.addEventListener('load',fitLabels);window.addEventListener('beforeprint',fitLabels);document.querySelector('#print-labels')?.addEventListener('click',()=>{fitLabels();window.print()});
