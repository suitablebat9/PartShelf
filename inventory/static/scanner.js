(()=>{
 const video=document.querySelector('#scan-video'),status=document.querySelector('#scan-status'),start=document.querySelector('#scan-start'),stopButton=document.querySelector('#scan-stop'),photo=document.querySelector('#scan-photo'),result=document.querySelector('#scan-result');
 if(!video)return;
 let stream=null,controls=null,generation=0;
 function stop(message){generation++;controls?.stop();controls=null;stream?.getTracks().forEach(track=>track.stop());stream=null;video.srcObject=null;video.hidden=true;document.querySelector('#camera-placeholder').hidden=false;start.disabled=false;stopButton.disabled=true;if(message)status.textContent=message}
 function decoded(text){if(text.length>512){stop('This code is too long for a Partshelf identifier.');return}result.value=text;stop('Code found. Review it below, then choose Find component.');result.focus()}
 start.addEventListener('click',async()=>{
  stop();const current=generation;start.disabled=true;stopButton.disabled=false;status.textContent='Allow camera access to scan a label.';
  if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){stop('Camera access is unavailable. Use HTTPS, choose a photo, or enter the code.');return}
  try{
   const media=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});
   if(current!==generation){media.getTracks().forEach(track=>track.stop());return}stream=media;video.hidden=false;document.querySelector('#camera-placeholder').hidden=true;
   const reader=new ZXingBrowser.BrowserMultiFormatReader();
   const next=await reader.decodeFromStream(media,video,(scan,error,active)=>{if(scan&&current===generation){active.stop();decoded(scan.getText())}});
   if(current!==generation)next.stop();else{controls=next;status.textContent='Point the camera at a QR code or barcode.'}
  }catch(error){if(current===generation)stop(error.name==='NotAllowedError'?'Camera permission was denied. Allow it in browser settings, choose a photo, or enter the code.':'Could not start the camera. Choose a photo or enter the code instead.')}
 });
 stopButton.addEventListener('click',()=>stop('Camera stopped.'));
 photo.addEventListener('change',async()=>{stop();const file=photo.files[0];if(!file)return;if(file.size>8*1024*1024){status.textContent='Choose an image smaller than 8 MB.';return}const current=generation,url=URL.createObjectURL(file);status.textContent='Reading photo…';try{const reader=new ZXingBrowser.BrowserMultiFormatReader();const scan=await reader.decodeFromImageUrl(url);if(current===generation)decoded(scan.getText())}catch{if(current===generation)status.textContent='No readable code found. Try a sharper photo with the full label visible.'}finally{URL.revokeObjectURL(url);photo.value=''}});
 window.addEventListener('pagehide',()=>stop());document.addEventListener('visibilitychange',()=>{if(document.hidden)stop('Camera stopped while this page is hidden.')});
})();
