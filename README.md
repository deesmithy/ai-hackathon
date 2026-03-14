# Cliff — AI Construction Superintendent

> **Cliff is a fully autonomous AI agent that manages construction projects end-to-end:** planning tasks, selecting contractors, negotiating schedules, handling all email communication, escalating problems, firing non-performing contractors and replacing them — with near-zero human involvement.

---

## What It Does

Construction project management is broken. A superintendent's day is dominated by repetitive, high-stakes communication: emailing contractors, chasing non-responses, rescheduling when someone bails, coordinating dependencies between trades. It's time-consuming, error-prone, and doesn't scale.

**Cliff replaces that entire workflow with an autonomous AI agent.**

A project owner describes their project in plain English. Cliff takes it from there:

1. Generates a sequenced task plan with trade assignments and estimated durations
2. Selects the best contractor for each task from a rated roster
3. Sends professional outreach emails to every contractor simultaneously
4. Negotiates confirmed start/end dates with each contractor, respecting upstream dependencies
5. Monitors the project daily — flags schedule risk, chases non-responses, escalates blockers
6. When a contractor declines or goes silent: automatically moves to the next in the queue, or offers a 10% bonus when the queue is exhausted
7. Autonomously detects when a committed contractor has ghosted, handles the full replacement workflow, and generates an executive summary of how the situation was handled
8. Responds intelligently to any inbound contractor email — questions, pushback, anger, legal threats — and loops in the human superintendent only when it genuinely can't handle something

---

## Judging Criteria

### Autonomy — 40%

**Cliff operates almost entirely without human input. Here is exactly what it does on its own:**

#### From Zero to Active Project in One Click

When a project is created, Cliff immediately and autonomously:
- Analyzes the plain-English description and generates a sequenced construction task plan (5–15 tasks, correctly ordered: foundation → framing → rough-ins → drywall → finishes)
- Queries the contractor roster, matches each task to the best available contractor by specialty + ratings
- Drafts and sends professional outreach emails to all contractors simultaneously using a single structured API call

No human selects contractors. No human writes emails. No human presses "send."

#### Autonomous Date Negotiation Chain

After a contractor accepts a task, Cliff autonomously:
- Checks the contractor's committed schedule **across all active projects** to detect conflicts
- Proposes specific start/end dates that respect upstream task dependencies
- If the contractor counter-proposes conflicting dates, Cliff explains why those dates don't work and proposes valid alternatives
- When dates are confirmed, Cliff **cascades** — automatically triggering date negotiation for every downstream dependent task whose upstream is now locked in

This negotiation chain runs through the entire project dependency graph without any human involvement.

#### Contractor Failure Recovery

When a contractor fails to respond or declines:
- Cliff marks them as declined/no-response in the outreach queue
- Immediately moves to the next contractor in the ranked queue and sends fresh outreach
- If the entire queue is exhausted, Cliff searches the full roster for anyone with matching specialty and reaches out with a **10% bonus incentive**
- Creates a superintendent alert only when truly stuck with no options

#### Termination Workflow

When a committed contractor ghosts the project, Cliff autonomously:
1. Detects the commitment failure during the daily 8am status sweep
2. Recommends termination with a clear, evidence-based reason (superintendent approves or cancels — the one human checkpoint)
3. Sends an availability inquiry to the best available replacement
4. When replacement confirms, sends the termination notice to the fired contractor (professional tone, references 50% pay clause)
5. Confirms the new contract with the replacement
6. Processes whatever reply the fired contractor sends — calm acceptance, anger, legal threats — and handles it appropriately
7. Generates a full executive summary of how the situation was handled

#### Reply Processing at Scale

Cliff reads every inbound email and autonomously decides what to do:
- **Acceptance** → marks task committed, confirms assignment details, triggers date negotiation
- **Decline** → thanks them professionally, immediately escalates to next contractor
- **Question** → answers from project context and replies directly
- **Anger or pushback** → de-escalates without making unauthorized commitments
- **Legal threat** → sends professional acknowledgment and creates superintendent alert
- **Ambiguous** → asks for a clear yes/no to keep the schedule moving

The only emails Cliff doesn't handle fully on its own are those requiring genuine business judgment — payment disputes outside standard terms, major scope renegotiations — where it creates a detailed alert and hands off cleanly.

#### Continuous Background Monitoring

- **Every 30 seconds**: auto-reply simulator generates realistic contractor responses; the poller picks them up and runs the full reply pipeline
- **Every 8am daily**: status monitor sweeps every active project, flags schedule risk, marks no-responses, escalates to next contractors, and recommends terminations for committed-then-ghosted contractors

**Human touchpoints in a full project lifecycle: 2.** Project creation (plain-English description) and termination approval. Everything else is Cliff.

---

### Value — 30%

#### The Problem Is Real and Large

The U.S. construction industry generates ~$2.1 trillion annually and is one of the least digitized sectors in the economy. A typical residential or light commercial superintendent manages 8–15 concurrent subcontractor relationships per project, across multiple active projects simultaneously. The majority of their time is consumed by:

- Writing and tracking contractor outreach emails
- Chasing non-responses (industry average: 30–40% of contractors don't reply to initial outreach)
- Rescheduling when a contractor bails or runs over
- Managing date conflicts between dependent trades
- Drafting termination notices and finding replacements under time pressure

This is high-stakes, high-volume communication work that is tedious for experienced superintendents and nearly impossible for smaller operators without dedicated admin staff.

#### What Cliff Delivers

| Without Cliff | With Cliff |
|---|---|
| Hours per week writing outreach emails | Seconds — fully automated on project creation |
| Manual follow-up calls for non-responses | Autonomous escalation to next contractor |
| Ad hoc rescheduling when someone bails | Automated cascade rescheduling across dependency chain |
| Weeks to draft a termination notice | Minutes — AI-drafted, professionally worded, executive summary included |
| Superintendent required for every decision | Superintendent reviews exceptions only |
| No visibility for project owners | Real-time buyer progress portal |

#### Business Viability

Cliff is SaaS-native. Natural pricing: per-active-project or per-contractor-interaction, both of which align tightly with value delivered. Target customers:

- **GCs and superintendents** managing residential/light commercial projects who need to scale without hiring coordinators
- **Property developers** running multiple concurrent projects who need visibility without micromanagement
- **Owner-builders** who lack the industry relationships and communication expertise of a seasoned superintendent

The buyer-facing progress view (`/progress/{project_id}`) demonstrates a second product surface: a real-time progress portal that homeowners and developers can check without calling anyone.

---

### Technical Complexity — 20%

#### Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    FastAPI Application                    │
│  ┌──────────┐  ┌───────────┐  ┌─────────────────────┐   │
│  │  Routers │  │ Templates │  │  APScheduler        │   │
│  │ /api/... │  │ Jinja2 +  │  │  - 8am status sweep │   │
│  │          │  │ Alpine.js │  │  - 30s simulator    │   │
│  └────┬─────┘  └───────────┘  │  - 30s poller       │   │
│       │                        └─────────────────────┘   │
└───────┼──────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│                   Agent Orchestration                     │
│                                                          │
│  run_agent(mode, message)   ← agentic tool-use loop      │
│  ├── reply_processor        ← handles any inbound email  │
│  ├── status_monitor         ← daily project health check │
│  ├── date_negotiator        ← proposes + confirms dates  │
│  ├── followup_responder     ← continues live threads     │
│  ├── termination_advisor    ← evaluates + recommends     │
│  ├── termination_executor   ← sends notices + contracts  │
│  └── termination_summarizer ← executive summary          │
│                                                          │
│  structured output (single-call)                         │
│  ├── generate_tasks_direct  ← forced submit_tasks tool   │
│  └── assign_and_draft_direct← assignments + emails, all  │
│                               tasks in parallel           │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│                    Tool Layer (15 tools)                  │
│                                                          │
│  get_project_context      get_contractor_roster          │
│  get_email_threads        get_contractor_schedule        │
│  get_outreach_queue       get_termination_flow           │
│  assign_contractor        mark_outreach_status           │
│  send_email               update_task_status             │
│  create_alert             update_project_status          │
│  create_termination_flow  advance_termination_flow       │
│  save_termination_summary                                │
│                                                          │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│              SQLite via SQLAlchemy ORM                    │
│  Projects · Tasks · Contractors · OutreachQueue           │
│  Emails · Alerts · TerminationFlows · AgentActions       │
└──────────────────────────────────────────────────────────┘
```

#### Multi-Mode Agent Architecture

Cliff uses **9 distinct agent modes**, each with its own system prompt and restricted tool set. This is a deliberate design decision:

- Prevents prompt bloat — each agent is focused on one job
- Eliminates tool hallucination — an agent can only call tools it actually needs
- Enables independent tuning of each agent's behavior without affecting others
- Makes the system auditable — the Agent Log shows which mode took which action

Two modes use **structured output** (forced `tool_choice`) for deterministic, fast, parallel execution:
- `generate_tasks_direct` — returns a validated JSON array of tasks in a single API call
- `assign_and_draft_direct` — returns contractor assignments + fully drafted outreach emails for all tasks in one call

The remaining 7 modes run an **agentic tool-use loop** (up to 20 iterations), allowing Claude to reason through multi-step problems, branch based on what it discovers, and chain tool calls as the situation requires.

#### Autonomous Cascade Chains

The date negotiation cascade is the most technically sophisticated behavior in the system:

```
Contractor accepts task
  └─▶ reply_processor detects status → "committed"
        └─▶ checks upstream dependency has dates_confirmed = True
              └─▶ triggers date_negotiator for this task
                    └─▶ get_contractor_schedule() checks bookings across ALL projects
                          └─▶ if conflict: recalculates valid dates, updates task
                                └─▶ sends date proposal email to contractor
                                      └─▶ contractor confirms
                                            └─▶ reply_processor detects dates_confirmed = True
                                                  └─▶ finds ALL downstream dependent tasks
                                                        └─▶ triggers date_negotiator for each
                                                              └─▶ (chain continues)
```

This runs entirely autonomously, respects the full dependency graph, avoids double-booking contractors across projects, and propagates changes downstream without human involvement.

#### Action Logging

Every state-changing tool call is persisted to an `AgentActions` table with human-readable descriptions, timestamps, and the agent mode that triggered it. The Agent Log tab in the UI shows the complete audit trail — judges can see exactly what Cliff decided, why, and in what order.

#### Key Technical Details

- **Stack**: Python 3.9, FastAPI, SQLAlchemy, SQLite, APScheduler, Alpine.js, Tailwind CSS
- **AI**: Claude Sonnet 4.6 via Anthropic SDK with native tool use
- **Parallel execution**: Tool calls within a single agent turn execute concurrently via `ThreadPoolExecutor`
- **Live UI**: Task table polls `/api/projects/{id}/live-status` every 15 seconds; status updates without page reload
- **Dependency-aware scheduling**: Auto-schedules all tasks on project creation; recalculates downstream tasks when upstream dates change, skipping tasks whose dates are already contractor-confirmed
- **Inject Email UI**: `/projects/{id}/inject-email` lets anyone simulate a contractor sending any email, triggering the full reply pipeline instantly — built specifically for live demos

---

### Demo + Presentation — 10%

#### The Demo Flow (5 minutes, zero setup)

**Step 1 — Create a project.**
Enter a plain-English description: *"Kitchen remodel, 800 sq ft. Demo existing layout, new custom cabinets, tile backsplash, under-cabinet lighting, new sink and dishwasher plumbing, patch and paint."* Click Create. Before the page finishes loading, Cliff has generated the task plan, assigned contractors, and sent outreach emails to all of them.

**Step 2 — Watch the Agent Log.**
Switch to the Agent Log tab. See every action Cliff took: which emails were sent, which contractors were assigned, what the AI decided and when. The system is not a black box.

**Step 3 — Inject a contractor reply.**
Click "Inject Email." Select a task and contractor, write any response — an acceptance, a question, an angry pushback. Submit. Watch Cliff respond in real time: updating the task status, sending a reply email, triggering date negotiation, or creating a superintendent alert if it's something requiring human judgment.

**Step 4 — Run the termination demo.**
Go to the Terminations tab, click "Run Demo." In ~60 seconds, Cliff:
- Selects a contractor and fires them for unresponsiveness
- Finds a replacement and sends availability inquiry
- Simulates the replacement confirming
- Sends the termination notice to the fired contractor
- Generates a randomized emotional reply from the fired contractor (5 variants: anger, apology, acceptance, confusion, disappointment)
- Processes that reply and responds appropriately
- Marks the flow complete and generates an executive summary in markdown

**Step 5 — Check the Emails tab.**
The complete email thread for every contractor is preserved — both directions, full content, timestamps. The full paper trail of a construction project, generated autonomously.

**Step 6 — Show the buyer view.**
Open `/progress/{project_id}` in a new tab. This is what a homeowner or developer sees: a clean, real-time progress tracker with no logins, no coordination needed.

#### UI Highlights

- **Progress modal**: Every AI operation shows a step-by-step status modal so users understand what's happening during multi-second operations — never a spinning wheel with no context
- **Calendar**: Visual schedule with solid (confirmed) vs. dashed (tentative) task blocks, updating live as contractors confirm dates
- **Tabs**: Tasks & Schedule, Emails, Terminations, Agent Log — clean separation of concerns
- **AI-rendered markdown**: Plans and executive summaries render as formatted prose, not raw text

---

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
python main.py
```

Open http://localhost:8000

The contractor reply simulator runs automatically every 30 seconds — within a minute of creating a project and sending outreach, you'll see simulated contractor replies being processed and the project state evolving autonomously.

---

## The One-Sentence Pitch

**Cliff is the first AI agent that can take a construction project from a plain-English description to a fully scheduled, contracted, and actively managed job site — autonomously.**
