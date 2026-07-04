import subprocess
import sys
import unittest


class ImportPathTest(unittest.TestCase):
    def test_context_types_import_from_repository_root(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from voice_concierge.context.types import ContextState; "
                    "print(ContextState().mode)"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "home")


if __name__ == "__main__":
    unittest.main()
