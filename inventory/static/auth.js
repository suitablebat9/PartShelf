// Passkey credentials stay in the authenticator. Only public verification data is sent.
function decodeBase64url(value){return Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4)),c=>c.charCodeAt(0))}
function encodeBase64url(value){return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'')}
async function authPost(url,body){
  const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify(body)});
  if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('Sign in again and retry from Account & security.');
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not complete the request.');return data;
}
document.querySelectorAll('[data-passkey]').forEach(button=>button.addEventListener('click',async()=>{
  const status=document.querySelector('#passkey-status');button.disabled=true;status.textContent='Follow your device’s passkey prompt…';
  try{
    if(!window.PublicKeyCredential||!window.isSecureContext)throw new Error('Passkeys need a supported browser and the HTTPS website address.');
    const register=button.dataset.passkey==='register',prefix=register?'/account/passkey':'/auth/passkey';
    const options=await authPost(prefix+'/options',{remember:document.querySelector('#remember-login')?.checked||false});
    options.challenge=decodeBase64url(options.challenge);
    if(options.user)options.user.id=decodeBase64url(options.user.id);
    for(const key of ['allowCredentials','excludeCredentials'])if(options[key])options[key].forEach(c=>c.id=decodeBase64url(c.id));
    const result=register?await navigator.credentials.create({publicKey:options}):await navigator.credentials.get({publicKey:options});
    if(!result)throw new Error('Passkey request was cancelled.');
    const response={clientDataJSON:encodeBase64url(result.response.clientDataJSON)};
    for(const field of ['attestationObject','authenticatorData','signature','userHandle'])if(result.response[field])response[field]=encodeBase64url(result.response[field]);
    if(result.response.getTransports)response.transports=result.response.getTransports();
    const credential={id:result.id,rawId:encodeBase64url(result.rawId),type:result.type,response,clientExtensionResults:result.getClientExtensionResults()};
    const data=await authPost(prefix+'/verify',{credential,name:document.querySelector('#passkey-name')?.value||'My device'});
    location.assign(data.redirect);
  }catch(error){status.textContent=error.name==='NotAllowedError'?'Passkey request cancelled or unavailable. You can try again or use your password.':error.message;button.disabled=false}
}));
