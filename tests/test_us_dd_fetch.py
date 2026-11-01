import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import split_by_region
import us_dd_fetch


class OhioZipTests(unittest.TestCase):
    def test_zip_formats(self):
        for value, expected in [(7040, "07040"), ("7040", "07040"), ("07040", "07040"),
                                (43215, "43215"), (None, ""), ("07040-1234", "07040-1234")]:
            with self.subTest(value=value):
                self.assertEqual(us_dd_fetch.ohio_zip(value), expected)

    def test_numeric_zip_preserves_state_routing(self):
        row = {"sitedescription": "Agency", "sitekey": 95921, "servicename": "Respite",
               "latitude": 40.73, "longitude": -74.27, "addressline1": "515 Valley St",
               "city": "Maplewood", "state": "NJ", "zipcode": 7040, "providername": "Provider"}
        with patch.object(us_dd_fetch, "oh_rows", return_value=[row]):
            entry = us_dd_fetch.ohio()[0]
        self.assertEqual(entry["address"], "515 Valley St, Maplewood, NJ 07040")
        self.assertEqual(split_by_region.us_state(entry), "NJ")


if __name__ == "__main__":
    unittest.main()
