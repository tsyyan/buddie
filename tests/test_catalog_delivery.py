"""Regression tests for catalog version delivery and its workflow safety boundaries."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("catalog_bump", ROOT / "scripts" / "catalog_bump.py")
catalog_bump = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog_bump)


class CatalogDelivery(unittest.TestCase):
    def test_updates_pins_and_versioned_links_without_other_changes(self):
        source = ('{"args":["buddie@2.0.5","serve"],'
                  '"notes":"https://github.com/tsyyan/buddie/blob/v2.0.5/PRIVACY.md",'
                  '"other":"retain me"}')
        updated, found = catalog_bump.bump(source, "2.0.8")
        self.assertEqual(found, ["2.0.5"])
        self.assertIn("buddie@2.0.8", updated)
        self.assertIn("/v2.0.8/PRIVACY.md", updated)
        self.assertIn('"other":"retain me"', updated)

    def test_idempotent_and_downgrade_rejected(self):
        source = 'buddie@2.0.8 and /v2.0.8/PRIVACY.md'
        self.assertEqual(catalog_bump.bump(source, "2.0.8")[0], source)
        with self.assertRaisesRegex(ValueError, "not downgraded"):
            catalog_bump.bump(source, "2.0.7")

    def test_missing_listing_fails_instead_of_creating_one(self):
        with self.assertRaisesRegex(ValueError, "no buddie"):
            catalog_bump.bump('{"id":"another-server"}', "2.0.9")

    def test_check_mode_does_not_change_file(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "entry.json"
            file.write_text('buddie@2.0.5', encoding="utf-8")
            self.assertEqual(catalog_bump.main([str(file), "2.0.8", "--check"]), 1)
            self.assertEqual(file.read_text(encoding="utf-8"), 'buddie@2.0.5')
            self.assertEqual(catalog_bump.main([str(file), "2.0.8"]), 0)
            self.assertEqual(catalog_bump.main([str(file), "2.0.8", "--check"]), 0)

    def test_workflow_regenerates_kilo_and_refuses_unsafe_reuse(self):
        workflow = (ROOT / ".github" / "workflows" / "catalogs.yml").read_text(encoding="utf-8")
        self.assertIn("npx --no-install tsx generate-mcps-marketplace.ts", workflow)
        self.assertIn('catalog_bump.py mcps/marketplace.yaml "$V" --check', workflow)
        self.assertIn("git diff --check", workflow)
        self.assertIn("manual reconciliation required", workflow)
        self.assertNotIn("git push --force", workflow)
        self.assertNotIn("gh pr merge", workflow)


if __name__ == "__main__":
    unittest.main()
