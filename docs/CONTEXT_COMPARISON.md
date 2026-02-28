# Context Management Strategies Comparison

This report details the behavior, stability, and token consumption of the four different context management strategies implemented in the `GeneralAgent`. The test scenario involves a user providing requirements for a new mobile application over 15 distinct messages, asking the agent to remember and synthesize them.

## Test Scenario: Requirement Gathering (15 messages)

**Objective**: Feed the agent 15 sequential details about a custom application (e.g., "The app is called TaskMaster", "It must use React Native", "It needs offline support", "User profiles require avatars", etc.) and then ask the agent to summarize all requirements in the final message.

---

### Strategy 1: Default Compression
**Mechanism**: Retains a rolling summarized history combined with the last N literal messages.

- **Quality of Response**: High. The agent successfully retrieves most of the original requirements because the older constraints are fused into a running summary. However, extremely specific nuances (like a specific hex color code mentioned in message 2) might get smoothed over or abstracted in the compression.
- **Stability (Forgetfulness)**: Very stable over long sessions (100+ messages), but slightly lossy for exact quotes.
- **Token Consumption**: **Medium/High**. The background summarization LLM call costs tokens every time the threshold is hit. The prompt itself stays reasonably small.
- **UX**: Seamless. The user occasionally sees a `*[System: Сжимаю старый контекст...]*` message briefly.

### Strategy 2: Sliding Window
**Mechanism**: Hard-cuts the history to only the last 10 messages. No summarization.

- **Quality of Response**: High for recent context. **Fails completely** on retrieving older context. When asked to summarize all 15 requirements, the agent is entirely blind to messages 1 through 5.
- **Stability (Forgetfulness)**: Zero stability for old context.
- **Token Consumption**: **Low**. History length is strictly bounded (e.g., max 10 messages). Token usage flatlines and never grows. No background LLM calls are made.
- **UX**: Fast and silent. Best used for one-off tasks or transient debugging where past context isn't needed.

### Strategy 3: Sticky Facts (Key-Value Memory)
**Mechanism**: On every user message, a background LLM process extracts core decisions and appends them to a persistent `session.facts` string injected into the system prompt.

- **Quality of Response**: Excellent. The agent remembers the exact requirements mentioned in message 1 even at message 15, because they were extracted as bullet points into the system prompt.
- **Stability (Forgetfulness)**: Extremely stable. It retains hard constraints perfectly. 
- **Token Consumption**: **High**. *Every* user message triggers an additional background LLM request to evaluate if new facts need to be appended. The system prompt also grows linearly as more facts are added.
- **UX**: Can add slight latency due to the parallel fact-extraction. The user sees `*[System: Извлекаю и обновляю факты...]*`.

### Strategy 4: Branching
**Mechanism**: Deep-clones the conversation state up to a specific point, creating a parallel timeline.

- **Quality of Response**: Uses Default Compression internally, but isolates context. Perfect for exploring an alternative requirement ("What if we used Flutter instead of React Native?") without permanently polluting the main project timeline.
- **Stability (Forgetfulness)**: Protects the main branch from context drift.
- **Token Consumption**: Equivalent to Default Compression per active branch.
- **UX**: Highly interactive. Users can click "Branch" on any old message and instantly jump to a clean timeline in the sidebar.

---

## Conclusion
- Use **Sliding Window** for general, transient chatting to save tokens.
- Use **Default Compression** as the balanced, everyday strategy.
- Use **Sticky Facts** specifically for long-term project planning where rules/instructions from day 1 must be strictly obeyed on day 50.
- Use **Branching** for "what-if" exploratory coding or divergent brainstorming.
