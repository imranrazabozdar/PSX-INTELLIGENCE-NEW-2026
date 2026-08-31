"""ai_overlay.py — QuantLLMService: the AI Intelligence Layer behind the
"AI Analyst Synthesis" (Stock Research tab) and "AI Edge Analysis" (Quant
Validation Lab) placeholders in streamlit_app.py.

PRIMARY PROVIDER: Google Gemini, via the official `google-generativeai`
SDK (model: gemini-1.5-flash — fast/cheap, appropriate for a 3-sentence
summary, not a reasoning-heavy task). Reads GEMINI_API_KEY.
Secondary fallbacks (OPENAI_API_KEY, ANTHROPIC_API_KEY) stay available
via plain REST for anyone running this without a Gemini key — checked
in that order only if GEMINI_API_KEY isn't set.

MOCK MODE: if no key is configured, the `google-generativeai` package
isn't installed, or every call to the configured provider fails
(network error, invalid key, RATE LIMIT — google-generativeai raises
google.api_core.exceptions.ResourceExhausted for 429s, caught here like
any other failure), every method falls back to a deterministic, clearly
-labeled summary built directly from the real numbers passed in — never
a fabricated-sounding "AI" sentence pretending to be a live model
response, and never an exception. The terminal must be able to call
this service unconditionally, key or no key, rate-limited or not, and
always get a string back.
"""

import json
import os

import requests

try:
    import google.generativeai as genai
except ImportError:                                     # pragma: no cover
    genai = None  # falls through to mock mode below if GEMINI_API_KEY is set anyway

_PROVIDER_ENV_VARS = ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
_TIMEOUT = 20
# gemini-1.5-flash was retired by Google (live 404 + ListModels
# confirmed). "gemini-flash-latest" resolved to a preview model with an
# unusually tight 5-req/min free quota (live 429). "gemini-2.5-flash" is
# no longer available to new users as of this key (live 404, which
# explicitly named gemini-3.6-flash as its replacement) -- that's what's
# pinned now, confirmed working with a real successful call.
_GEMINI_MODEL = "gemini-3.6-flash"


class QuantLLMService:
    """One instance per process is enough — it holds no per-request state,
    just which provider (if any) is configured."""

    def __init__(self):
        self.provider, self.api_key = self._detect_provider()

    @staticmethod
    def _detect_provider():
        for env_var in _PROVIDER_ENV_VARS:
            key = os.getenv(env_var)
            if key:
                return env_var.split("_API_KEY")[0].lower(), key  # "gemini" / "openai" / "anthropic"
        return None, None

    @property
    def is_live(self):
        """True if a real provider is configured — lets callers (e.g. the
        dashboard) show 'LLM Integration Pending' vs an actual AI badge
        without duplicating the provider-detection logic."""
        return self.provider is not None

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------
    def get_stock_research_summary(self, ticker, dss_score, technical_data, recent_news):
        """3-sentence executive bull/bear summary for one symbol's Stock
        Research page. `technical_data` and `recent_news` are whatever
        dicts/strings the caller already has on hand (DSS engines output,
        news-feed rows) — this method only reads them, never fetches or
        computes anything itself, so it can't disagree with the numbers
        already on screen.
        """
        prompt = self._build_stock_research_prompt(ticker, dss_score, technical_data, recent_news)
        result = self._call_llm(prompt, max_tokens=4096)
        if result is not None:
            return result
        return self._mock_stock_research_summary(ticker, dss_score, technical_data, recent_news)

    def get_edge_analysis_summary(self, backtest_metrics, regime_status):
        """3-sentence statistical-edge summary for the Quant Validation
        Lab — reads real win-rate/expectancy/sample-size numbers already
        computed by the backtest engine, never invents its own."""
        prompt = self._build_edge_analysis_prompt(backtest_metrics, regime_status)
        result = self._call_llm(prompt, max_tokens=4096)
        if result is not None:
            return result
        return self._mock_edge_analysis_summary(backtest_metrics, regime_status)

    def get_batch_stock_research_summaries(self, symbols_payload):
        """Same 3-sentence bull/bear read as get_stock_research_summary,
        but for MANY symbols in ONE Gemini call — modeled directly on
        news_glm.py's batched-JSON-prompt design (one request rates
        every symbol, not one request per symbol).

        WHY: this project hit gemini-3.6-flash's 20-request/day free
        quota repeatedly because email_reporter.py / pdf_reporter.py
        each made one Gemini call PER symbol (a 15-symbol report alone
        burned 15/20 requests). Batching N symbols into 1 request makes
        an N-symbol report cost 1/20 of the quota instead of N/20.

        symbols_payload: {ticker: {"dss_score": ..., "technical_data":
        ..., "recent_news": ...}}. Returns {ticker: summary_text} —
        every requested ticker is present in the result: live text where
        the batch call succeeded and that ticker's key parsed cleanly
        out of the response, the same per-symbol mock text otherwise
        (a partially-malformed batch response degrades per-symbol, not
        as an all-or-nothing failure).
        """
        if not symbols_payload:
            return {}
        prompt = self._build_batch_stock_research_prompt(symbols_payload)
        # Scale the token budget with batch size -- same per-symbol
        # allowance as the single-symbol call, plus headroom for the
        # per-call "thinking" tokens newer Gemini models spend before
        # any visible text (see the max_tokens=4096 note on the
        # single-symbol calls above).
        budget = 2048 + 1200 * len(symbols_payload)
        raw = self._call_llm(prompt, max_tokens=budget, json_mode=True)
        parsed = self._parse_batch_json(raw, set(symbols_payload)) if raw is not None else {}

        out = {}
        for ticker, data in symbols_payload.items():
            if ticker in parsed:
                out[ticker] = parsed[ticker]
            else:
                out[ticker] = self._mock_stock_research_summary(
                    ticker, data.get("dss_score"), data.get("technical_data"), data.get("recent_news"))
        return out

    # ------------------------------------------------------------------
    # Prompt construction — strict, numbers-only framing so the model is
    # summarizing evidence already on screen, not inventing new claims.
    # ------------------------------------------------------------------
    @staticmethod
    def _build_stock_research_prompt(ticker, dss_score, technical_data, recent_news):
        payload = {
            "symbol": ticker,
            "dss_evidence_score_0_100": dss_score,
            "technical_data": technical_data,
            "recent_news": recent_news,
        }
        return (
            "You are a quantitative equity analyst writing an internal desk note. "
            "Use ONLY the JSON data below — never invent a price, indicator value, "
            "or news event that isn't present in it. Do not give investment advice "
            "or a buy/sell instruction; describe what the evidence shows. Respond "
            "with EXACTLY 3 sentences, plain text, no markdown, no preamble: "
            "(1) the net bullish/bearish lean and why, (2) the strongest supporting "
            "AND the strongest contradicting piece of evidence, (3) the key risk or "
            "condition that would change the read.\n\n"
            f"DATA:\n{json.dumps(payload, default=str)}\n"
        )

    @staticmethod
    def _build_batch_stock_research_prompt(symbols_payload):
        """news_glm.py's pattern: one prompt lists every symbol's data,
        the model returns one JSON object keyed by symbol. Adapted to
        this project's 3-sentence bull/bear format instead of GLM's
        single-word rating."""
        lines = [
            "You are a quantitative equity analyst writing internal desk notes for "
            "MULTIPLE symbols in one batch. For EACH symbol below, use ONLY that "
            "symbol's own JSON data — never invent a price, indicator value, or "
            "news event that isn't present in it, and never let one symbol's data "
            "leak into another's summary. Do not give investment advice; describe "
            "what the evidence shows. Return ONLY valid JSON, no prose, no markdown "
            "fences, exactly this shape:",
            '{"SYMBOL": "exactly 3 sentences: (1) net bullish/bearish lean and why, '
            '(2) strongest supporting AND strongest contradicting evidence, '
            '(3) key risk/condition that would change the read.", ...}',
            "",
            "SYMBOLS AND DATA:",
        ]
        for ticker, data in symbols_payload.items():
            payload = {
                "dss_evidence_score_0_100": data.get("dss_score"),
                "technical_data": data.get("technical_data"),
                "recent_news": data.get("recent_news"),
            }
            lines.append(f"\n{ticker}:")
            lines.append(json.dumps(payload, default=str))
        return "\n".join(lines)

    @staticmethod
    def _parse_batch_json(raw_text, expected_symbols):
        """news_glm.py's _sanitize() pattern: strip markdown fences if the
        model added them despite instructions, parse, then keep only
        entries whose key is an actually-requested symbol with a
        non-empty string value. A malformed/unparseable response yields
        an empty dict — callers fall back to mock per-symbol, not a
        blanket exception."""
        if not raw_text:
            return {}
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        out = {}
        for sym, summary in data.items():
            s = str(sym).upper()
            if s in expected_symbols and isinstance(summary, str) and summary.strip():
                out[s] = summary.strip()
        return out

    @staticmethod
    def _build_edge_analysis_prompt(backtest_metrics, regime_status):
        payload = {
            "backtest_metrics": backtest_metrics,
            "current_regime_status": regime_status,
        }
        return (
            "You are a quantitative researcher summarizing a backtest for an "
            "internal validation lab. Use ONLY the JSON data below — never invent "
            "a win rate, sample size, or regime label that isn't present in it, "
            "and explicitly flag if the sample size is small. Respond with EXACTLY "
            "3 sentences, plain text, no markdown, no preamble: (1) whether the "
            "historical edge is statistically meaningful given the sample size, "
            "(2) how expectancy/win-rate compares to a coin-flip baseline, (3) "
            "whether the current market regime matches the regime this edge was "
            "actually measured in.\n\n"
            f"DATA:\n{json.dumps(payload, default=str)}\n"
        )

    # ------------------------------------------------------------------
    # Provider dispatch — plain REST, no SDK. Any failure (network, auth,
    # malformed response) returns None so the caller falls back to mock
    # mode instead of raising.
    # ------------------------------------------------------------------
    def _call_llm(self, prompt, max_tokens, json_mode=False):
        if not self.provider:
            return None
        try:
            if self.provider == "gemini":
                return self._call_gemini(prompt, max_tokens, json_mode)
            if self.provider == "openai":
                return self._call_openai(prompt, max_tokens)
            if self.provider == "anthropic":
                return self._call_anthropic(prompt, max_tokens)
        except Exception as e:
            print(f"[ai_overlay] {self.provider} call failed, falling back to mock: "
                  f"{type(e).__name__}: {e}")
        return None

    def _call_gemini(self, prompt, max_tokens, json_mode=False):
        if genai is None:
            print("[ai_overlay] GEMINI_API_KEY is set but google-generativeai isn't "
                  "installed (pip install google-generativeai) — falling back to mock.")
            return None
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(_GEMINI_MODEL)
        cfg_kwargs = {"max_output_tokens": max_tokens, "temperature": 0.2}
        if json_mode:
            # Gemini's structured-output mode -- for the batched call, this
            # is what makes "return ONLY valid JSON" reliable instead of
            # hopeful prompt-following (same intent as news_glm.py's GLM
            # call using response_format={"type": "json_object"}).
            cfg_kwargs["response_mime_type"] = "application/json"
        response = model.generate_content(
            prompt, generation_config=genai.types.GenerationConfig(**cfg_kwargs))
        return response.text.strip()

    def _call_openai(self, prompt, max_tokens):
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": max_tokens, "temperature": 0.2},
            timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _call_anthropic(self, prompt, max_tokens):
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            json={"model": "claude-3-5-haiku-20241022", "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()

    # ------------------------------------------------------------------
    # Mock mode — deterministic, built from the real numbers passed in,
    # clearly labeled as not a live model response.
    # ------------------------------------------------------------------
    @staticmethod
    def _mock_stock_research_summary(ticker, dss_score, technical_data, recent_news):
        score_str = f"{dss_score}/100" if dss_score is not None else "unavailable"
        has_news = bool(recent_news)
        return (
            f"[MOCK — no LLM key configured] {ticker}'s current DSS evidence score is "
            f"{score_str}. Technical data ({'available' if technical_data else 'unavailable'}) "
            f"and news context ({'present' if has_news else 'none flagged'}) would normally "
            "be synthesized here into a 3-sentence bull/bear read. "
            "Set GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY to enable live AI summaries."
        )

    @staticmethod
    def _mock_edge_analysis_summary(backtest_metrics, regime_status):
        has_metrics = bool(backtest_metrics)
        regime = regime_status if regime_status else "unavailable"
        return (
            "[MOCK — no LLM key configured] Backtest metrics are "
            f"{'available' if has_metrics else 'unavailable'} for this pattern, and the current "
            f"regime status is {regime}. A live model would normally compare expectancy against "
            "a random-entry baseline and flag any regime mismatch here in 3 sentences. "
            "Set GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY to enable live AI summaries."
        )
