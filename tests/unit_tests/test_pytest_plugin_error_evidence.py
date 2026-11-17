# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Compliance evidence must record every test pytest reports, with the outcome pytest reports.

Regression tests: errored tests once vanished from report.json, a teardown error was
recorded as ``passed`` (and, after a skip or an expected failure, not at all),
strict-xfail XPASS was recorded as ``xfailed``, a directly applied
custom marker raised ``KeyError`` and dropped the entry, and a non-JSON metadata value
truncated the whole evidence file at session end.
"""

import json
from typing import Any

import pytest
import yaml

from cats.report_run import ResultCounts
from tests.utils import make_config


@pytest.fixture
def cats_config_content() -> str:
    """Minimal cats.yaml config as string."""
    return yaml.dump(make_config(accounts={"testaccount": "234567890123"}))


def write_project(pytester: pytest.Pytester, cats_config_content: str, test_source: str) -> None:
    """Write cats.yaml, a conftest pointing CATS_CONFIG at it, and the test file."""
    config_path = pytester.path / "cats.yaml"
    config_path.write_text(cats_config_content)
    pytester.makeconftest(f'''
import os
os.environ["CATS_CONFIG"] = "{config_path}"
''')
    pytester.makepyfile(test_source)


def read_report(pytester: pytest.Pytester) -> list[dict[str, Any]]:
    """The recorded entries without ``duration_s`` and ``recorded_at``.

    Those two vary run to run, so they are asserted on their own in
    test_pytest_plugin_report_files.py and stripped here to keep exact-entry assertions.
    """
    entries: list[dict[str, Any]] = json.loads((pytester.path / "report.json").read_text())["tests"]
    for entry in entries:
        del entry["duration_s"]
        del entry["recorded_at"]
    return entries


def test_setup_error_is_recorded_as_error(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A fixture error must appear in the evidence, not vanish."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def broken_fixture():
    raise RuntimeError("fixture exploded")

def test_needs_broken_fixture(broken_fixture):
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(errors=1)
    expected: list[dict[str, Any]] = [
        {
            "result": "error",
            "accounts_in_test": [],
            "test_name": "test_needs_broken_fixture",
            "nodeid": "test_setup_error_is_recorded_as_error.py::test_needs_broken_fixture",
            "test_docstring": None,
            "standards": [],
            "standard_metadata": {},
            "custom_markers": {},
            "additional_metadata": {},
            "xfail": False,
            "error_message": "RuntimeError: fixture exploded",
            "reason": None,
        }
    ]
    assert expected == read_report(pytester)


def test_teardown_error_upgrades_passed_entry_to_error(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest reports this test as ERROR; the evidence must not say passed."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def broken_teardown():
    yield "value"
    raise RuntimeError("teardown exploded")

def test_passes_then_teardown_errors(broken_teardown):
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(passed=1, errors=1)
    expected: list[dict[str, Any]] = [
        {
            "result": "error",
            "accounts_in_test": [],
            "test_name": "test_passes_then_teardown_errors",
            "nodeid": "test_teardown_error_upgrades_passed_entry_to_error.py::test_passes_then_teardown_errors",
            "test_docstring": None,
            "standards": [],
            "standard_metadata": {},
            "custom_markers": {},
            "additional_metadata": {},
            "xfail": False,
            "error_message": "RuntimeError: teardown exploded",
            "reason": None,
        }
    ]
    assert expected == read_report(pytester)


def read_counts(pytester: pytest.Pytester) -> ResultCounts:
    """The ``run.counts`` block of report.json."""
    counts: ResultCounts = json.loads((pytester.path / "report.json").read_text())["run"]["counts"]
    return counts


# A call-phase skip, then a fixture teardown that raises: pytest reports ``1 skipped, 1 error``.
SKIP_THEN_TEARDOWN_ERRORS = """
import pytest

@pytest.fixture
def broken_teardown():
    yield "value"
    raise RuntimeError("teardown exploded")

def test_skips_then_teardown_errors(broken_teardown):
    pytest.skip("not today")
"""


def test_teardown_error_after_call_skip_upgrades_entry_to_error(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest reports ``1 skipped, 1 error`` and exits 1; a ``skipped`` entry would hide the
    failed cleanup from every reader of report.json. The skip reason is kept."""
    # arrange
    write_project(pytester, cats_config_content, SKIP_THEN_TEARDOWN_ERRORS)

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(skipped=1, errors=1)
    expected: list[dict[str, Any]] = [
        {
            "result": "error",
            "accounts_in_test": [],
            "test_name": "test_skips_then_teardown_errors",
            "nodeid": "test_teardown_error_after_call_skip_upgrades_entry_to_error.py::test_skips_then_teardown_errors",
            "test_docstring": None,
            "standards": [],
            "standard_metadata": {},
            "custom_markers": {},
            "additional_metadata": {},
            "xfail": False,
            "error_message": "RuntimeError: teardown exploded",
            "reason": "not today",
        }
    ]
    assert expected == read_report(pytester)


def test_teardown_error_after_call_skip_is_counted_as_error(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """``counts.error`` must count the teardown error, as pytest's summary does."""
    # arrange
    write_project(pytester, cats_config_content, SKIP_THEN_TEARDOWN_ERRORS)

    # act
    pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    expected: ResultCounts = {"total": 1, "passed": 0, "failed": 0, "error": 1, "skipped": 0, "xfailed": 0, "xpassed": 0, "not_run": 0}
    assert expected == read_counts(pytester)


def test_teardown_error_after_marker_skip_upgrades_entry_to_error(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """The entry of a marker-skipped test was recorded in the setup phase. A module-scoped
    fixture (the shape of an account fixture) tears down after the last test that used it,
    which may be that skipped test; its error must land on the entry all the same."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture(scope="module")
def module_broken_teardown():
    yield "value"
    raise RuntimeError("module teardown exploded")

def test_first(module_broken_teardown):
    assert True

@pytest.mark.skip(reason="account not deployed")
def test_last_is_skipped(module_broken_teardown):
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(passed=1, skipped=1, errors=1)
    entries = read_report(pytester)
    expected = [
        ("test_first", "passed", None, None),
        ("test_last_is_skipped", "error", "RuntimeError: module teardown exploded", "account not deployed"),
    ]
    assert expected == [(entry["test_name"], entry["result"], entry["error_message"], entry["reason"]) for entry in entries]


def test_teardown_error_after_imperative_xfail_upgrades_entry_to_error(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest reports ``1 xfailed, 1 error`` and exits 1; the entry must say so."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def broken_teardown():
    yield "value"
    raise RuntimeError("teardown exploded")

def test_xfails_then_teardown_errors(broken_teardown):
    pytest.xfail("known broken")
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(xfailed=1, errors=1)
    expected: list[dict[str, Any]] = [
        {
            "result": "error",
            "accounts_in_test": [],
            "test_name": "test_xfails_then_teardown_errors",
            "nodeid": "test_teardown_error_after_imperative_xfail_upgrades_entry_to_error.py::test_xfails_then_teardown_errors",
            "test_docstring": None,
            "standards": [],
            "standard_metadata": {},
            "custom_markers": {},
            "additional_metadata": {},
            "xfail": True,
            "error_message": "RuntimeError: teardown exploded",
            "reason": "known broken",
        }
    ]
    assert expected == read_report(pytester)


def test_teardown_error_not_matching_xfail_raises_upgrades_xfailed_entry_to_error(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """Under an xfail marker pytest excuses a raising teardown only when ``raises=`` matches it;
    here it does not, so pytest reports ``1 xfailed, 1 error`` and the entry must be an error."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def broken_teardown():
    yield "value"
    raise RuntimeError("teardown exploded")

@pytest.mark.xfail(raises=ValueError, reason="known broken")
def test_fails_as_expected_then_teardown_errors(broken_teardown):
    raise ValueError("expected")
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(xfailed=1, errors=1)
    entries = read_report(pytester)
    expected = ("error", "RuntimeError: teardown exploded", "known broken", True)
    assert expected == (entries[0]["result"], entries[0]["error_message"], entries[0]["reason"], entries[0]["xfail"])


def test_teardown_error_not_matching_xfail_raises_upgrades_xpassed_entry_to_error(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """An unexpected pass is passing evidence; like ``passed``, it must not stand with a broken teardown behind it."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def broken_teardown():
    yield "value"
    raise RuntimeError("teardown exploded")

@pytest.mark.xfail(raises=ValueError)
def test_passes_unexpectedly_then_teardown_errors(broken_teardown):
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(xpassed=1, errors=1)
    entries = read_report(pytester)
    expected = ("error", "RuntimeError: teardown exploded")
    assert expected == (entries[0]["result"], entries[0]["error_message"])


def test_teardown_error_under_xfail_marker_is_recorded_as_xfailed(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """Without ``raises=``, pytest itself reports a raising teardown under an xfail marker as
    a second XFAIL, not as an error, and exits 0. CATS records the outcome pytest reports."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def broken_teardown():
    yield "value"
    raise RuntimeError("teardown exploded")

@pytest.mark.xfail(reason="known broken")
def test_fails_as_expected_then_teardown_raises(broken_teardown):
    raise ValueError("expected")
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(xfailed=2)
    entries = read_report(pytester)
    expected = (1, "xfailed", None, "known broken")
    assert expected == (len(entries), entries[0]["result"], entries[0]["error_message"], entries[0]["reason"])


def test_teardown_error_under_xfail_marker_after_unexpected_pass_is_recorded_as_xpassed(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """The same excuse after an unexpected pass: pytest reports ``1 xpassed, 1 xfailed``, no error,
    exit 0. The entry stays ``xpassed``, as pytest reports it; the teardown error is in pytest's output alone."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def broken_teardown():
    yield "value"
    raise RuntimeError("teardown exploded")

@pytest.mark.xfail(reason="known broken")
def test_passes_unexpectedly_then_teardown_raises(broken_teardown):
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(xpassed=1, xfailed=1)
    entries = read_report(pytester)
    expected = (1, "xpassed", None)
    assert expected == (len(entries), entries[0]["result"], entries[0]["error_message"])


def test_teardown_error_after_failed_call_keeps_the_failure(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest reports ``1 failed, 1 error``; the control's own failure is the stronger evidence and keeps its message."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def broken_teardown():
    yield "value"
    raise RuntimeError("teardown exploded")

def test_fails_then_teardown_errors(broken_teardown):
    assert False
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(failed=1, errors=1)
    entries = read_report(pytester)
    expected = ("failed", "assert False")
    assert expected == (entries[0]["result"], entries[0]["error_message"])


def test_strict_xfail_xpass_is_recorded_as_failed(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest fails a strict-xfail test that passes; recording it xfailed misstates the evidence."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.xfail(strict=True, reason="expected to fail")
def test_strict_xpass():
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(failed=1)
    expected: list[dict[str, Any]] = [
        {
            "result": "failed",
            "accounts_in_test": [],
            "test_name": "test_strict_xpass",
            "nodeid": "test_strict_xfail_xpass_is_recorded_as_failed.py::test_strict_xpass",
            "test_docstring": None,
            "standards": [],
            "standard_metadata": {},
            "custom_markers": {},
            "additional_metadata": {},
            "xfail": True,
            "error_message": "[XPASS(strict)] expected to fail",
            "reason": None,
        }
    ]
    assert expected == read_report(pytester)


def test_xfail_raises_mismatch_is_recorded_as_failed(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A different exception than xfail(raises=...) declares is a failure in pytest's summary."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.xfail(raises=ValueError)
def test_wrong_exception():
    raise RuntimeError("not a ValueError")
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(failed=1)
    entries = read_report(pytester)
    expected = ("failed", "RuntimeError: not a ValueError")
    assert expected == (entries[0]["result"], entries[0]["error_message"])


def test_imperative_xfail_is_recorded_as_xfailed(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest.xfail() carries wasxfail but no marker; it must still record as xfailed."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

def test_imperative_xfail():
    pytest.xfail("known broken")
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(xfailed=1)
    entries = read_report(pytester)
    expected = ("xfailed", True)
    assert expected == (entries[0]["result"], entries[0]["xfail"])


def test_directly_applied_custom_marker_is_recorded(pytester: pytest.Pytester) -> None:
    """@pytest.mark.team("payments") once raised KeyError('kwarg') and dropped the entry."""
    # arrange
    config = make_config(accounts={"testaccount": "234567890123"})
    config["reporting"] = {"custom_markers": ["team"]}
    write_project(
        pytester,
        yaml.dump(config),
        """
import pytest

@pytest.mark.team("payments")
def test_with_direct_marker():
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(passed=1)
    entries = read_report(pytester)
    expected = ("passed", {"team": ["payments"]})
    assert expected == (entries[0]["result"], entries[0]["custom_markers"])


def test_custom_marker_with_multiple_positional_values_records_each(pytester: pytest.Pytester) -> None:
    """@pytest.mark.team("a", "b") records every positional value, in order."""
    # arrange
    config = make_config(accounts={"testaccount": "234567890123"})
    config["reporting"] = {"custom_markers": ["team"]}
    write_project(
        pytester,
        yaml.dump(config),
        """
import pytest

@pytest.mark.team("payments", "identity")
def test_with_two_values():
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(passed=1)
    entries = read_report(pytester)
    expected = {"team": ["payments", "identity"]}
    assert expected == entries[0]["custom_markers"]


def test_unserializable_additional_metadata_fails_the_test_loudly(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A datetime in metadata once truncated report.json at session end. It must instead
    fail the offending test with the culprit named, leaving the evidence file whole."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import datetime

def test_bad_metadata(cats_report):
    cats_report.add_report_metadata({"when": datetime.datetime(2026, 1, 1)})
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*additional_metadata value for key 'when' is not JSON-serializable (type datetime)*"])
    entries = read_report(pytester)
    expected = ("failed", 1)
    assert expected == (entries[0]["result"], len(entries))


def test_class_level_cats_marker_records_standards(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """@cats on a test class once yielded standards: [] (own_markers misses class markers)."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
from cats import cats

@cats(standard_name="SOC2-CC6.6")
class TestGroup:
    def test_in_class(self):
        assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(passed=1)
    entries = read_report(pytester)
    expected = ["SOC2-CC6.6"]
    assert entries[0]["standards"] == expected


def test_foreign_standard_marker_is_not_cats_evidence(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """CATS reads `cats_standard` only: a user's or another plugin's `standard` marker is not a standard attestation."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.standard(name="SOC2-CC6.6")
def test_with_foreign_marker():
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(passed=1)
    entries = read_report(pytester)
    expected: list[str] = []
    assert entries[0]["standards"] == expected


def test_skip_reason_is_recorded(pytester: pytest.Pytester, cats_config_content: str) -> None:
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.skip(reason="account not deployed")
def test_skipped():
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(skipped=1)
    entries = read_report(pytester)
    expected = ("skipped", "account not deployed")
    assert expected == (entries[0]["result"], entries[0]["reason"])


def test_xfail_reason_is_recorded(pytester: pytest.Pytester, cats_config_content: str) -> None:
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.xfail(reason="known broken")
def test_expected_failure():
    assert False
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(xfailed=1)
    entries = read_report(pytester)
    expected = ("xfailed", "known broken")
    assert expected == (entries[0]["result"], entries[0]["reason"])


def test_xfail_with_setup_error_is_recorded_as_xfailed(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest reports an xfail test whose fixture errors as XFAIL; the evidence must not say skipped."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def broken_fixture():
    raise RuntimeError("fixture exploded")

@pytest.mark.xfail(reason="known gap")
def test_known_gap(broken_fixture):
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(xfailed=1)
    expected: list[dict[str, Any]] = [
        {
            "result": "xfailed",
            "accounts_in_test": [],
            "test_name": "test_known_gap",
            "nodeid": "test_xfail_with_setup_error_is_recorded_as_xfailed.py::test_known_gap",
            "test_docstring": None,
            "standards": [],
            "standard_metadata": {},
            "custom_markers": {},
            "additional_metadata": {},
            "xfail": True,
            "error_message": None,
            "reason": "known gap",
        }
    ]
    assert expected == read_report(pytester)


def test_xfail_run_false_is_recorded_as_xfailed(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest reports xfail(run=False) as XFAIL with a [NOTRUN] reason; the evidence must not say skipped."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.xfail(run=False, reason="known gap")
def test_known_gap():
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(xfailed=1)
    expected: list[dict[str, Any]] = [
        {
            "result": "xfailed",
            "accounts_in_test": [],
            "test_name": "test_known_gap",
            "nodeid": "test_xfail_run_false_is_recorded_as_xfailed.py::test_known_gap",
            "test_docstring": None,
            "standards": [],
            "standard_metadata": {},
            "custom_markers": {},
            "additional_metadata": {},
            "xfail": True,
            "error_message": None,
            "reason": "[NOTRUN] known gap",
        }
    ]
    assert expected == read_report(pytester)


def test_stacked_duplicate_standard_records_once(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """Stacking the same standard_name twice once duplicated report entries and props."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
from cats import cats

@cats(standard_name="SOC2-CC6.6", control_ids=["AC-3"])
@cats(standard_name="SOC2-CC6.6", control_ids=["SC-7"])
def test_stacked():
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(passed=1)
    entries = read_report(pytester)
    expected = ["SOC2-CC6.6"]
    assert entries[0]["standards"] == expected


def test_report_dir_is_created_when_missing(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """--cats-report-dir pointing at a missing nested directory once raised FileNotFoundError."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_ok():
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly", "--cats-report-dir", "out/nested")

    # assert
    result.assert_outcomes(passed=1)
    entries = json.loads((pytester.path / "out" / "nested" / "report.json").read_text())["tests"]
    assert entries[0]["result"] == "passed"


def test_setup_phase_skip_still_records_the_requested_account(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A skipped test never built its fixtures; the account comes from the fixture name and cats.yaml."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.skip(reason="account not deployed")
def test_skipped(testaccount_account):
    assert True
""",
    )

    # act
    result = pytester.runpytest_subprocess("-p", "no:randomly")

    # assert
    result.assert_outcomes(skipped=1)
    entries = read_report(pytester)
    expected = [{"account_name": "testaccount", "account_id": "234567890123", "tags": {}}]
    assert expected == entries[0]["accounts_in_test"]
