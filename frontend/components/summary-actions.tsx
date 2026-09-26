'use client';
import {useState} from 'react';
import {Data,money} from './api';

type Props={detail:Data; open:(tab:string)=>void};
export default function SummaryActions({detail,open}:Props){
 const [copied,setCopied]=useState(false),[copyError,setCopyError]=useState(false);
 const missing=(detail.document_checklist||[]).filter((d:Data)=>!d.received);
 const unverified=detail.unverified||[];
 const rules=detail.financial?.rules||[];
 const checks=rules.filter((r:Data)=>r.result==='fail'||r.result==='unable_to_assess');
 const rankMissing=rules.some((r:Data)=>r.result==='unable_to_assess'&&r.condition?.field==='commercial_cibil_rank');
 const limit=detail.financial?.metrics?.find((m:Data)=>m.key==='eligible_limit')?.value;
 const overLimit=limit!=null&&Number(detail.application.amount)>Number(limit);
 const requests=[...missing.map((d:Data)=>d.label),...(rankMissing?['Business credit report / explanation if no commercial rank is available']:[])];
 const draft=`Information required for ${detail.application.borrower}:\n${requests.map((s:string)=>'• '+s).join('\n')}\nPlease provide the documents or explain why they are unavailable.`;
 return <section className="panel summary-actions" aria-label="What needs attention"><div className="panel-heading"><div><h2>What needs attention</h2><p>Quick review · Assigned to {detail.application.owner||'Unassigned'}</p></div><button className="btn small-btn" onClick={()=>open('appraisal')}>Full appraisal →</button></div>
 <div className="summary-action-grid"><div className={requests.length?'summary-action request':'summary-action clear'}><strong>{requests.length?`${requests.length} items to request`:'No missing documents flagged'}</strong><p>{requests.length?requests.join(' · '):'Check verification and policy concerns before deciding.'}</p><button className="text-link" onClick={()=>open('documents')}>Review documents →</button>{requests.length>0&&<button className="btn small-btn" onClick={async()=>{try{await navigator.clipboard.writeText(draft);setCopied(true);setCopyError(false)}catch{setCopyError(true)}}}>{copied?'Request list copied':'Copy request list'}</button>}<span role="status">{copyError?'Could not copy. Select the request items above to copy them.':''}</span></div>
 <div className={unverified.length?'summary-action verify':'summary-action clear'}><strong>{unverified.length} inputs to verify</strong><p>{unverified.length?unverified.map((key:string)=>key.replaceAll('_',' ')).join(' · '):'No unverified extracted inputs flagged.'}</p><button className="text-link" onClick={()=>open('documents')}>Verify evidence →</button></div>
 <div className={checks.length||overLimit?'summary-action concern':'summary-action clear'}><strong>{checks.length} policy checks need review</strong><p>{overLimit?`${money(detail.application.amount)} requested · ${money(limit)} indicative limit. Review the proposed amount.`:checks.length?'Review failed checks and checks with missing information.':'No failed or incomplete checks in the current calculation.'}</p><button className="text-link" onClick={()=>open(overLimit?'financials':'appraisal')}>{overLimit?'Review eligible limit':'Review policy checks'} →</button></div></div>
 <div className="note">{detail.application.assessment_stale?'Evidence has changed. Review the updated assessment before deciding.':'These are review prompts, not an approval.'} Copying a request list does not send it to the customer.</div></section>
}
