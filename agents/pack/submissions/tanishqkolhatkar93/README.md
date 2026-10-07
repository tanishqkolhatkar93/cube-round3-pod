# 📦 Pack Manager AI

**🚀 Live Deployment:** [https://tanishqkolhatkar93-package-manager.streamlit.app/](https://tanishqkolhatkar93-package-manager.streamlit.app/)

**Author:** Tanishq Kolhatkar 

**Mail Id**  - tanishqkolhatkar93@gmail.com   | [Linkedln](https://www.linkedin.com/in/tanishq93/)

An AI-powered quality control agent that inspects open shipping boxes before sealing, prevents costly fulfillment errors, and leaves a cryptographic audit trail for 3PLs and self-fulfilling sellers.

---

## Expected layout
```text
submissions/tanishqkolhatkar93/
├── README.md            ← this file: who you are, links to everything below
├── 01-customer-letter.md
├── 02-prfaq.md          ← include the questions you'd rather not answer
├── 03-one-pager.md      ← metrics table + at least one kill condition
├── CLAUDE.md            ← durable constraints, hard rules, forbidden language
├── build-brief.md
├── build-log.md         ← keep it current; organisers read it
├── eval-report.md       ← method, two-labeller agreement, per-check FP / FN, failure modes
├── contract/            ← your evidence-record shape, as agreed with the other pods
└── agent/               ← your code (headless first)
```

## Status
| Face | Deliverable | Status |
| :--- | :--- | :--- |
| 1 | Customer letter, PR/FAQ, one-pager | [x] |
| 2 | CLAUDE.md | [x] |
| 3 | Headless agent on fixtures | [x] |
| 4 | Eval report | [x] |
| 5 | Evidence record page | [x] |
| 6 | Cross-pod contract | [x] |

## Kill condition
If the False Positive Rate (where the AI tells the operator to SEAL a box that is actually missing items or contains wrong items) exceeds 1.0% in warehouse staging.

---

## 🧠 Problem Understanding
An outbound order is picked and placed into a box. Before the box is sealed, someone needs to verify: **Does the box contain exactly what the customer ordered?** A wrong item or incorrect quantity can lead to refunds, returns, replacement shipments and poor customer experience.

## 💡 The Solution

In high-volume fulfillment operations, packing mistakes lead to returns, expensive reshipments, and retailer chargebacks.
**Pack Manager AI** acts as a sub-second visual gatekeeper at the packing table:
1. Overhead cameras snap an image of the open shipping carton.
2. The agent compares visual contents against the expected order lines.
3. It issues a deterministic operational verdict (**SEAL**, **STOP & FIX**, **UNCERTAIN**, or **PENDING**).
4. Every decision is cryptographically hashed and saved in the `contract/` folder for non-repudiation.

## ⚡ Setup & Execution

### Running via Streamlit Community Cloud
The application is designed with a dual-mode architecture and is actively deployed. You do not need to run it locally to evaluate it.
1. Visit the live URL at the top of this README.
2. Open the **⚙️ Settings > 🔑 API Key Config** sidebar.
3. Paste your Gemini API key and click **Validate Key**.
4. Upload an image and verify!

### Test Inputs (Sample Data)
To evaluate the agent, try the following test scenario in the UI:
1. **Unit ID:** UNIT-TEST-01
2. **Order ID:** ORD-9999
3. **Expected Order Lines:** KEYBOARD: 1; MOUSE: 1; USB_CABLE: 1
4. **Image Upload:** Upload a clear overhead photo matching (or intentionally violating) these items to see the SEAL or STOP & FIX logic trigger.

### Running Locally
```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add API key to environment
# Edit agent/.env to include GEMINI_API_KEY="your_key"

# 3. Start Backend (Terminal 1)
cd agent
uvicorn main:app --reload --env-file .env --port 8000

# 4. Start Frontend (Terminal 2)
streamlit run app.py
```

## ⚠️ Assumptions & Limitations

### Assumptions
1. **Lighting and Angle:** We assume the packing station has adequate lighting and an overhead camera providing a clear, top-down perspective into the open carton.
2. **Tenant Isolation:** All requests are isolated across distinct 3PL warehouse clients via the `x-org-id` header to guarantee Row-Level Security.

### Limitations / Failure Modes
1. **Vertical Textile Occlusion:** Identical folded soft goods (e.g. 3 stacked black shirts) cannot be counted accurately if the bottom layers are fully hidden.
2. **Identical Packaging in Varied Sizes:** Products sharing exact identical box designs without readable text require manual barcode scan pairing.
3. **Opaque Sub-Packaging:** Items inside sealed opaque polybags (like screws or cables) cannot be inspected internally by the vision model.
