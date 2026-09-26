export type Data = Record<string, any>;
export const API=process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
let role='org_admin';
export function setRole(value:string){role=value;}
export function headers(){return {'Authorization':`Bearer ${process.env.NEXT_PUBLIC_DEMO_TOKEN || 'local-demo-change-me'}`,'X-Demo-Role':role};}
export async function api(path:string, body?:unknown, method?:string,idempotencyKey?:string):Promise<any>{
 const form=body instanceof FormData;
 const res=await fetch(API+path,{method:method || (body!==undefined?'POST':'GET'),credentials:'include',headers:{...headers(),...(form?{}:{'Content-Type':'application/json'}),...(body!==undefined?{'Idempotency-Key':idempotencyKey||crypto.randomUUID()}: {})},body:body===undefined?undefined:form?body:JSON.stringify(body)});
 if(!res.ok){const data=await res.json().catch(()=>({detail:'Request failed'}));throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));}
 return res.json();
}
export async function documentURL(id:string){const r=await fetch(`${API}/documents/${id}/content`,{headers:headers(),credentials:'include'});if(!r.ok)throw new Error('Unable to load source document');return URL.createObjectURL(await r.blob());}
export async function followJob(id:string,onUpdate:(v:Data)=>void){
 const r=await fetch(`${API}/jobs/${id}/events`,{headers:headers(),credentials:'include'});if(!r.ok||!r.body)throw new Error('Unable to follow processing job');
 const reader=r.body.getReader();let buffer='';const decoder=new TextDecoder();
 while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let boundary;while((boundary=buffer.indexOf('\n\n'))!==-1){const line=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);if(line.startsWith('data: '))onUpdate(JSON.parse(line.slice(6)));}}
}
export const money=(n:unknown,compact=false)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:compact?1:0,...(compact?{notation:'compact' as const}:{})}).format(Number(n||0));
export const label=(s:string)=>s?.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase())||'—';
export const day=(s:string)=>new Date(s).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'});
