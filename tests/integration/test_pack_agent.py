import pytest
from agents.pack.app import handle
from shared.utils.records import pending_output

def test_pack_tenant_rejection():
    request = {
        "subject": {"org_id": "unknown_org", "subject_id": "UNIT-0006"}
    }
    with pytest.raises(LookupError, match="Unknown organization unknown_org"):
        handle(request)