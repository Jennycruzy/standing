import unittest

from standing.provenance import ObservationProvenance, ProvenanceError, SourceBinding


class ProvenanceTests(unittest.TestCase):
    def test_observation_provenance_round_trips(self) -> None:
        provenance = ObservationProvenance.from_mapping(
            {
                "operator_id": "operator:one",
                "source_id": "source:one",
                "extractor_id": "extractor:one",
            }
        )

        self.assertEqual(
            provenance.as_dict(),
            {
                "operator_id": "operator:one",
                "source_id": "source:one",
                "extractor_id": "extractor:one",
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


if __name__ == "__main__":
    unittest.main()
