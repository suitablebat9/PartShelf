// Anonymous session counts; only report visible pages, never an account or IP.
const visitRoot=document.querySelector('[data-track-visits="1"]');
if(visitRoot && navigator.doNotTrack!=='1' && !navigator.globalPrivacyControl){
  async function pulse(){
    if(document.visibilityState!=='visible')return;
    try{await fetch('/visitor-pulse',{method:'POST',headers:{'X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:new URLSearchParams({mode:visitRoot.dataset.visitMode})});}catch{}
  }
  pulse();setInterval(pulse,30000);document.addEventListener('visibilitychange',pulse);
}
const traffic=document.querySelector('#visitor-analytics');
if(traffic){
  async function refreshTraffic(){
    if(document.visibilityState!=='visible')return;
    try{
      const response=await fetch('/management/analytics/live');if(!response.ok)throw new Error();
      const data=await response.json();
      traffic.querySelectorAll('[data-metric]').forEach(el=>{el.textContent=data[el.dataset.metric].toLocaleString()});
      document.querySelector('#traffic-status').textContent='Updated '+new Date().toLocaleTimeString();
    }catch{document.querySelector('#traffic-status').textContent='Could not refresh visitor counts. Reconnecting…';}
  }
  setInterval(refreshTraffic,15000);document.addEventListener('visibilitychange',refreshTraffic);
}
