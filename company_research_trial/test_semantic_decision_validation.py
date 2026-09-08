import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "semantic_decision_validation.py"
SPEC = importlib.util.spec_from_file_location("semantic_decision_validation", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class CrmDatasetTest(unittest.TestCase):
    def test_seven_columns_preserve_link_target_and_balanced_parentheses(self):
        table = "| 1 | 6 | 7 | 跟进 | Development Ceramics | [https://old.test](https://new.test/products_(ceramics)) | France |\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crm.md"
            path.write_text(table)
            records, labels = MODULE.crm_markdown_dataset(path)
        self.assertEqual(records[0]["website"], "https://new.test/products_(ceramics)")
        self.assertEqual(labels[1]["follow_up"], "跟进")

    def test_eight_columns_read_markdown_target_not_display_url(self):
        table = "| 1 | 2 | 3 | 淘汰 | Development Instruments | [https://wrong.test](https://right.test/) | UK | |\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crm.md"
            path.write_text(table)
            records, _ = MODULE.crm_markdown_dataset(path)
        self.assertEqual(records[0]["website"], "https://right.test/")

    def test_reads_eight_column_markdown_as_identity_seeds_and_labels(self):
        table = (
            "| 序号 | 产品匹配 | 商业匹配 | 最终跟进 | 公司名 | 网址 | 国家 | 地址 |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| 1 | **9** | **8** | **跟进** | Example Co. | https://example.com | China | A \\| B |\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crm.md"
            path.write_text(table, encoding="utf-8")
            records, labels = MODULE.crm_markdown_dataset(path)
        self.assertEqual(records, [{"id": "crm-001", "name": "Example Co.", "country": "China", "website": "https://example.com"}])
        self.assertEqual(labels, {1: {"product_match": 9, "commercial_match": 8, "follow_up": "跟进"}})


if __name__ == "__main__":
    unittest.main()
