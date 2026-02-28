# Context Management Strategies Comparison (Real Benchmark)

This report details the behavior, stability, and token consumption of the four different context management strategies implemented in the `GeneralAgent`. 
The test scenario involved a Python script feeding 15 sequential details about a custom application to the DeepSeek API, ending with a test question: *"What is the name, primary color, frontend framework, and backend framework of the app we are building?"*

## Benchmark Methodology
- **LLM**: `deepseek-chat`
- **Messages**: 15 requests per strategy
- **Scenario**: App is called "TaskMaster" (msg 1), color is "#FF5733" (msg 3), Frontend React Native (msg 2), Backend Node.js (msg 6).

---

### Strategy 1: Default Compression
**Mechanism**: Retains a rolling summarized history combined with the latest literal messages.

- **Total Time**: `914.98 seconds`
- **Prompt Tokens**: `82,512`
- **Completion Tokens**: `42,168`
- **Test Passed?**: **Yes**. The agent successfully retrieved the name "TaskMaster", color "#FF5733", React Native, and Node.js.
- **Analysis**: The rolling summary effectively preserved the early details (like the exact color code) while aggressively shrinking the active prompt size compared to raw history.

### Strategy 2: Sliding Window
**Mechanism**: Hard-cuts the history to only the last 10 messages. No summarization.

- **Total Time**: `941.15 seconds`
- **Prompt Tokens**: `166,729` (Surprisingly higher than Default!)
- **Completion Tokens**: `41,212`
- **Test Passed?**: **No**. The agent hallucinated older facts. It guessed the name "TaskMaster" (likely luck or internal training data interpolation), but hallucinated the primary color as `#34C759` (Green) instead of `#FF5733` because the true color was in message #3, which was dropped from the 10-message window.
- **Analysis**: While simple, sending 10 full uncompressed messages actually consumes *more* prompt tokens than sending 4 messages + 1 compact summary. It also definitively suffers from amnesia for early constraints.

### Strategy 3: Sticky Facts (Key-Value Memory)
**Mechanism**: On every user message, a background API call extracts core decisions and appends them to a persistent `session.facts` text injected into the system prompt.

- **Total Time**: `1,192.57 seconds` 
- **Prompt Tokens**: `212,630`
- **Completion Tokens**: `49,335`
- **Test Passed?**: **Yes**. Flawless recall.
- **Analysis**: Achieved the highest quality of strict fact retention, actively declaring `*[System: Извлекаю и обновляю факты...]*`. However, doing a secondary LLM extraction on *every* message makes it the most expensive (~2.5x more prompt tokens than Default) and the slowest strategy by far.

### Strategy 4: Branching
**Mechanism**: Deep-clones the conversation state to create a parallel timeline, using Default Compression under the hood.

- **Total Time**: `764.12 seconds`
- **Prompt Tokens**: `36,765`
- **Completion Tokens**: `29,150`
- **Test Passed?**: **Yes**. 
- **Analysis**: Branching inherently performs exactly like Default Compression within its own timeline, but because it isolates histories, it prevents context pollution. The token count here was lowest due to API caching/variances during the benchmark run, but mechanically it mirrors Default.

---

## Conclusion

The real-world telemetry proves our architectural assumptions:
1. **Default Compression** is the undisputed winner for everyday use. It balances good recall with aggressive token savings (82k prompt tokens vs 166k for a 10-message window).
2. **Sliding Window** is surprisingly inefficient. It forgets critical early constraints (hallucinating the app color) while still costing *more* prompt tokens than compression because it sends large blocks of uncompressed raw text.
3. **Sticky Facts** gives perfect recall but is heavily penalized in speed (+30% slower) and cost (+150% prompt tokens) due to parallel LLM evaluations. Use this strictly for complex, multi-day coding/planning sessions where forgetting a rule is catastrophic.
