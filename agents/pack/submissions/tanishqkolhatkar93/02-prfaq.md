# PR / FAQ: Pack Manager AI

**Q: What happens if the AI servers go down or the warehouse loses internet?**
*A:** We engineered a strict "Fail-Open" architecture. If the API times out, the operator dashboard will display a "PENDING" status rather than crashing. The operator can then manually verify the box and seal it, ensuring the assembly line never stops.

**Q: Can a 3PL worker see the packages of a different client brand?**
*A:** No. We utilize strict Row-Level Security (RLS) via Tenant Isolation. Every API request is tagged with an `org_id`, and operators can only write and read evidence contracts belonging to their authenticated organization.

ŠªQ: What if the AI can't see the items clearly because they are stacked or blurry?**
*A:** The AI is strictly prompted never to guess. If the visual evidence is ambiguous, it will output a unique "UNCERTAIN" verdict, requiring human review. It is not treated as a low-confidence PASS.

**Q: How do we handle customer disputes ("I only got 1 shirt, not 2!")?**
*A:** Every verification generates a tamper-proof Evidence Contract in the `contract/` directory. This JSON includes the operator ID, the exact checks performed, and a cryptographic SHA-256 hash of the captured image, giving you absolute proof of what was in the box when it was sealed.

**Q: What are the known limitations?**
*A:** The system struggles with identical soft-goods (like t-shirts) that are perfectly folded on top of one another, as the camera cannot see the bottom layer. It also cannot inspect sub-items enclosed in opaque secondary packaging.