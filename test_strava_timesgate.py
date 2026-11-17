import contextlib
import io
import unittest
from unittest.mock import patch

import strava_timesgate as app


class DeviceResponseTests(unittest.TestCase):
    @patch.object(app.requests, "post")
    def test_success_codes(self, post):
        for result in (
            {"error_code": 0},
            {"ReturnCode": 0},
            {"error_code": 0, "ReturnCode": 0},
        ):
            with self.subTest(result=result):
                post.return_value.json.return_value = result
                self.assertEqual(app.push_to_times_gate({}, app.DEFAULTS), result)

    @patch.object(app.requests, "post")
    def test_firmware_timeout(self, post):
        post.return_value.json.return_value = {
            "ReturnCode": 1,
            "ReturnMessage": "command timeout",
        }
        with self.assertRaisesRegex(TimeoutError, "completion was not confirmed"):
            app.push_to_times_gate({}, app.DEFAULTS)
        post.assert_called_once()

    @patch.object(app.requests, "post")
    def test_other_errors_remain_failures(self, post):
        for result in (
            {},
            {"ReturnCode": 1, "ReturnMessage": "invalid token"},
            {"error_code": 0, "ReturnCode": 2},
            {"error_code": 2, "ReturnCode": 0},
            {
                "error_code": 2,
                "ReturnCode": 1,
                "ReturnMessage": "command timeout",
            },
        ):
            with self.subTest(result=result):
                post.return_value.json.return_value = result
                with self.assertRaises(RuntimeError):
                    app.push_to_times_gate({}, app.DEFAULTS)

    def test_main_warns_without_claiming_success_or_retrying(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("sys.argv", ["strava_timesgate.py", "--demo"]),
            patch.object(app, "load_config", return_value=dict(app.DEFAULTS)),
            patch.object(app, "render"),
            patch.object(app, "build_payload", return_value={}),
            patch.object(
                app, "push_to_times_gate", side_effect=TimeoutError("not confirmed")
            ) as push,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            app.main()
        self.assertIn("Warning: not confirmed", stderr.getvalue())
        self.assertNotIn("Sent to Times Gate", stdout.getvalue())
        push.assert_called_once()


if __name__ == "__main__":
    unittest.main()
