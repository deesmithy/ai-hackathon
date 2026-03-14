# Superintendent AI — QA Test Sheet

## Prerequisites
- [ ] Python 3.11+ installed
- [ ] `ANTHROPIC_API_KEY` set in `.env` (required for AI features)
- [ ] `RESEND_API_KEY` set in `.env` (optional — emails stub without it)
- [ ] `GMAIL_USER` + `GMAIL_APP_PASSWORD` set in `.env` (optional — polling disabled without it)

## Phase 1: Foundation
| # | Test | Steps | Expected | Pass? |
|---|------|-------|----------|-------|
| 1.1 | Dependencies install | `pip install -r requirements.txt` | All packages install without errors | [ ] |
| 1.2 | Server starts | `python main.py` | Uvicorn running on port 8000, "Seeded 10 contractors" in logs | [ ] |
| 1.3 | DB file created | Check for `superintendent.db` in project root | File exists after server start | [ ] |
| 1.4 | Dashboard loads | Open http://localhost:8000 | Page renders with nav bar, "No projects yet" message | [ ] |

## Phase 2: Contractors
| # | Test | Steps | Expected | Pass? |
|---|------|-------|----------|-------|
| 2.1 | Contractor roster page | Navigate to http://localhost:8000/contractors | Table shows 10 seeded contractors with names, specialties, ratings | [ ] |
| 2.2 | Add contractor via UI | Click "+ Add Contractor", fill form, click Save | New contractor appears in table | [ ] |
| 2.3 | API: list contractors | `curl http://localhost:8000/api/contractors/` | JSON array of 10+ contractors | [ ] |
| 2.4 | API: create contractor | `curl -X POST .../api/contractors/ -H 'Content-Type: application/json' -d '{"name":"Test","email":"test@test.com","specialty":"framing"}'` | Returns new contractor JSON with ID | [ ] |
| 2.5 | Specialties covered | Check contractor list | At least: framing, electrical, plumbing, roofing, hvac, painting, concrete, drywall, flooring, landscaping | [ ] |

## Phase 3: AI Plan Generation
| # | Test | Steps | Expected | Pass? |
|---|------|-------|----------|-------|
| 3.1 | New project page loads | Navigate to http://localhost:8000/projects/new | Form with name, description, dates, "Generate Plan" button | [ ] |
| 3.2 | Create + generate plan | Enter "3-Bedroom House at 123 Main St" with description, click Generate Plan | Loading spinner appears, then plan text + task list appears below | [ ] |
| 3.3 | Tasks created in DB | `curl http://localhost:8000/api/tasks/by-project/1` | JSON array of 5-15 tasks with names, specialties, sequence orders | [ ] |
| 3.4 | Plan saved to project | `curl http://localhost:8000/api/projects/1` | `ai_plan` field is populated | [ ] |
| 3.5 | Dashboard shows project | Navigate to http://localhost:8000 | Project card appears with "Planning" badge | [ ] |

## Phase 4: Contractor Assignment
| # | Test | Steps | Expected | Pass? |
|---|------|-------|----------|-------|
| 4.1 | Confirm & assign | After plan generation, click "Confirm & Assign Contractors" | Redirects to project detail page | [ ] |
| 4.2 | Tasks show contractors | Project detail page task table | "Contractor" column populated for each task | [ ] |
| 4.3 | Task status updated | Check task statuses | Tasks moved from "pending" to "assigned" | [ ] |
| 4.4 | Project status active | Check project status badge | Shows "Active" (not "Planning") | [ ] |
| 4.5 | API verify | `curl http://localhost:8000/api/tasks/by-project/1` | Tasks have `status: "assigned"` | [ ] |

## Phase 5: Email Outreach
| # | Test | Steps | Expected | Pass? |
|---|------|-------|----------|-------|
| 5.1 | Run outreach button | On project detail page, click "Run Outreach" | Loading spinner, then "Outreach Sent!" | [ ] |
| 5.2 | Emails logged | Navigate to http://localhost:8000/emails | Outbound emails listed with [SUP-{id}] subjects | [ ] |
| 5.3 | Email body quality | Check email bodies | Professional, includes project name, task details, asks for confirmation | [ ] |
| 5.4 | Task status updated | Check project detail task statuses | Tasks moved to "Outreach Sent" | [ ] |
| 5.5 | Stub mode (no Resend key) | Run without RESEND_API_KEY | Console shows "[EMAIL STUB]" messages, emails still logged in DB | [ ] |
| 5.6 | Real email (with Resend key) | Set valid RESEND_API_KEY, run outreach | Email arrives in contractor's inbox with [SUP-{id}] subject | [ ] |

## Phase 6: Inbound Email Processing
| # | Test | Steps | Expected | Pass? |
|---|------|-------|----------|-------|
| 6.1 | Process reply API | `curl -X POST .../api/agent/process-reply -H 'Content-Type: application/json' -d '{"from_email":"mike@example.com","subject":"Re: [SUP-1] Framing","body":"I can do this, available starting next Monday."}'` | Returns result with acceptance detection | [ ] |
| 6.2 | Task status updates | Check task after acceptance reply | Status changes to "committed" | [ ] |
| 6.3 | Decline handling | Send decline reply via API | Outreach entry marked "declined" | [ ] |
| 6.4 | Gmail polling (if configured) | Set Gmail credentials, send test reply | Auto-detected within 5 minutes, task updated | [ ] |

## Phase 7: Status Monitoring + Alerts
| # | Test | Steps | Expected | Pass? |
|---|------|-------|----------|-------|
| 7.1 | Check status button | On project detail, click "Check Status" | Loading spinner, then "Check Complete!" | [ ] |
| 7.2 | Alerts appear | After status check, refresh page | Yellow alert banners appear for any flagged issues | [ ] |
| 7.3 | Dashboard alerts | Navigate to http://localhost:8000 | Unread alerts shown at top of dashboard | [ ] |
| 7.4 | Alert types | Verify alert content | Appropriate types: behind_schedule, no_response, task_blocked, risk | [ ] |

## Phase 8: UI Polish
| # | Test | Steps | Expected | Pass? |
|---|------|-------|----------|-------|
| 8.1 | Nav links work | Click each nav link | Dashboard, New Project, Contractors, Email Log all load | [ ] |
| 8.2 | Status badges | Check all status badges | Correct colors: planning=gray, active=green, behind=red, at_risk=yellow, complete=blue | [ ] |
| 8.3 | Responsive layout | Resize browser window | Layout adjusts (cards stack on mobile) | [ ] |
| 8.4 | Loading spinners | Trigger any AI action | Spinner shows during processing, disappears on completion | [ ] |
| 8.5 | Empty states | View pages with no data | Friendly empty state messages (not blank/broken) | [ ] |

## End-to-End Happy Path
| # | Step | Action | Expected |
|---|------|--------|----------|
| E1 | Start server | `python main.py` | Server running, 10 contractors seeded |
| E2 | Verify contractors | Go to /contractors | 10 contractors across 10 specialties |
| E3 | Create project | Go to /projects/new, enter "Build a 3-bedroom house at 123 Main St" with description | Form accepts input |
| E4 | Generate plan | Click "Generate Plan" | AI creates 5-15 construction tasks |
| E5 | Assign contractors | Click "Confirm & Assign Contractors" | Tasks assigned, project goes "Active" |
| E6 | Run outreach | Click "Run Outreach" on project detail | Emails sent/stubbed, logged in email log |
| E7 | Process reply | POST to /api/agent/process-reply with acceptance email | Task status → "committed" |
| E8 | Check status | Click "Check Status" | Alerts generated for any issues |
| E9 | Dashboard | Go to / | Project card with status badge, alert banner |

## Known Limitations for Demo
- Email sending requires valid Resend API key and verified domain
- Gmail polling requires Gmail App Password (not regular password)
- SQLite is single-writer; fine for demo, not production
- No authentication/authorization on endpoints
