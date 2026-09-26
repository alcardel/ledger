import {notFound} from 'next/navigation';
import Home from '../page';
const modules=['credit-overview','approval-workbench','loan-origination','document-review','financial-spreading','cash-flow','exceptions-referrals','employee-assignments','loan-products','credit-policy','administration'];
export default async function Workspace({params}:{params:Promise<{workspace:string[]}>}){
 const {workspace}=await params;
 if(!modules.includes(workspace[0]) || (workspace.length!==1 && !(workspace.length===4 && workspace[1]==='applications' && ['summary','documents','financials','cashflow','appraisal','history'].includes(workspace[3]))))notFound();
 return <Home/>;
}
