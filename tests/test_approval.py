import unittest

from standing.approval import (
    ManualApprovalError,
    check_manual_approval,
    evidence_fingerprint,
    issue_manual_approval,
)


class ManualApprovalTests(unittest.TestCase):
    def test_evidence_fingerprint_is_stable_when_mapping_and_observation_order_change(self) -> None:
        first = [
            {"observation_uid": "b", "value": 90, "meta": {"source": "vendor"}},
            {"observation_uid": "a", "value": 90, "meta": {"source": "vendor"}},
        ]
        second = [
            {"meta": {"source": "vendor"}, "value": 90, "observation_uid": "a"},
            {"value": 90, "observation_uid": "b", "meta": {"source": "vendor"}},
        ]

        self.assertEqual(
            evidence_fingerprint("vendor.retention", first),
            evidence_fingerprint("vendor.retention", second),
        )

    def test_only_humans_can_create_approval_records(self) -> None:
        with self.assertRaises(ManualApprovalError):
            issue_manual_approval(
                "approval-1",
                "vendor.retention",
                approved_by="agent",
                approver_role="model",
                approved_at=100,
                evidence_digest="a" * 64,
                reason="The model wants to approve.",
            )

    def test_approval_check_binds_condition_and_evidence(self) -> None:
        observations = [{"observation_uid": "one", "value": 90}]
        approval = issue_manual_approval(
            "approval-1",
            "vendor.retention",
            approved_by="alice",
            approver_role="human",
            approved_at=100,
            evidence_digest=evidence_fingerprint("vendor.retention", observations),
            reason="Reviewed the evidence.",
        )

        valid = check_manual_approval(
            approval,
            condition_key="vendor.retention",
            evidence_digest=evidence_fingerprint("vendor.retention", observations),
        )
        wrong_evidence = check_manual_approval(
            approval,
            condition_key="vendor.retention",
            evidence_digest=evidence_fingerprint("vendor.retention", [{"observation_uid": "one", "value": 365}]),
        )
        wrong_condition = check_manual_approval(
            approval,
            condition_key="vendor.regions",
            evidence_digest=approval.evidence_fingerprint,
        )

        self.assertTrue(valid.valid)
        self.assertFalse(wrong_evidence.valid)
        self.assertFalse(wrong_condition.valid)


if __name__ == "__main__":
    unittest.main()
