from dataclasses import dataclass
import secrets
import httpx
import jwt
from fastapi import HTTPException, Request
from .config import settings

ROLES = ['org_admin','relationship_manager','credit_analyst','credit_approver','policy_manager','risk_reviewer']
GRANTS = {
    'relationship_manager': {'read','originate','upload','resolve'},
    'credit_analyst': {'read','originate','upload','review','assess','resolve'},
    'credit_approver': {'read','decide','publish'},
    'policy_manager': {'read','policy','publish'},
    'risk_reviewer': {'read','resolve'},
    'org_admin': {'read','originate','upload','review','assess','resolve','decide','policy','publish','override','admin'},
}
@dataclass
class Actor:
    id: str
    org: str
    role: str
    name: str
    def require(self, permission):
        if permission not in GRANTS.get(self.role, set()):
            raise HTTPException(403, f'{permission} permission required')

async def actor(request: Request):
    if settings.auth_mode == 'demo':
        token = request.headers.get('authorization', '').removeprefix('Bearer ')
        if not settings.demo_token or not secrets.compare_digest(token, settings.demo_token):
            raise HTTPException(401, 'Local demo token required')
        role = request.headers.get('x-demo-role', 'org_admin')
        if role not in ROLES: raise HTTPException(403, 'Unknown demo role')
        return Actor('demo-'+role, 'demo-bank', role, {'org_admin':'Ananya Sharma','credit_analyst':'Rohan Mehta','credit_approver':'Priya Nair','relationship_manager':'Aditi Rao','policy_manager':'Vikram Shah','risk_reviewer':'Ishaan Patel'}.get(role, role.replace('_',' ').title()))
    token = request.session.get('access_token')
    if not token: raise HTTPException(401, 'Sign in with WorkOS')
    try:
        client = jwt.PyJWKClient(f'https://api.workos.com/sso/jwks/{settings.workos_client_id}')
        key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=['RS256'], issuer=[f'https://api.workos.com/user_management/{settings.workos_client_id}','https://api.workos.com/','https://api.workos.com'], options={'verify_aud':False,'require':['exp','sub','iss']}, leeway=10)
        if claims.get('client_id') and claims['client_id'] != settings.workos_client_id: raise ValueError('Client mismatch')
        org = claims.get('org_id')
        role = claims.get('role', '')
        if not org or role not in ROLES: raise ValueError('Organization role required')
        # Do not trust a cookie alone for a high-privilege action. Check active membership.
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.get('https://api.workos.com/user_management/organization_memberships', params={'user_id':claims['sub'],'organization_id':org}, headers={'Authorization':f'Bearer {settings.workos_api_key}'})
            result.raise_for_status()
            memberships = result.json().get('data', [])
        membership = next((m for m in memberships if m.get('status') == 'active'), None)
        if not membership: raise ValueError('Active organization membership required')
        role = membership.get('role', {}).get('slug', role)
        if role not in ROLES: raise ValueError('Unsupported role')
        return Actor(claims['sub'], org, role, request.session.get('name', 'Staff member'))
    except Exception:
        raise HTTPException(401, 'Session expired or membership unavailable. Sign in again.')
