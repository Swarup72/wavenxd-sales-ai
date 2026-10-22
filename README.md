# WaveNxD AI Sales Representative

An intelligent, enterprise-grade AI technical sales representative and quotation system for WaveNxD ultrasonic nozzles, spray systems, and precision dispensing equipment. Built with a high-performance Python FastAPI modular monolith, Async PyMongo, MongoDB 7, and native browser ES modules.

---

## Architecture & Technology Stack

- **Backend**: Python 3.12, FastAPI, Pydantic v2, Async PyMongo, Motor-free native async PyMongo 4.9+ driver.
- **Database**: MongoDB 7.x (local instance on `mongodb://127.0.0.1:27017`).
- **Security & Auth**:
  - Stateful server-side session store with Argon2id password hashing.
  - Double-Submit CSRF cookie checking (`X-CSRF-Token` header validated against session cookie).
  - Multi-tenant company catalog scoping & strict product entitlement access control.
- **AI / LLM Orchestration**:
  - Primary LLM: Groq `llama-3.3-70b-versatile` with prompt-level parameter extraction and deterministic rule engine fallback.
  - Secondary LLM (Automatic Circuit Fallback): Google Gemini `gemini-1.5-flash` / `gemini-2.0-flash`.
  - Speech-to-Text (STT): Groq Whisper (`whisper-large-v3`) with multilingual support (EN, HI, MR).
  - Text-to-Speech (TTS): Gemini Flash Audio Synthesis with regional language playback.
- **Frontend**:
  - Customer Consultation Workspace: Light-first responsive design, real-time message stream, consultation parameter summary card, live microphone input level meter, quotation draft preview modal, email draft export, and follow-up calendar scheduler.
  - Admin Control Center: 11 comprehensive governance tabs including Overview, Companies, Users & Invitations, Product Catalog, Entitlement Assignments, Technical Review Queue, Consultations Support, Leads & Inquiries, Provider Health, Audit Trail, and System Settings.
  - Native browser ES modules (no Node.js build step or frontend bundlers required).

---

## Key Workflows & Features

### 1. Automatic WaveNxD Greeting (Phase 1)
When a customer creates a new consultation, the system immediately returns an initial assistant greeting without requiring the user to send the first message.
- Introduces the assistant as a WaveNxD technical sales representative.
- Explains the purpose of ultrasonic nozzle technology and asks for the customer's target application, coating material, and fluid properties.
- Deterministic, zero-cost greeting with language detection (English, Hindi, Marathi, Hinglish).

### 2. Structured Customer Lead Capture (Phase 2)
Customers can submit structured technical inquiries directly from their consultation:
- **Endpoint**: `POST /customer/leads`
- Automatically merges verified process parameters (flow rate, viscosity, droplet size, application) and evaluated product recommendations from the conversation.
- Validates contact details (customer name, company, email, optional phone) and enforces company isolation (customers can only bind leads to conversations belonging to their company).
- Prevents duplicate submissions idempotently.
- Stored in the MongoDB `leads` collection with indexed stages: `new`, `qualified`, `quote_draft`, `follow_up_requested`, `closed`.

### 3. Formal Quotation Preview & Export (Phase 3)
Customers can inspect and export formal quotation drafts backed strictly by company-authorized catalog data:
- **Endpoints**: `GET /customer/conversations/{id}/quote-preview` and `GET /customer/conversations/{id}/quote-preview/download`
- Produces a structured draft with quote reference (`WNXD-QUOTE-...`), date, customer/company profile, and verified process specifications.
- **Catalog Truth Guarantee**: Prices are strictly marked as `"Price on Application — Final pricing and commercial terms require confirmation by WaveNxD."` No invented prices, warranties, delivery dates, or currencies are ever generated.
- Flagged nozzles (e.g. 180 kHz stent coating nozzle) prominently display the required **Engineering Technical Review Warning**.
- Generates clean, standalone print-ready HTML (`@media print` rules) with navigation stripped out for direct browser printing or download.

### 4. Honest Email Quotation Workflow (Phase 4)
- **Endpoints**:
  - `GET /customer/conversations/{id}/email-draft`: Inspect recipient, subject, body, and status.
  - `GET /customer/conversations/{id}/email-draft/download`: Downloads a standard RFC 822 `.eml` draft file.
  - `POST /customer/conversations/{id}/email-simulate`: Simulates delivery for development/testing.
- **Honest Disclosure**: Because no paid SMTP/SES provider is configured by default under the ₹0 budget, the status is explicitly returned as `"preview"` or `"simulated"`, **never** as `"sent"`. The UI clearly states: *"This email draft has been prepared locally. It has not been sent to an external mail server."*

### 5. Follow-Up Scheduling & Calendar Export (Phase 5)
- **Endpoints**:
  - `POST /customer/conversations/{id}/follow-up`: Registers proposed follow-up datetime, timezone, and duration against the lead.
  - `GET /customer/conversations/{id}/follow-up/calendar.ics`: Generates an RFC 5545 standard `.ics` calendar invitation file.
- **Calendar Compatibility**: Formats valid `BEGIN:VCALENDAR`, `VERSION:2.0`, `BEGIN:VEVENT` blocks with UTC timestamps (`DTSTART`, `DTEND`), UID, summary, notes, and line-folding (75 octets).
- Provides an optional Google Calendar URL link for one-click browser import.
- **Honest Wording**: Wording explicitly states: *"Your follow-up invitation has been prepared. Download the calendar file and add it to your calendar."* It does **not** claim a meeting is automatically booked on a sales engineer's live calendar.

### 6. Accessible Audio Level Meter & Voice Processing (Phase 6)
- The voice recording bar features a live microphone activity meter powered by browser `AudioContext` and `AnalyserNode` APIs.
- Animates based on real input volume and reflects accessibility attributes (`role="progressbar"`, `aria-valuenow`).
- Safely cleans up all audio contexts and media tracks upon stop or cancellation.
- Transcribes audio sequentially via Groq Whisper (`whisper-large-v3`) with speech playback via Gemini TTS.

### 7. Administrative Lead & Inquiries Governance (Phase 8 & 9)
The WaveNxD Admin Control Center includes a dedicated **Leads & Inquiries** tab:
- **Endpoints**: `GET /admin/leads`, `GET /admin/leads/{id}`, `PATCH /admin/leads/{id}`, `GET /admin/leads/export/csv`.
- Filter by company and lead stage (`new`, `qualified`, `quote_draft`, `follow_up_requested`, `closed`).
- Lead inspection modal displays technical process parameters, customer notes, equipment recommendations, conversation reference, and follow-up status.
- Administrators can update stage and log internal engineering notes with complete audit trail logging.
- **Formula Injection Sanitization**: CSV export strictly adheres to OWASP recommendations by neutralizing dangerous formula characters (`=`, `+`, `-`, `@`, `\t`, `\r`) with single-quote prefixing.

---

## Environment Variables & Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Key environment configuration (from `.env.example`):

```env
APP_NAME="WaveNxD AI Sales Representative"
APP_ENV="development"
MONGODB_URI="mongodb://127.0.0.1:27017"
MONGODB_DATABASE="wavenxd_sales"

# AI Provider Credentials (Optional for mock/offline testing; required for live speech/LLM)
GROQ_API_KEY="your_groq_api_key_here"
GEMINI_API_KEY="your_gemini_api_key_here"

# Primary & Fallback Model Settings
LLM_PROVIDER="groq"
GROQ_MODEL="qwen/qwen3.8-27b"
LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_PROVIDER="gemini"
GEMINI_MODEL="gemini-3.8-flash"

# Voice STT & TTS Settings
STT_PROVIDER="groq"
GROQ_WHISPER_MODEL="whisper-large-v3"
TTS_PROVIDER="gemini"
GEMINI_TTS_MODEL="gemini-3.8-flash-lite-tts"
```

*Note: Never commit real API keys or credentials to version control.*

---

## Running Locally

1. **Activate virtual environment**:
   ```bash
   source ./.venv/bin/activate
   ```

2. **Ensure MongoDB is running**:
   ```bash
   mongosh --eval "db.adminCommand('ping')"
   ```

3. **Start the FastAPI server**:
   ```bash
   ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

4. **Access the application**:
   - Customer Workspace: [http://127.0.0.1:8000/app](http://127.0.0.1:8000/app)
   - Admin Control Center: [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin)
   - OpenAPI Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Test Personas
- **Alice (Alpha Pharma Ltd)**: `alice@alphapharma.com` / `ValidCustPass123!` (Medical stent coating, authorized for medical nozzles).
- **Bob (Beta Coatings Corp)**: `bob@betacoatings.com` / `ValidCustPass123!` (Industrial glass & electronics coatings).
- **Admin (WaveNxD Internal)**: `admin@wavenxd.com` / `ValidAdminPass123!` (Full platform governance).

---

## Testing & Quality Assurance

### 1. Automated Python Test Suite
Run the complete backend test suite:
```bash
./.venv/bin/python -m pytest -q
```
*Current status: 183 passed tests covering greetings, lead workflows, quotation previews, RFC 822 email drafts, RFC 5545 .ics calendars, double-submit CSRF, Argon2id security, company catalog scoping, quota circuit fallbacks, and OWASP formula injection sanitization.*

### 2. Browser Smoke & Regression Test
Run the headless Google Chrome DevTools Protocol smoke test:
```bash
WAVENXD_ADMIN_PASSWORD='ValidAdminPass123!' WAVENXD_VIEWPORTS='1440x900,1024x768,390x844' node tests/browser/admin_portal_smoke.mjs
```
*Verifies login, CSRF, all 11 admin tabs across desktop, tablet, and mobile viewports, modal closing via Escape, single-flight data fetching, and zero console/network errors.*

---

## Manual Voice Smoke-Test Procedure

To test Speech-to-Text (STT) and Text-to-Speech (TTS) with free-tier credentials:

1. **Microphone Permission & Input Level**:
   - Open [http://127.0.0.1:8000/app](http://127.0.0.1:8000/app) and sign in as Alice.
   - Click the microphone icon. Grant browser permission when prompted.
   - Speak into the microphone. Verify that the green volume meter bar (`#recAudioLevel`) in the recording status bar fluctuates dynamically in response to your voice.
   - Click **Cancel** and verify that the recording bar dismisses and the microphone stream is immediately released.

2. **English Speech-to-Text (STT)**:
   - Click the microphone icon again. Say: *"We need an ultrasonic nozzle for balloon catheter drug coating with a flow rate of 1.5 ml/min and 15 cP viscosity."*
   - Click **Done & Transcribe**.
   - Verify the Groq Whisper transcription populates the chat and deterministic product recommendations evaluate compatibility.

3. **Regional Language Audio (Hindi & Marathi)**:
   - Click the microphone icon. Speak in Hindi: *"हमे 2 ml प्रति मिनट फ्लो रेट के लिए अल्ट्रासोनिक नोजल चाहिए।"* (Or Marathi: *"आम्हाला अल्ट्रासोनिक नोझल हवे आहे."*)
   - Submit and verify Whisper transcribes the audio accurately. The WaveNxD assistant will acknowledge the requirements in the appropriate language.

4. **Speech Synthesis (Gemini TTS)**:
   - On any assistant response message, click the **🔊 Listen** button.
   - Verify the button transitions to **⏳ Synthesizing...** then **⏸ Pause** as synthesized audio streams cleanly through browser audio output.
   - Click **Pause** to verify playback stops and resources are revoked.

5. **Graceful Fallback on Quota or Missing Keys**:
   - If `GROQ_API_KEY` or `GEMINI_API_KEY` is not configured, the UI cleanly informs the user via toast notification without breaking text-based consultations or freezing the input composer.

---

## Integration Status & Honest Disclosure

| Capability | Status | Implementation Details |
|---|---|---|
| Automatic Greeting | **Live & Verified** | Deterministic, multi-lingual P0 greeting persisted on conversation creation. |
| Deterministic Recommendation Engine | **Live & Verified** | Catalog-backed compatibility evaluation with company-scoped product isolation. |
| Customer Lead Capture | **Live & Verified** | MongoDB-backed, idempotent, company-isolated lead capture with audit trails. |
| Quotation Draft Preview | **Live & Verified** | Authorized catalog data; strictly displays *"Price on Application"*; print-ready HTML export. |
| Email Quotation Draft | **Live Local Draft** | RFC 822 `.eml` file download & simulation mode; honestly disclaimed as draft (not sent). |
| Calendar Follow-Up | **Live Local Export**| RFC 5545 `.ics` file generation with UTC timestamps & Google Calendar URL; no live server booking. |
| Audio Activity Level Meter | **Live & Verified** | Browser `AudioContext` & `AnalyserNode` with accessible progress bar and clean teardown. |
| STT / TTS Voice Services | **Live (Creds Dependent)**| Fully functional when Groq/Gemini keys are present; unit-tested with robust mocks & fallbacks. |
| Admin Portal (11 Tabs) | **Live & Verified** | Full CRUD, reviews queue, audit log, leads management, and OWASP formula-sanitized CSV export. |
