import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "structured_evidence_pilot.py"
SPEC = importlib.util.spec_from_file_location("structured_evidence_pilot", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class CrmMarkdownRecordsTest(unittest.TestCase):
    def test_reads_only_identity_seed_columns(self):
        table = (
            "| 序号 | 产品匹配 | 商业匹配 | 最终跟进 | 公司名 | 网址 | 国家 |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 1 | **9** | **8** | **跟进** | Example Co. | [site](https://example.com/) | China |\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crm.md"
            path.write_text(table, encoding="utf-8")
            self.assertEqual(
                MODULE._crm_markdown_records(path),
                {1: {"id": "crm-001", "name": "Example Co.", "country": "China", "website": "https://example.com/"}},
            )


if __name__ == "__main__":
    unittest.main()
