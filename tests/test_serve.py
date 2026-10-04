"""Test hosted startup options without opening ports or touching checkpoints."""

import os
import unittest
from unittest.mock import patch

from src.api.serve import main, server_port


class ServeTests(unittest.TestCase):
    def test_default_port(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server_port(), 8000)

    def test_hosted_startup(self):
        with patch.dict(os.environ, {"PORT": "10000", "WEB_CONCURRENCY": "4"}):
            with patch("src.api.serve.uvicorn.run") as run:
                main()
                run.assert_called_once_with(
                    "src.api.main:app", host="0.0.0.0", port=10000,
                    workers=1, reload=False, access_log=False,
                )

    def test_invalid_ports_do_not_start_server(self):
        for port in ("", "abc", "8000.5", "0", "-1", "65536"):
            with self.subTest(port=port), patch.dict(os.environ, {"PORT": port}):
                with patch("src.api.serve.uvicorn.run") as run:
                    with self.assertRaisesRegex(ValueError, "PORT must"):
                        main()
                    run.assert_not_called()
