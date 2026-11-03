'use strict';
const crypto=require('node:crypto');
const MASK='[已配置]',PREFIX='portal-login-handoff:';
const handoffs=new Map();
const secrets=new Set(['token','accesstoken','refreshtoken','password','cookie','cookies','authorization','apikey','secret']);
const isSecret=key=>secrets.has(key.toLowerCase().replace(/[_-]/g,''));
function handoff(vid,token){
 const now=Date.now();
 for(const [key,value]of handoffs)if(value.expires<=now)handoffs.delete(key);
 for(const [key,value]of handoffs)if(value.vid===String(vid)&&value.token===token)return key;
 if(handoffs.size>=128)handoffs.delete(handoffs.keys().next().value);
 const key=PREFIX+crypto.randomBytes(24).toString('hex');
 handoffs.set(key,{vid:String(vid),token,expires:now+5*60*1000});return key;
}
function redact(value){
 if(Array.isArray(value))return value.map(redact);
 if(!value||typeof value!=='object'||value instanceof Date||Buffer.isBuffer(value))return value;
 // Preserve native QR-login flow with an opaque server-side handoff, never the credential.
 if(value.code===-32603||value.data?.code==='INTERNAL_SERVER_ERROR')value={...value,message:'处理失败，请稍后重试'};
 const loginToken=value.vid&&typeof value.token==='string'&&value.token&&value.token!==MASK?(value.token.startsWith(PREFIX)?value.token:handoff(value.vid,value.token)):null;
 return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,key==='token'&&loginToken?loginToken:isSecret(key)&&item?MASK:redact(item)]));
}
function preserveMasked(value){
 if(!value||typeof value!=='object')return value;
 if(typeof value.token==='string'&&value.token.startsWith(PREFIX)){
  const record=handoffs.get(value.token);
  if(!record||record.expires<=Date.now()||String(value.id)!==record.vid)throw new Error('login handoff expired or invalid');
  value.token=record.token;
 }
 for(const key of Object.keys(value)){
  if(isSecret(key)&&value[key]===MASK)delete value[key];
  else preserveMasked(value[key]);
 }
 return value;
}
function install(app){
 if(process.env.SCHOOLSEARCH_PUBLIC_WORKSPACE!=='1')return;
 app.use((req,res,next)=>{
  if(['POST','PUT','PATCH','DELETE'].includes(req.method)&&req.headers.origin&&req.headers.origin!==(process.env.SCHOOLSEARCH_PUBLIC_ORIGIN||'https://schoolsearchzzychen.online')){
   res.status(403).json({error:'origin not allowed'});return;
  }
  try{preserveMasked(req.body);}catch(_){res.status(400).json({error:'login handoff expired or invalid'});return;}
  const json=res.json.bind(res);
  res.json=value=>json(redact(value));
  res.setHeader('Cache-Control','no-store');
  next();
 });
}
module.exports={redact,preserveMasked,install,MASK};
