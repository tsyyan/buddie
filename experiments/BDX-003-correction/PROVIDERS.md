# BDX-003: where the runs go (checked 2026-10-30)

One model per table of the protocol, `openai/gpt-oss-120b`, served by several free providers; the second model,
Gemini Flash, from Google only. No router or gateway: those switch model or provider on their own, and the paired
comparison needs every arm of a unit to meet the same model at the same provider.

## gpt-oss-120b

| provider | access | limit on the free tier | tool calling | notes |
|---|---|---|---|---|
| OVHcloud AI Endpoints | anonymous, no key | 2 requests a minute per IP and model ([list][awesome]); no daily cap documented | yes: catalog says Function Calling; a live anonymous request on 2026-10-30 returned a `source_text` tool call | fp4 (gpt-oss's native weights), EU-hosted; base `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`, model `gpt-oss-120b`. Run from one machine: Actions runners share IPs |
| Groq | key (`GROQ_API_KEY`, already a repository secret) | 30 RPM, 1K RPD, 8K TPM, 200K TPD ([rate limits][groq]) | yes (pilot 1) | the token limits, not requests, end a day: about 8 units with arms A–D at pilot 1's token use |
| Cloudflare Workers AI | API token and account id (to create) | 10,000 Neurons a day for all models, reset 00:00 UTC; gpt-oss-120b costs 31,818 Neurons per M input and 68,182 per M output tokens ([pricing][cf-price]) | yes: Function calling ([model page][cf-model]); OpenAI-compatible `/v1/chat/completions` | about 10 units a day with arms A–D at pilot 1's token use |

Estimates of units a day: pilot 1's mean tokens per run (A about 600 in / 530 out, B 4,700 / 1,760, C 6,100 /
1,940, D taken as C) summed over four arms, about 17,500 in and 6,100 out per unit. OVH at 2 RPM and about 14
requests per unit would take about 7 minutes a unit; its daily ceiling, if any, is not documented and is found by
running.

## More candidates for gpt-oss-120b (checked 2026-10-31)

Leads from [awesome-freellm-apis][freellm]; figures are from the provider's own page or a live call unless a row says otherwise.

| provider | free terms | use |
|---|---|---|
| SambaNova | free tier without a card: gpt-oss-120b 20 RPM, 20 RPD, 200K TPD ([rate limits][samba]); model listed at `api.sambanova.ai/v1/models` without a key | in `endpoint_pool.REGISTRY` (`SAMBANOVA_API_KEY`); about 1 unit a day, a spare |
| Cerebras | Free Trial: gpt-oss-120b 5 RPM, 30K uncached TPM, 1M TPH and TPD ([rate limits][cerebras]); third-party pages say the trial needs a payment method and its $5 credit lasts 30 days, not confirmed on Cerebras's pages | in the registry (`CEREBRAS_API_KEY`); a trial, about 20 units a day while it lasts |
| Scaleway | 1M free tokens once for a new customer, then paid: from a web search of [Scaleway's page][scaleway], the page itself not read; `api.scaleway.ai/v1/models` answers 401 without a key | in the registry (`SCALEWAY_API_KEY`); a one-off, about 20 units |
| Kilo Code | gpt-oss-120b is a paid model: an anonymous call answers `PAID_MODEL_AUTH_REQUIRED` | no |
| Hugging Face router | lists gpt-oss-120b; free accounts get no Inference Providers credits ([pricing][hf]) | no |
| Ollama Cloud | pay per token, gpt-oss:120b priced ([pricing][ollama]); no free tier | no |
| GitHub Models | `models.github.ai` answers every request with a plain-text `OK`, from a local machine too | no |
| LLM7.io, OpenCode Zen, Chutes | no gpt-oss-120b in their model lists (anonymous `GET /v1/models`) | no |

| Vercel AI Gateway | $5 of credits every 30 days for a team that has never paid ([pricing][vercel]); gpt-oss-120b's model page marks all its backends (Baseten, Bedrock, Fireworks, Groq, Parasail, Nebius, Together, Cerebras) "Free AI Gateway Credit: Yes", from $0.10 in / $0.50 out per M tokens ([model][vercel-oss]); free-tier rate limits are lower per model, numbers not published; buying credits ends the free tier | in the registry as `vercel-<backend>` (`AI_GATEWAY_API_KEY`), each pinned with `providerOptions.gateway.only` so a unit never changes backend; about 600 units a month at Baseten's price; the best find |
| FastRouter | lists `openai/gpt-oss-120b:free` at $0 (anonymous `GET /api/v1/models`); limits not found in its docs | in the registry (`FASTROUTER_API_KEY`); size unknown until run |
| OpenRouter | no `gpt-oss-120b:free` any more (anonymous `GET /api/v1/models`); `:batch` is cheap but paid | no |
| OrcaRouter | `-free` models, none of them gpt-oss (`GET /v1/models`); the lowest free tier also caps prompt size | no |
| Puter.js | gpt-oss without a key, but billed to the browser user's Puter account (user pays); not a server-side API | no |

Probe of 2026-10-31 from Actions (`endpoint-probe` workflow, run 41134971156): OVH, Groq and Cloudflare answered
with a `source_text` tool call (Cloudflare's first call from Actions). Vercel refused every backend with HTTP 403
`customer_verification_required`: the key is accepted, but the free credits unlock only with a credit card on
file; nothing has been paid and the free tier would stay free until a payment is made. The owner decided on
2026-10-31 not to add a card: Vercel is not used, its registry entries stay for whoever has a verified account.

Apart from that probe, none of the registry entries above has been called with a key yet: a key, then one tool-calling request, before a
run. Whether Vercel's OpenAI-compatible endpoint takes `providerOptions` in the body as its AI SDK does is the first
thing that request checks.

Units a month at Vercel: pilot 3's ERROR-unit means for arms A–D, about 36,000 tokens in and 9,000 out a unit, at
$0.10 / $0.50 per M is about $0.008 a unit; $5 / $0.008 is about 600. An estimate, not measured.

## Gemini Flash (second model)

Google AI Studio key (`GEMINI_API_KEY`, a repository secret), model `gemini-3.8-flash`. Google no longer publishes
free-tier limits per model; the quota shows in AI Studio. Free-tier prompts may be used to improve Google products,
except for users in the EEA, Switzerland and the UK ([list][awesome], note 1). The inputs are public benchmark
reports.

## Not used, and why

- NVIDIA NIM: the free endpoint of `openai/gpt-oss-120b` is marked Deprecated on its [model page][nim].
- OpenRouter: no free `gpt-oss-120b` in today's `:free` list; free models share 50 requests a day ([list][awesome]).
- GitHub Models: answers every request from this repository's Actions with a plain-text `OK` (PROTOCOL.md).
- Routers and gateways (OpenRouter's free router, Kilo's `kilo-auto/free`, OmniRoute, FreeLLMAPI, freerouter): they
  pick or switch the model themselves. The self-hosted ones would also see every key; their code was not read.
- Providers that need Chinese real-name verification (ModelScope, SiliconFlow) or serve other models only.

## Rules for using several providers (to record in PROTOCOL.md before the main run)

- A unit runs all its arms at one provider; when a provider's quota ends, the next unit goes elsewhere, the current
  one is never split. `arms.py` records `provider` in every row.
- Per-provider cells are reported next to the pooled per-model table, so a provider effect would show.

[awesome]: https://github.com/mnfst/awesome-free-llm-apis
[groq]: https://console.groq.com/docs/rate-limits
[cf-price]: https://developers.cloudflare.com/workers-ai/platform/pricing/
[cf-model]: https://developers.cloudflare.com/workers-ai/models/gpt-oss-120b/
[nim]: https://build.nvidia.com/openai/gpt-oss-120b
[freellm]: https://github.com/open-free-llm-api/awesome-freellm-apis
[samba]: https://docs.sambanova.ai/docs/en/models/rate-limits
[cerebras]: https://inference-docs.cerebras.ai/support/rate-limits
[scaleway]: https://www.scaleway.com/generative-apis/
[hf]: https://huggingface.co/docs/inference-providers/pricing
[ollama]: https://ollama.com/pricing
[vercel]: https://vercel.com/docs/ai-gateway/pricing
[vercel-oss]: https://vercel.com/ai-gateway/models/gpt-oss-120b
