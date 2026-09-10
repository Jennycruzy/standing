import unittest

from standing.provenance import ObservationProvenance, ProvenanceError, SourceBinding


class ProvenanceTests(unittest.TestCase):
    def test_observation_provenance_round_trips(self) -> None:
        provenance = ObservationProvenance.from_mapping(
            {
                "operator_id": "operator:one",
                "source_id": "source:one",
                "extractor_id": "extractor:one",
                "operator_type": "organization",
            }
        )

        self.assertEqual(
            provenance.as_dict(),
            {
                "operator_id": "operator:one",
                "source_id": "source:one",
                "extractor_id": "extractor:one",
                "operator_type": "organization",
            },
        )

    def test_source_binding_rejects_lookalike_domains(self) -> None:
        binding = SourceBinding.from_mapping(
            {
                "allowed_hosts": ["example.com"],
                "canonical_url": "https://example.com/source",
            }
        )

        self.assertFalse(binding.allows("https://api.example.com/source"))
        self.assertTrue(binding.allows("https://example.com/source"))
        self.assertFalse(binding.allows("https://example.com.evil/source"))
        self.assertFalse(binding.allows("https://example.com/other", require_canonical=True))

    def test_source_binding_requires_an_allowed_host(self) -> None:
        with self.assertRaises(ProvenanceError):
            SourceBinding.from_mapping({"allowed_hosts": []})

    def test_source_binding_can_pin_the_accepted_source_type(self) -> None:
        binding = SourceBinding.from_mapping(
            {
                "allowed_hosts": ["vendor.example"],
                "canonical_url": "https://vendor.example/retention",
                "source_type": "vendor_primary",
            }
        )

        self.assertEqual(binding.source_type, "vendor_primary")


if __name__ == "__main__":
    unittest.main()
