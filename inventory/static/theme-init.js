try{document.documentElement.dataset.theme=localStorage.getItem('partshelf-theme')||'light'}catch{document.documentElement.dataset.theme='light'}
const themeObserver=new MutationObserver(()=>{if(document.body){document.body.dataset.theme=document.documentElement.dataset.theme;themeObserver.disconnect()}});themeObserver.observe(document.documentElement,{childList:true});
