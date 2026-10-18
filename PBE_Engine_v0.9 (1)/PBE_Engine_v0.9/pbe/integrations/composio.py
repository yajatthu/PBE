import base64, hashlib, hmac, json
import httpx
from pbe.settings import settings
from pbe.integrations.tool_contracts import unwrap_list, normalize_tool

class ComposioClient:
    def __init__(self): self.base=settings.COMPOSIO_API_BASE; self.key=settings.COMPOSIO_API_KEY
    def _headers(self): return {"x-api-key":self.key,"content-type":"application/json"}
    async def create_auth_link(self, user_id: str, auth_config_id: str, callback_url: str|None=None):
        payload={"auth_config_id":auth_config_id,"user_id":user_id}
        if callback_url: payload["callback_url"]=callback_url
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.post(f"{self.base}/connected_accounts/link",headers=self._headers(),json=payload); r.raise_for_status(); return r.json()
    async def list_accounts(self, user_id: str|None=None, toolkit: str|None=None):
        params={}
        if user_id: params["user_ids"]=user_id
        if toolkit: params["toolkit_slugs"]=toolkit
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.get(f"{self.base}/connected_accounts",headers=self._headers(),params=params); r.raise_for_status(); return r.json()
    async def create_trigger(self, slug: str, user_id: str, connected_account_id: str|None=None, trigger_config: dict|None=None):
        payload={"user_id":user_id,"trigger_config":trigger_config or {}}
        if connected_account_id: payload["connected_account_id"]=connected_account_id
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.post(f"{self.base}/trigger_instances/{slug}/upsert",headers=self._headers(),json=payload); r.raise_for_status(); return r.json()

    async def list_tools(self, toolkit_slug: str|None=None, search: str|None=None, limit: int=60):
        params={"limit":max(1,min(int(limit),100)),"toolkit_versions":"latest"}
        if toolkit_slug: params["toolkit_slug"]=toolkit_slug
        if search: params["search"] = search
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.get(f"{self.base}/tools",headers=self._headers(),params=params); r.raise_for_status(); data=r.json()
        # Normalize common Composio V3 response envelopes for the planner/UI.
        return unwrap_list(data, ("items", "tools", "data", "results"))

    async def get_tool(self, tool_slug: str):
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.get(f"{self.base}/tools/{tool_slug}",headers=self._headers(),params={"version":"latest"}); r.raise_for_status(); return r.json()

    async def execute_tool(self, tool_slug: str, arguments: dict, user_id: str, connected_account_id: str|None=None):
        payload={"arguments":arguments or {},"user_id":user_id,"version":"latest"}
        if connected_account_id: payload["connected_account_id"]=connected_account_id
        async with httpx.AsyncClient(timeout=60) as c:
            r=await c.post(f"{self.base}/tools/execute/{tool_slug}",headers=self._headers(),json=payload); r.raise_for_status(); return r.json()

    async def create_webhook_subscription(self, webhook_url: str):
        payload={"webhook_url":webhook_url,"enabled_events":["composio.trigger.message","composio.connected_account.expired"],"version":"V3"}
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.post(f"{self.base}/webhook_subscriptions",headers=self._headers(),json=payload); r.raise_for_status(); return r.json()
    @staticmethod
    def verify_webhook(raw: bytes, webhook_id: str, timestamp: str, signature: str, secret: str) -> bool:
        if not secret or not webhook_id or not timestamp or not signature: return False
        signed=f"{webhook_id}.{timestamp}.".encode()+raw
        expected=base64.b64encode(hmac.new(secret.encode(), signed, hashlib.sha256).digest()).decode()
        return any(hmac.compare_digest(expected, item.strip().split(" ",1)[-1].replace("v1,","")) for item in signature.split(","))
