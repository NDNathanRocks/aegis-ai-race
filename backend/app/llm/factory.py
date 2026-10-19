"""Back-compat alias: the gateway replaced the old 60 s global-cooldown ResilientLLM."""
from app.llm.gateway import LLMGateway

ResilientLLM = LLMGateway
