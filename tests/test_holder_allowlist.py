"""Copyright holder lines carry names only (independent review re-check, F01): the guard is an allow-list."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bundles  # noqa: E402

REFUSED = [
    # re-check bypasses of the earlier deny-word guard
    "Foo, for research use", "Foo, free for friends of Foo", "Foo (contact foo@x.org for other rights)",
    "Foo for evaluation purposes", "Foo, for personal use",
    "Foo; use by permission", "Foo。 Redistribution restricted", "Foo． Internal copy",
    # the first review's bypasses
    "Foo. Redistribution only to educational bodies.", "Bar, all commercial use needs permission slip",
    # title-case sentences and other punctuation
    "Foo. Not For Commercial Use", "Foo Inc. Redistribution Prohibited", "Acme: see NOTICE", "Acme; Evaluation Copy",
    "Acme / Sale Edition", "x" * 121,
]
ALLOWED = [
    "AlpacaDB, Inc.", "The Foo Authors", "Google LLC", "Jane Q. Public", "Acme Corp. and contributors",
    "The Apache Software Foundation", "Facebook, Inc. and its affiliates", "Ludwig van Beethoven",
    "Jane Doe <jane.doe@example.org>", "José Müller", "O'Neil & Sons",
]


class HolderAllowList(unittest.TestCase):
    def mit(self, *holders):
        return "".join(f"Copyright (c) 2024 {h}\n" for h in holders) + bundles.MIT_BODY

    def test_refused_holders_give_no_code(self):
        for holder in REFUSED:
            with self.subTest(holder=holder):
                self.assertNotIn(bundles.license_id(self.mit(holder)), bundles.ALLOWED)

    def test_second_holder_line_with_terms_is_refused(self):
        self.assertNotIn(bundles.license_id(self.mit("Foo", "Bar -- usage is at Bar's discretion")), bundles.ALLOWED)

    def test_real_holders_still_allowed(self):
        for holder in ALLOWED:
            with self.subTest(holder=holder):
                self.assertEqual(bundles.license_id(self.mit(holder)), "MIT")
        self.assertEqual(bundles.license_id(self.mit("Foo", "The Bar Authors")), "MIT")

    def test_bsd3_clause_holder_checked_in_original_case(self):
        third = ("3. Neither the name of {} nor the names of its contributors may be used to endorse or promote "
                 "products derived from this software without specific prior written permission.\n\n")
        for holder, ok in (("the copyright holder", True), ("Acme Corp.", True),
                           ("Acme, for research use", False), ("Acme. Evaluation Copy", False)):
            text = ("Copyright (c) 2024 Acme Corp.\n\n" + bundles.BSD_GRANT + "\n\n" + third.format(holder)
                    + bundles.BSD_DISCLAIMER)
            with self.subTest(holder=holder):
                result = bundles.license_id(text)
                if ok:
                    self.assertIn(result, ("BSD-3-Clause",), result)
                else:
                    self.assertNotIn(result, bundles.ALLOWED)


if __name__ == "__main__":
    unittest.main()
