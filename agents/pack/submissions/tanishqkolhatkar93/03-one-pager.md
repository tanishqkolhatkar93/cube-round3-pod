# Pack Manager AI: One Pager

## Target Metrics

| Metric | Target | Minimum Viable Threshold |
| :--- | :--- | :--- |
| **False Positive Rate** (Sealing a bad box) | 0.0% | < 0.5% |
| **False Negative Rate** (Stopping a good box) | < 2.0% | < 5.0% |
| **Uncertain Rate** (Human review required) | < 10.0% | < 15.0% |
| **Latency per Package** | < 1.5 seconds | < 3.0 seconds |
| **Network Fail-Open Rate** | 100% | 100% (Mandatory) |
| **Pending Rate** (Fail-open fallback triggered) | < 1.0% | < 2.0% |

## Kill Condition
**Kill the project if:** The False Positive Rate (where the AI tells the operator to SEAL a box that is actually missing items) exceeds 1.0% staging. A False Negative (wasting 10 seconds of human review) is acceptable; shipping an incorrect order to a customer is not. Additionally, if the Uncertain Rate exceeds 15%, the product is unusable and must be killed.

## Key Design Decisions
- **Occlusion Handling:** We accept single-shot captures and will report occlusion-caused failures as a separate category from recognition failures.
- **Decoys:** We always include the seller's other SKUs (decoys) as candidates in production, so the model must discriminate rather than just confirm.