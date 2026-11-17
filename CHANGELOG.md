# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Tests that use pytest's `subtests` fixture now get a report entry for each `subtests.test()`
  block, plus one for the test, with the results pytest reports. A block's entry has a new
  `subtest` key, which is `null` on other entries; `schema_version` is still 1. Before, every
  block was recorded under the test's own `nodeid`, and the test could read `passed` when a
  block had failed.
- Security Hub findings and OSCAL observations for a block name their test: the
  `cats/subtest_of` product field and the `subtest-of` observation property. Both are additive.

### Changed

- pytest 9.1.1 or later is required (was 9.0.3). 9.1 renders a block's keyword arguments to
  text when the block ends, so the block's `nodeid` (and the Security Hub `Id` and OSCAL uuids
  derived from it) is the same under pytest-xdist as serially, and the same across pytest
  versions from here on; 9.1 also fixed subtests under pytest-xdist.
- If you already use `subtests`, the number of entries is unchanged, and what changes is their
  content: each block's entry now has its own `nodeid` (the test's followed by the block's
  description) and so a new Security Hub `Id` and OSCAL uuid; the test's own entry, which keeps
  the old `nodeid` and identifiers, is `failed` when a block failed, as pytest reports it. A
  failed block was already counted as a failure, under the test's `nodeid`; `run.counts.failed`
  now rises by one more for each test that has a failed block, matching pytest's summary.
- A second `subtests.test()` block with the same description as an earlier one in the same test
  fails, naming the fix: the description is the block's identity in the evidence. A suite that
  passed before can fail on this, most likely a bare `subtests.test()` in a loop or a fixed
  `msg` with the varying part elsewhere; give each block a unique `msg`. A `msg` that is not a
  string fails the block too.
- A CATS reporting error raised while a block is recorded fails that block in pytest's summary,
  in the evidence and in the run's exit status, as a reporting error on a test always has, and
  fails its test as any failed block does (`contains 1 failed subtest`); `-x` and `--maxfail`
  stop on it. A block whose `msg` has no text is described as `[<undescribed subtest>]`, the
  one description CATS supplies rather than copies from pytest; its entry's `msg` is `null`.

### Fixed

- A test whose evidence could not be built (a marker value JSON cannot represent) now has an
  entry in `report.json`: `failed`, with the cause in `error_message` and no markers, accounts
  or metadata. Before, pytest reported the test FAILED and `report.json` had no entry for it.
  When the test had also failed on its own, its own failure comes first in pytest's output and
  in `error_message`, with the reporting error after it as a titled section under the
  traceback, so the JUnit `<failure message>` stays the test's own assertion; before, the
  reporting error replaced it in pytest's output.
- A test with `subtests` whose reports are logged after teardown, as pytest-rerunfailures logs
  them under any `--reruns` value, is recorded with pytest's verdict. Before, the test's entry
  read `passed` while pytest printed FAILED for it.
- A test pytest-rerunfailures runs again has entries for its last attempt only, as pytest's
  summary counts it, and its `junit.xml` testcase carries each `cats:` property once. Before,
  every attempt was recorded, so `report.json` held two entries under one `nodeid` (two
  Security Hub findings with one `Id`), the superseded attempt's test entry could read
  `passed`, and the testcase carried every property once per attempt.
- The project moved from `github.com/awslabs/cats` to `github.com/aws/cats`. Documentation is
  at `aws.github.io/cats`; the config schema `$id` and package metadata point there. Security
  Hub finding `Id`s and OSCAL stable UUIDs are unchanged: their namespaces are opaque seeds,
  not links, and keep the value they had at 1.0.0.

## [1.0.0] - 2026-10-31

First public release of CATS.
