"""Preserve the author's tenant-rejection intent at the real configured boundary."""
import copy
import pytest
from agents.pack.app import handle
from agents.pack.tests.test_adapter import h
from agents.prep.common import Rejected


def test_pack_tenant_rejection(h):
    request=copy.deepcopy(h.request)
    request['subject']['org_id']='unknown_org'
    with pytest.raises(Rejected,match='source_not_found') as error:
        handle(request)
    assert isinstance(error.value,LookupError) and error.value.status==404
    assert h.calls==0


def test_pack_malformed_tenant_request_rejected_before_lookup():
    request={'subject':{'org_id':'unknown_org','subject_id':'UNIT-0006'}}
    with pytest.raises(Rejected,match='invalid_request') as error:
        handle(request)
    assert error.value.status==422
