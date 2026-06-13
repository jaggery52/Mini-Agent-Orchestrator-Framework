# Example Transcript — Real Session

A complete, unedited session captured via `testing/mini-agent-client.py` against a locally running server.
It demonstrates the full flow: **goal → plan → tool execution → answer → multi-turn follow-up → session end**,
including TODO status tracking and OpenAI prompt-cache hits.

- Model: `gpt-4.1-mini` | Web search: Tavily
- Session ID: `597e9a09-e42d-4355-901a-b4dde3247b08`
- Total tokens: **21,596** (10,240 served from prompt cache)
- Full server-side log for this session: [agent.log](agent.log)

---

## 1. User states the goal

```
Agent: What would you like to do?

You:   What are the latest breakthroughs in quantum computing in 2026,
       and what do they mean for practical applications?
```

## 2. Planner produces a structured TODO plan

```
[Planner] Goal: Find out the latest breakthroughs in quantum computing in 2026
          and their implications for practical applications.
  1. Internet Search for Latest Quantum Computing Breakthroughs 2026
       — Search for the latest breakthroughs in quantum computing in 2026 and
         their significance for practical applications.
  2. Ready for Answer
       — Compile the information about the latest quantum computing breakthroughs
         and their practical implications into a comprehensive response.
```

## 3. Brain — step 1: decides to search the web

```
[Thinking] The user wants to know the latest breakthroughs in quantum computing
           specifically for the year 2026 and their practical implications. Since
           this requires current, real-world data and the planned step 1 is to
           perform an internet search ... No prior information is available yet to
           answer the question, so searching up-to-date sources is necessary.
[Decision] I need to search the web for more information.

TODO progress:   [in progress] Internet Search for Latest Quantum Computing Breakthroughs 2026
                 [not done]    Ready for Answer
```

Server log (tool execution):

```
[INTERNET_SEARCH] Searching: "latest breakthroughs in quantum computing 2026
                  practical applications" (depth: basic)
[INTERNET_SEARCH] Tavily direct answer: Quantum computing in 2026 is advancing
                  practical applications in security, pharmaceuticals, logistics,
                  and finance ... Major breakthroughs include IBM's quantum
                  advantage and fault-tolerant quantum computers.
[INTERNET_SEARCH] Retrieved 6 results — 1385 chars summarised
```

## 4. Brain — step 2: enough information, deliver the answer

```
[Thinking] The internet search results provided sufficient, relevant, and
           up-to-date information ... Key developments from credible sources were
           found including IBM's quantum advantage, fault-tolerant quantum
           computers, and practical applications across multiple industries.
[Decision] I have enough information to answer the user's question.

TODO progress:   [done]        Internet Search for Latest Quantum Computing Breakthroughs 2026
                 [in progress] Ready for Answer

[TheBrain] Tokens — prompt: 4170, cached: 3072, completion: 295
[TheBrain] Prompt cache HIT — 3072 tokens served from cache
```

## 5. Final answer delivered

```
Agent: In 2026, quantum computing has achieved several significant breakthroughs
that mark a pivotal shift from theoretical potential to practical, real-world
applications. ... Notably, IBM has announced reaching a milestone in quantum
advantage by the end of 2026 ...

### Key Breakthroughs in 2026

1. **IBM's Quantum Advantage**
   ... quantum systems are now able to outperform classical computers on specific,
   relevant computational tasks ...

2. **Fault-Tolerant Quantum Computing and Error Correction**
   ... logical qubits ... have paved the way for fault-tolerant quantum computers ...

3. **Majorana Qubits and Hardware Improvements**
   ... smaller, cheaper, and more stable quantum hardware ...

### Practical Implications Across Industries

- **Security: Quantum-Safe Encryption** ... quantum-resistant cryptography ...
- **Pharmaceuticals: Accelerated Drug Discovery** ... simulate molecular
  interactions with high precision ...
- **Logistics: Optimized Supply Chains** ... more efficient delivery routes,
  resource allocation, and inventory management ...
- **Finance: Faster and More Accurate Risk Modeling** ... risk management,
  portfolio optimization, and predictive modeling ...

### The 2026 Transition: From Potential to Practical Products

... a watershed year where quantum computing has moved beyond experimental setups
and is now delivering tangible products and solutions ...
```

*(Answer abridged here for readability — 3,768 characters in the original session; the full text is in [agent.log](agent.log).)*

## 6. Multi-turn: the session continues after the answer

The flow loops back to the brain, which detects `answer_delivered: true`, marks all
TODO items done, and asks a contextual follow-up:

```
[Thinking] The previous answer has been delivered successfully as indicated by
           'answer_delivered' being true. According to protocol, I must mark all
           planned TODO items as done and prompt the user with a relevant,
           contextual follow-up question to advance the conversation ...
[Decision] I need to ask the user a clarifying question.

TODO progress:   [done] Internet Search for Latest Quantum Computing Breakthroughs 2026
                 [done] Ready for Answer

Agent: Is there any specific industry or application area within quantum computing
       breakthroughs in 2026 that you want me to focus on more deeply in the summary?

You:   No thanks, that's everything. Bye!
```

## 7. Brain — step 4: user exit detected, session ends cleanly

```
[Thinking] The user has explicitly indicated that they do not want any further
           information ... I am choosing the 'end' tool to close the session with
           a farewell message.
[Decision] The session should end.

Agent: Goodbye! Have a great day!

[Session ended — status: successful]
```

Server log (session summary):

```
[END] Session complete — status: successful | steps: step 5 |
      tokens: 21596 (cached: 10240)
[StateMachine] ==================== Session complete ====================
```

---

## State trace (from [agent.log](agent.log))

```
Start → human_input → Planner → the brain → tool_router
      → Internet Search Handler → the brain → tool_router
      → Answer Question → the brain → tool_router
      → Collect More Information Handler → the brain → tool_router
      → End → EndFinal
```

Every hop above is one line in the server log (`[StateMachine] --- <state> (<function>)`),
so the full execution path of any session can be reconstructed from the log alone.
