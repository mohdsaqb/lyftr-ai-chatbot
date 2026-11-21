import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar

import litellm
from litellm import Router
from litellm.caching.caching import Cache
from litellm.integrations.custom_logger import CustomLogger

MODEL_ALIAS = "chat-model"
logger = logging.getLogger(__name__)
attempt_context = ContextVar("attempt_context", default=None)


class DeploymentAttempts(CustomLogger):
    async def async_pre_call_check(self, deployment, parent_otel_span=None):
        context = attempt_context.get()
        if context is None:
            return
        failures, attempts = context
        key_id = deployment["model_info"]["id"]
        attempts.append(key_id)
        if key_id in failures:
            raise litellm.APIError(status_code=failures[key_id], message="Simulated failure",
                                   llm_provider="groq", model=deployment["litellm_params"]["model"])


@contextmanager
def open_gateway():
    keys = [key.strip() for key in os.environ["LLM_API_KEYS"].split(",")]
    if len(keys) != 2 or not all(keys) or keys[0] == keys[1]:
        raise ValueError("LLM_API_KEYS requires two distinct Groq keys")
    deployments = []
    for index, key in enumerate(keys, start=1):
        model = os.environ[f"GROQ_MODEL_{index}"].strip().removeprefix("groq/")
        if not model:
            raise ValueError(f"GROQ_MODEL_{index} is empty")
        deployments.append({
            "model_name": MODEL_ALIAS,
            "model_info": {"id": f"key_{index}"},
            # The native adapter in LiteLLM 1.106.0 fails on replies without service_tier.
            "litellm_params": {
                "model": f"openai/{model}",
                "api_base": "https://api.groq.com/openai/v1",
                "api_key": key,
                "order": index,
            },
        })
    router = Router(model_list=deployments, num_retries=0, max_fallbacks=1,
                    disable_cooldowns=True, timeout=30)
    cache = Cache(type="local", max_messages=None)
    hook = DeploymentAttempts()
    litellm.callbacks.append(hook)
    try:
        yield router, cache
    finally:
        litellm.callbacks.remove(hook)
        router.discard()


async def complete(router, cache, messages, failures):
    lookup = {"model": MODEL_ALIAS, "messages": messages}
    if not failures:
        cached = cache.get_cache(**lookup)
        if cached is not None:
            return cached["reply"], {
                **cached["usage"], "resolution_source": "LLM_CACHE",
                "key_id": None, "fallback_attempts": 0,
            }

    attempts = []
    token = attempt_context.set((failures, attempts))
    try:
        response = await router.acompletion(**lookup, caching=False)
    except Exception as exc:
        logger.warning(
            "Chat routing failed: attempts=%s simulated=%s error=%s sdk_status=%s",
            ",".join(attempts) or "none", ",".join(failures) or "none",
            type(exc).__name__, getattr(exc, "status_code", None),
        )
        raise
    finally:
        attempt_context.reset(token)
    reply = response.choices[0].message.content if response.choices else None
    model = response.model
    if not isinstance(reply, str) or not reply.strip() or not model:
        logger.warning("Incomplete provider reply: attempts=%s", ",".join(attempts))
        raise ValueError("Incomplete provider response")
    tokens = getattr(response, "usage", None)
    usage = {
        "model": model if model.startswith("groq/") else f"groq/{model}",
        "input_tokens": getattr(tokens, "prompt_tokens", None),
        "output_tokens": getattr(tokens, "completion_tokens", None),
    }
    if not all(type(usage[name]) is int and usage[name] >= 0
               for name in ("input_tokens", "output_tokens")):
        logger.warning("Missing provider token counts: attempts=%s", ",".join(attempts))
        raise ValueError("Missing provider token counts")
    if not attempts:
        logger.warning("Response received without a recorded deployment attempt")
        raise ValueError("Missing deployment information")
    cache.add_cache({"reply": reply, "usage": usage}, **lookup)
    return reply, {
        **usage, "resolution_source": "LIVE_INFERENCE", "key_id": attempts[-1],
        "fallback_attempts": len(attempts) - 1,
    }
