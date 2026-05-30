# LLM Provider Setup Guide

Quick reference for setting up each supported LLM provider.

## OpenAI (GPT-4o, GPT-4 Turbo)

**Pros:** Best cost/quality ratio, very reliable, multiple model options  
**Cons:** Requires paid API key, rate limiting

### Setup

1. Get API key: https://platform.openai.com/api-keys
2. Create `.env` or set environment:
   ```bash
   export LLM_PROVIDER=openai
   export OPENAI_API_KEY=sk-xxx...
   export OPENAI_MODEL=gpt-4o  # optional, defaults to gpt-4o
   ```
3. Run pipeline:
   ```bash
   python main.py --phase 2
   ```

### Pricing
- gpt-4o: ~$5 per 1M input tokens, ~$15 per 1M output tokens
- Typical email: ~500 tokens → ~$0.005 per transaction

### Models Available
- `gpt-4o` (recommended, fast & capable)
- `gpt-4-turbo`
- `gpt-4`
- `gpt-3.5-turbo` (cheaper)

---

## Anthropic (Claude)

**Pros:** Best accuracy, excellent context handling, longest context window  
**Cons:** Slightly more expensive than OpenAI, limited model options

### Setup

1. Get API key: https://console.anthropic.com/api-keys
2. Create `.env` or set environment:
   ```bash
   export LLM_PROVIDER=anthropic
   export ANTHROPIC_API_KEY=sk-ant-xxx...
   export ANTHROPIC_MODEL=claude-sonnet-4-20250514  # optional
   ```
3. Run pipeline:
   ```bash
   python main.py --phase 2
   ```

### Pricing
- claude-sonnet: ~$3 per 1M input tokens, ~$15 per 1M output tokens
- Typical email: ~500 tokens → ~$0.0075 per transaction

### Models Available
- `claude-sonnet-4-20250514` (recommended)
- `claude-opus-4-1`
- `claude-haiku-3` (cheaper but less capable)

---

## Google Gemini

**Pros:** Very fast, free tier available, good for high volume  
**Cons:** Smaller free tier, less tested for this use case

### Setup

1. Get API key: https://aistudio.google.com/apikey (free tier available)
2. Create `.env` or set environment:
   ```bash
   export LLM_PROVIDER=gemini
   export GEMINI_API_KEY=AIzaSy...
   export GEMINI_MODEL=gemini-2.0-flash  # optional
   ```
3. Run pipeline:
   ```bash
   python main.py --phase 2
   ```

### Pricing
- **Free tier:** 15 requests/min, 1.5M tokens/day
- **Paid:** ~$0.075 per 1M input tokens, ~$0.30 per 1M output tokens

### Models Available
- `gemini-2.0-flash` (recommended, very fast)
- `gemini-1.5-pro` (more capable)
- `gemini-1.5-flash` (faster, cheaper)

### Free Tier Limits
- 15 requests per minute
- 1.5M tokens per day
- ~3,000 transactions/month free

---

## Ollama (Local, Self-Hosted)

**Pros:** Free, private (no data leaves your machine), no API costs  
**Cons:** Requires local GPU/CPU, slower inference, setup complexity

### Setup

1. Install Ollama: https://ollama.ai
2. Start Ollama server:
   ```bash
   ollama serve
   # Ollama listens on http://localhost:11434
   ```
3. Pull a model (in another terminal):
   ```bash
   # Recommended models for this task:
   ollama pull mistral      # Fast, good quality
   ollama pull llama2       # Good all-around
   ollama pull neural-chat  # Optimized for chat
   ```
4. Set environment:
   ```bash
   export LLM_PROVIDER=ollama
   export OLLAMA_BASE_URL=http://localhost:11434
   export OLLAMA_MODEL=mistral  # or llama2, neural-chat
   ```
5. Run pipeline:
   ```bash
   python main.py --phase 2
   ```

### Models & Performance

| Model | Speed | Quality | Memory |
|-------|-------|---------|--------|
| mistral | Fast | Good | 4GB |
| llama2 | Medium | Good | 7GB |
| neural-chat | Fast | Good | 4GB |
| llama2:70b | Slow | Excellent | 40GB |

### Tips
- For CPU-only machines: `mistral` or `neural-chat` (4GB model)
- For GPU machines: `llama2:70b` or higher for best quality
- First run downloads the model (5-30GB depending on model)
- Response time: 10-60 seconds per email on CPU, 1-5 seconds on GPU

---

## Comparison Matrix

| Feature | OpenAI | Anthropic | Gemini | Ollama |
|---------|--------|-----------|--------|--------|
| Cost | $$ | $$$ | $-$$ | Free |
| Accuracy | Excellent | Excellent | Good | Good-Excellent |
| Speed | Fast | Medium | Very Fast | Slow-Medium |
| Privacy | No | No | No | Yes |
| Setup | Easy | Easy | Easy | Hard |
| Reliability | Excellent | Excellent | Good | Depends on HW |
| Context Length | 128K | 200K | 1M | Varies |

---

## Recommendation by Use Case

### **I want to get started quickly**
→ Use **OpenAI** (gpt-4o) — easy setup, reliable, affordable

### **I want the most accurate results**
→ Use **Anthropic** (Claude Sonnet) — best for complex categorization

### **I want to minimize costs**
→ Use **Gemini** — free tier available, pay-as-you-go

### **I want complete privacy**
→ Use **Ollama** (local) — all data stays on your machine, no API calls

### **I'm running high volume (1000+ emails/day)**
→ Use **Gemini** or **OpenAI** batch processing (batch API)

---

## Switching Providers

To switch providers at any time:

```bash
# Current provider
export LLM_PROVIDER=openai

# Switch to Anthropic
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# Run pipeline with new provider
python main.py --phase 2
```

The pipeline will detect the new provider automatically.

---

## Troubleshooting

### "API key not configured"
- Make sure you set the correct env var for your provider
- Check you copied the key correctly (no extra spaces)

### "Rate limited"
- OpenAI/Gemini have rate limits. Wait before retrying
- Use Ollama if you hit rate limits frequently

### "Connection refused" (Ollama)
- Make sure Ollama is running: `ollama serve`
- Check the base URL is correct: `http://localhost:11434`

### "Model not found" (Ollama)
- Pull the model first: `ollama pull mistral`

### "Response doesn't contain valid JSON"
- The LLM might not be following the prompt format
- Try a different model or provider
- Check dead letter queue for the failing email

---

## Cost Estimation

For 100 emails/month (~500 tokens each):

| Provider | Monthly Cost |
|----------|-------------|
| OpenAI (gpt-4o) | ~$0.50 |
| Anthropic | ~$0.75 |
| Gemini (free tier) | Free |
| Ollama | Free (electricity only) |

---

## Next Steps

1. Pick a provider
2. Set up API key (if needed)
3. Run Phase 2: `python main.py --phase 2`
4. Review LLM output quality
5. Tune categorization rules if needed
6. Move to Phase 3 when happy

See `README.md` for full setup instructions.
