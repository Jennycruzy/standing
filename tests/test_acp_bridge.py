import unittest
import tempfile
from pathlib import Path

from scripts.acp_bridge import (
    AcpBridgeError,
    _parse_response,
    _validate_result,
    adapter_environment,
    load_environment_file,
)


class AcpBridgeTests(unittest.TestCase):
    def test_maps_existing_buyer_credentials_without_putting_them_in_json(self) -> None:
        environment = {
            "BUYER_AGENT_WALLET_ADDRESS": "0x1111111111111111111111111111111111111111",
            "BUYER_WALLET_ID": "wallet-id",
            "BUYER_SIGNER_PRIVATE_KEY": "secret-is-environment-only",
        }
        mapped = adapter_environment(environment)
        self.assertEqual(mapped["STANDING_ACP_WALLET_ID"], "wallet-id")
        self.assertEqual(mapped["STANDING_ACP_SIGNER_PRIVATE_KEY"], "secret-is-environment-only")

    def test_success_result_is_typed(self) -> None:
        response = _parse_response('{"ok":true,"result":{"jobId":"76580","status":"completed","entries":[]}}\n')
        _validate_result(response["result"])

    def test_reads_dotenv_without_printing_or_requiring_a_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# ignored\nexport BUYER_WALLET_ID=wallet-id\nBUYER_SIGNER_PRIVATE_KEY='secret'\nINVALID LINE\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_environment_file(path),
                {"BUYER_WALLET_ID": "wallet-id", "BUYER_SIGNER_PRIVATE_KEY": "secret"},
            )

    def test_failure_is_not_accepted_as_success(self) -> None:
        with self.assertRaises(AcpBridgeError):
            response = _parse_response('{"ok":false,"error":{"name":"AcpJobError","message":"rejected"}}\n')
            if response.get("ok") is not True:
                raise AcpBridgeError(response["error"]["message"])


if __name__ == "__main__":
    unittest.main()
