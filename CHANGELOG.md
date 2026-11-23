# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-11-27

CATS now supports pytest subtests: every `subtests.test()` block is its own piece of evidence.
Requires pytest 9.1.1 or later.

### Added

- pytest `subtests` support. Each `subtests.test()` block is its own entry in `report.json`,
  Security Hub finding and OSCAL observation, identified by the test and the block's `msg`; the
  test's own entry is `failed` when any block failed, as pytest reports it. Give each block a
  unique `msg`: the description is the block's identity, and a duplicate fails the test. Entries
  gain a `subtest` key (`null` outside a block).
  [Writing tests: subtests](https://aws.github.io/cats/guides/writing-tests.html#subtests-one-check-per-discovered-resource),
  [Reports: subtests](https://aws.github.io/cats/api-reference/Reports.html#subtests).

### Changed

- pytest 9.1.1 or later is required (was 9.0.3).
- `receive_s3` raises `CatsUsageError` for a datagram sent without the receipt token, instead
  of returning `False` as if the network had dropped it. `cats run udp-call` and the
  `cats_udp_call` MCP tool report the same condition as `receipt_token_carried`.
- The project moved from `github.com/awslabs/cats` to `github.com/aws/cats`; documentation is at
  `aws.github.io/cats`. Security Hub `Id`s and OSCAL UUIDs are unchanged.

### Fixed

- `cats infra deploy` checks that `parent_account_id` is the caller's account before it touches
  CloudFormation.
- `cats infra destroy` deletes only stacks that `cats infra deploy` created for the same account
  keyname.
- Every boto client CATS builds retries adaptively, up to ten retries, so throttling in a parallel
  run is retried instead of failing the test.
- An `xfail` test whose setup fails, or marked `@pytest.mark.xfail(run=False)`, is recorded as
  `xfailed` (was `skipped`).
- A teardown error after a skipped or xfailed test is recorded as `error` (was dropped).
- A test whose evidence could not be built has a `failed` entry naming the cause (was absent).
- A test pytest-rerunfailures ran again is recorded once, for its last attempt.

## [1.0.0] - 2026-10-31

First public release of CATS.
