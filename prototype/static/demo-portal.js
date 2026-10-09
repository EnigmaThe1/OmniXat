'use strict';
const form=document.getElementById('demo-form');
const review=document.getElementById('review-section');
const receipt=document.getElementById('receipt-section');
const fields=['company','period','amount'];
form.addEventListener('submit', event=>{
  event.preventDefault();
  if(!form.reportValidity())return;
  for(const k of fields)document.getElementById('review-'+k).textContent=document.getElementById(k).value;
  form.hidden=true;review.hidden=false;
});
document.getElementById('demo-submit').addEventListener('click',async()=>{
  const id=window.fixtureRunId || new URL(location.href).searchParams.get('run_id');
  const data=Object.fromEntries(fields.map(k=>[k,document.getElementById(k).value]));
  try{
    const r=await fetch('/api/demo-portal/submissions',{method:'POST',headers:{'Content-Type':'application/json','X-OmniXat-Demo':'1'},body:JSON.stringify({run_id:id, ...data})});
    const payload=await r.json();if(!r.ok)throw Error(payload.error||'Could not save practice submission');
    document.getElementById('receipt-id').textContent=payload.receipt;
    review.hidden=true;receipt.hidden=false;
  }catch(e){alert(e.message);}
});
