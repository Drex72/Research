# Answering the handoff question

Notes for responding to the supervisor's two points: whether the handoff setting is common or important in tool-agent systems, and what is gained by extending an action-level code-switching attack to a handoff setup.

---

## 1. The paper they are thinking of is almost certainly MAPS, and it is translation, not code-switching

This distinction is the whole answer to the second half of their question, so it is worth making first and making precisely.

* **MAPS**, [Findings of EACL 2026, pp. 821 to 845](https://aclanthology.org/2026.findings-eacl.42/), arXiv 2505.15935.
* It is the only published work combining multilingual input with tool-using agents and a security component.
* **It contains zero mentions of code-switching, code-mixing or mixed language.** Every instance is translated wholly into one language.
* It is **single agent**, explicitly one agent per dataset, with no handoff.
* Its own scoping sentence: "We used the original English task definitions and their translations, without modifying or translating internal agent logic and processing flows like system prompts or tools." The tool layer stays English.
* Its security half inherits ASB, which scores whether the attacker's tool was **called**, on **simulated** tools. It never checks whether the action completed.

So if the supervisor has MAPS in mind, the honest reply is that it is a different input class, a different architecture and a different oracle.

## 2. No code-switching attack on tool-using agents exists

Searched arXiv, the ACL Anthology, Semantic Scholar and OpenReview.

* The community bibliography for this subfield, [gentaiscool/code-switching-papers](https://github.com/gentaiscool/code-switching-papers), returns **no entries at all** for agents, tool use, tool calling, function calling or agentic systems. Its only safety entry is CSRT.
* **CSRT** ([ACL 2025](https://aclanthology.org/2025.acl-long.657/)) genuinely mixes languages within a prompt, but has no agent, no tool call and no execution.
* **MASSIVE-Agents** ([Findings of EMNLP 2025](https://aclanthology.org/2025.findings-emnlp.1099.pdf)), 52 languages of function calling, is translated rather than code-switched, scores the syntax of generated calls rather than executing them, and is a capability benchmark rather than a safety one.
* **SEATauBench** (arXiv 2606.28715) translates tau2-bench into five Southeast Asian languages with real execution and state checking, but is translation, single agent, capability only. One detail worth borrowing: it "normalizes localized arguments to canonical English before execution", which is the same normalisation step this study proposes to measure rather than assume.

The four properties and who has them:

| | Code-switched input | Agent executes tools | Execution state checked | Multi-agent handoff |
|---|---|---|---|---|
| CSRT | Yes | No | No | No |
| MAPS | No, translated | Yes | Outcome only | No |
| MASSIVE-Agents | No, translated | No, syntax only | No | No |
| SEATauBench | No, translated | Yes | Yes | No |
| FinVault | No, English | Yes | Yes | No |
| **This study** | **Yes** | **Yes** | **Yes** | **Yes** |

Nothing has code-switching and tool execution together. Nothing at all has a handoff with any multilingual dimension.

## 3. Handoff is not an exotic setting, it is a first-class primitive everywhere

The strongest evidence is not a deployment survey, it is that six independent organisations have each shipped a named delegation primitive.

* **OpenAI Agents SDK**, [handoffs documentation](https://openai.github.io/openai-agents-python/handoffs/): "Handoffs allow an agent to delegate tasks to another agent." And the sentence that matters most here: **"Handoffs are represented as tools to the LLM. So if there's a handoff to an agent named `Refund Agent`, the tool would be called `transfer_to_refund_agent`."**
* **Microsoft AutoGen**, [handoffs pattern](https://microsoft.github.io/autogen/stable//user-guide/core-user-guide/design-patterns/handoffs.html): implemented as "a special tool call", and described as "a multi-agent design pattern introduced by OpenAI in an experimental project called Swarm".
* **CrewAI**, [collaboration docs](https://docs.crewai.com/en/concepts/collaboration): `allow_delegation=True` exposes `Delegate work to coworker(task, context, coworker)`.
* **LangGraph**: handoffs were "one of the primary motivators" for the `Command` type, and there is a dedicated `langgraph-swarm` package.
* **Anthropic subagents**, [documentation](https://code.claude.com/docs/en/sub-agents): "Each subagent runs in its own context window with a custom system prompt, specific tool access, and independent permissions."
* **Google Agent2Agent**, [announcement](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/): launched with "support and contributions from more than 50 technology partners" including Atlassian, Box, Cohere, Intuit, LangChain, MongoDB, PayPal, Salesforce, SAP, ServiceNow, UKG and Workday. Donated to the Linux Foundation in June 2025.

**The point to make to the supervisor:** in the OpenAI SDK and in AutoGen, a handoff **is** a tool call. So the handoff setting is not a separate research object bolted onto tool-agent work. It is the same mechanism, and an attack that reaches the tool layer reaches the handoff layer by construction.

**A caution on evidence.** I could not find a methodologically sound figure isolating multi-agent deployment. LangChain's *State of AI Agents* reports 51% of surveyed professionals running agents in production but does not disaggregate single from multi-agent. The "agent adoption statistics" pages that do give such numbers are vendor content. Rest the argument on the convergence of framework primitives, which is documented fact, rather than on a survey percentage.

## 4. The handoff is already recognised as its own attack surface

* **Agent-in-the-Middle**, [Findings of ACL 2025](https://aclanthology.org/2025.findings-acl.349/): "a novel attack that exploits the fundamental communication mechanisms in LLM-MAS by intercepting and manipulating inter-agent messages", motivated by the claim that "the vulnerability of the communication mechanisms in LLM-MAS remains largely underexplored". Success rates above 40% in all cases and above 70% in most.
* **Prompt Infection**, ESORICS 2025 workshops: prompts that "self-replicate across interconnected agents, behaving much like a computer virus".
* Multiple A2A protocol security papers, including [arXiv 2504.16902](https://arxiv.org/abs/2504.16902) and A2ASecBench.

So the field already agrees the inter-agent message is a distinct surface. What none of that work does is vary the **language** of the message.

## 5. What is actually gained by moving from action level to handoff

This is the substantive answer, and it is a claim about mechanism rather than about novelty for its own sake.

**At the action level**, the code-switched text and the tool call live in the same context. The model that reads the mixed language is the model that emits the call. Anything an input-side guardrail sees is what the acting model sees. The measurable question is whether mixed language degrades refusal.

**At a handoff**, the request is re-authored before it reaches the acting agent. This is documented framework behaviour, not speculation:

* Anthropic's subagent documentation: **"the subagent does that work in its own context and returns only the summary"**.
* Anthropic's [multi-agent research system write-up](https://www.anthropic.com/engineering/multi-agent-research-system): the lead agent "decomposes queries into subtasks and describes them to subagents", and each subagent "needs an objective, an output format, guidance on the tools and sources to use, and clear task boundaries". The lead agent writes that description itself.
* The OpenAI SDK ships `nest_handoff_history`, which "compacts summarizable history into ordered assistant summary segments", plus a `handoff_history_mapper` hook.
* CrewAI's delegation tool requires the delegating agent to compose a fresh `task` and `context` string, so the coworker receives the delegator's prose rather than the user's text.

That produces a failure mode that cannot exist at the action level:

* The **surface form** of the attack, the code-switching, is very likely destroyed by the rewrite.
* The **payload**, being the identifiers, amounts and requested operation, is likely to survive, because the rewrite is meant to preserve the task.
* Any guardrail sitting at the input sees mixed language, which prior work shows it detects poorly. Any guardrail sitting downstream sees clean English and no longer has the signal that would have flagged it.

The claim under test is therefore not "code-switching also works on agents". It is that **a handoff converts a detectable attack into an undetectable one while preserving its effect**, and that this is invisible to any evaluation that scores only the first agent's text.

**Why this is measurable rather than rhetorical.** The design measures surface survival and intent survival separately across the same handoff. Surface falling towards zero while intent stays high is the laundering effect, and guardrail detection on the raw input against the normalised output quantifies it directly.

**And why it needs execution grounding.** At the moment the surface disappears, a text-level or judge-level instrument stops being able to see the attack at all. Only a check on final sandbox state can tell you whether the action completed. That is the argument [AgentDojo](https://arxiv.org/abs/2406.13352) makes for refusing an LLM judge in injection work, and it applies with more force here, because the thing being laundered is precisely the evidence a judge would use.

## 6. Suggested framing for the reply

* Confirm the gap they identified, and thank them for it.
* Correct the premise gently: the action-level multilingual agent paper is MAPS, and it is translation rather than code-switching, single agent, with a tool-call oracle rather than an execution one.
* Make the handoff case on framework primitives, leading with the fact that in the OpenAI SDK and AutoGen a handoff **is** a tool call, so it is not a separate setting at all.
* Give the mechanism: the intermediate agent re-authors the request, which is documented, and that predicts surface loss with payload survival.
* State the contribution as the measurement, not the attack: separating surface survival from intent survival across a handoff, and pairing it with guardrail detection before and after, is what turns the intuition into a number.
* Concede honestly that if surface and intent both survive, or if both die, the laundering hypothesis is not supported. That is a legitimate possible finding and saying so strengthens the proposal.
