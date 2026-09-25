import importlib.machinery
import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "fsa.pyw"
LOADER = importlib.machinery.SourceFileLoader("fsa_app", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
fsa = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = fsa
LOADER.exec_module(fsa)


class ArshinV4Tests(unittest.TestCase):
    def make_api(self, payloads):
        api = fsa.RestAPI("00000000-0000-0000-0000-000000000000")
        api.get_verification = lambda verification_id: json.dumps(payloads[verification_id])
        return api

    def test_modified_record_resolves_to_next_version_and_party_mi(self):
        payloads = {
            "old-version": {
                "result": {
                    "publication": {
                        "status": "Запись была модифицирована",
                        "vriVerIdNext": "new-version",
                    }
                }
            },
            "new-version": {
                "result": {
                    "partyMI": {
                        "mitypeNumber": "93332-24",
                        "mitypeType": "МЕГЕОН",
                        "modification": "МЕГЕОН",
                    },
                    "vriInfo": {
                        "vrfDate": "19.08.2026",
                        "validDate": "18.08.2028",
                        "applicable": {"certNum": "С-TEST/1"},
                    },
                }
            },
        }

        record = self.make_api(payloads).process_verification("old-version")

        self.assertIsNotNone(record)
        self.assertEqual("new-version", record.number_verification)
        self.assertEqual("МЕГЕОН", record.type_measuring_instrument)
        self.assertEqual("2026-08-19", record.date_verification)
        self.assertEqual("2028-08-18", record.date_end_verification)
        self.assertEqual(fsa.CONCLUSION_VALID, record.result_verification)
        self.assertFalse(record.cancelled)

    def test_cancelled_record_is_marked_without_requiring_instrument_payload(self):
        payloads = {
            "cancelled": {
                "result": {
                    "publication": {
                        "status": "Запись аннулирована",
                    }
                }
            }
        }

        record = self.make_api(payloads).process_verification("cancelled")

        self.assertIsNotNone(record)
        self.assertTrue(record.cancelled)

    def test_eta_mi_inside_mi_info_is_supported(self):
        payload = {
            "miInfo": {
                "etaMI": {
                    "mitypeNumber": "49867-12",
                    "mitypeType": "МПЦ",
                }
            }
        }

        instrument = fsa.RestAPI._instrument_info(payload)

        self.assertEqual("49867-12", instrument["mitypeNumber"])
        self.assertEqual("МПЦ", instrument["mitypeType"])

    def test_public_rate_limit_has_safety_margin(self):
        self.assertGreaterEqual(fsa.PUBLIC_REQUEST_INTERVAL_SECONDS, 0.5)


if __name__ == "__main__":
    unittest.main()
