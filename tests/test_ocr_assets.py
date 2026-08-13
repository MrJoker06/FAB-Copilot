from __future__ import annotations

import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import generate_ocr_gold_assets as generator


def hashes(root: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in generator.NAMES
    }


class OCRAssetsTests(unittest.TestCase):
    def test_generator_is_reproducible(self):
        if not generator.FONT.is_file():
            self.skipTest(f"fixed generator font unavailable: {generator.FONT}")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "samples"
            with patch.object(generator, "ROOT", root):
                generator.main()
                first = hashes(root)
                generator.main()
                second = hashes(root)
        self.assertEqual(set(first), generator.NAMES)
        self.assertEqual(first, second)

    def test_readme_hashes_match_assets(self):
        readme = (generator.ROOT / "README.md").read_text(encoding="utf-8")
        rows = re.findall(r"\| ([^|]+) \| ([0-9a-f]{64}) \|", readme)
        documented = {name.strip(): digest for name, digest in rows}
        self.assertEqual(set(documented), generator.NAMES)
        self.assertEqual(documented, hashes(generator.ROOT))
