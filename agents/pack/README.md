# Cube Buildathon - 03 - Pack Manager

**Commerce Context stream - Round 2 - Individual Build**

## Integrated Architecture
This agent performs **Vision-based Pack Verification** using Gemini Flash Lite to ensure a box is packed accurately before it is sealed. It has been successfully integrated into the **Round 3 Pod Orchestrator**.

### Key Features
* **Shared Contract Native:** Listens via `handle(request)` to intercept structured JSON inputs.
* **Intelligent Output Verification:** Leverages the migrated `vision.py` analyzer from Round 2.
* **Strict Evidence Structuring:** Translates raw AI responses into the standardized `Evidence Record` with `PASS`, `FAIL`, and `UNCERTAIN` state handling, as demanded by the workflow constraints.
* **Fail-Safe Processing:** In the event an image fails to load or the AI times out, it gracefully outputs an `UNCERTAIN` evidence record that is passed to human operators, rather than crashing the pipeline.

### Integration Progress
* `app.py` acts as the contract bridge, parsing `request["subject"]` and routing `photo_refs`.
* Fully passes tenant isolation constraints (e.g. cross-tenant requests from `org_demo_bravo` attempting to access `org_demo_alpha` files are securely rejected).
* `agent.json` properly registers as `pack-manager@1`.
* Re-uses the original Round 2 agent logic without disrupting other agents.

### To Run Locally
If you want to run the standalone testing suite for this agent's contract:
```bash
pytest tests/integration/test_agent_contracts.py -k pack
```
