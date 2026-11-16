import base64
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "configure_repository", ROOT / "scripts/configure_repository.py"
)
configure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configure)
CHECK = {"context": "Repository checks", "integration_id": 15368}


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.stored = {}
        self.conclusion = "success"
        self.admin = True
        self.extra_run = False
        self.missing_dev = False
        self.fail_write = False
        self.codeowner = "owner"
        self.missing_codeowners = False
        self.dev_sha = "abcdef"
        self.dev_codeowner = None
        self.unrelated = {
            "id": 999,
            "name": "unrelated-policy",
            "source_type": "Repository",
            "source": "owner/project",
        }

    def api(self, endpoint, method="GET", payload=None):
        self.calls.append((method, endpoint, copy.deepcopy(payload)))
        if method in ["POST", "PUT"]:
            if self.fail_write:
                raise configure.ConfigurationError("HTTP 403: policy unavailable")
            identifier = (
                int(endpoint.rsplit("/", 1)[1])
                if method == "PUT"
                else len(self.stored) + 1
            )
            self.stored[identifier] = {
                **copy.deepcopy(payload),
                "id": identifier,
                "source_type": "Repository",
                "source": "owner/project",
            }
            return self.stored[identifier]
        if endpoint == "repos/owner/project":
            return {"permissions": {"admin": self.admin}}
        if endpoint == "apps/github-actions":
            return {"slug": "github-actions", "id": 15368}
        if endpoint == "users/owner":
            return {"id": 42, "type": "User"}
        if endpoint.endswith("/permission"):
            return {"permission": "admin"}
        if "/git/ref/heads/" in endpoint:
            if self.missing_dev and endpoint.endswith("/dev"):
                raise configure.ConfigurationError("HTTP 404: create dev first")
            return {
                "object": {
                    "sha": self.dev_sha if endpoint.endswith("/dev") else "abcdef"
                }
            }
        if "/contents/.github/CODEOWNERS?" in endpoint:
            if self.missing_codeowners:
                raise configure.ConfigurationError("HTTP 404: CODEOWNERS missing")
            owner = self.codeowner
            if self.dev_codeowner and endpoint.endswith("ref=dev-commit"):
                owner = self.dev_codeowner
            content = configure.render_codeowners(owner)
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(content.encode()).decode(),
            }
        if "/rulesets/" in endpoint:
            return self.stored[int(endpoint.rsplit("/", 1)[1])]
        raise AssertionError(endpoint)

    def pages(self, endpoint, key=None):
        if endpoint == "repos/owner/project/branches":
            branches = [{"name": "main", "commit": {"sha": "abcdef"}}]
            if not self.missing_dev:
                branches.append({"name": "dev", "commit": {"sha": self.dev_sha}})
            return branches
        if "/actions/runs?" in endpoint:
            return [{"id": 10, "workflow_id": 20, "created_at": "2026-01-01T00:00:00Z"}]
        if "/actions/runs/10/jobs?" in endpoint:
            runs = [
                {
                    "name": "Repository checks",
                    "status": "completed",
                    "conclusion": self.conclusion,
                }
            ]
            if self.extra_run:
                runs.append(copy.deepcopy(runs[0]))
            return runs
        if "/rulesets?" in endpoint:
            return [self.unrelated, *self.stored.values()]
        raise AssertionError(endpoint)

    @property
    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]


class PolicyTests(unittest.TestCase):
    def invoke(self, api, apply=False):
        args = [
            "--repo",
            "owner/project",
            "--merger",
            "owner",
            "--check",
            "Repository checks",
        ]
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return configure.main(args + (["--apply"] if apply else []), api=api)

    def test_init_dev_creates_remote_branch_from_main_only_when_missing(self):
        for missing in [True, False]:
            with self.subTest(missing=missing):
                api = FakeGitHub()
                api.missing_dev = missing
                with contextlib.redirect_stdout(io.StringIO()):
                    result = configure.main(
                        ["--repo", "owner/project", "--init-dev"], api=api
                    )
                self.assertEqual(result, 0)
                expected = [
                    (
                        "POST",
                        "repos/owner/project/git/refs",
                        {"ref": "refs/heads/dev", "sha": "abcdef"},
                    )
                ]
                self.assertEqual(api.writes, expected if missing else [])

    def test_release_app_can_write_branches_and_create_but_not_change_version_tags(
        self,
    ):
        baseline, gate, reviews, creation, protection = configure.build_payloads(
            [CHECK], 42, 123
        )
        actor = {"actor_id": 123, "actor_type": "Integration", "bypass_mode": "always"}
        for policy in [baseline, gate, reviews, creation]:
            self.assertIn(actor, policy["bypass_actors"])
        for policy in [creation, protection]:
            self.assertEqual(policy["target"], "tag")
            self.assertEqual(
                policy["conditions"]["ref_name"]["include"], ["refs/tags/v*"]
            )
        self.assertEqual(creation["rules"], [{"type": "creation"}])
        self.assertEqual(
            protection["rules"], [{"type": "update"}, {"type": "deletion"}]
        )
        self.assertEqual(protection["bypass_actors"], [])
        self.assertEqual(configure.build_payloads([CHECK], 42)[0]["bypass_actors"], [])

    def test_main_and_dev_require_pr_ci_without_bypass(self):
        baseline, _, _ = configure.build_payloads([CHECK], 42)
        self.assertEqual(baseline["enforcement"], "active")
        self.assertEqual(baseline["bypass_actors"], [])
        self.assertEqual(
            baseline["conditions"]["ref_name"]["include"],
            ["refs/heads/main", "refs/heads/dev"],
        )
        rules = {rule["type"]: rule for rule in baseline["rules"]}
        self.assertEqual(
            set(rules),
            {"pull_request", "required_status_checks", "non_fast_forward", "deletion"},
        )
        self.assertEqual(
            rules["pull_request"]["parameters"]["required_approving_review_count"], 0
        )
        self.assertTrue(
            rules["pull_request"]["parameters"]["required_review_thread_resolution"]
        )
        self.assertTrue(
            rules["required_status_checks"]["parameters"][
                "strict_required_status_checks_policy"
            ]
        )
        self.assertEqual(
            rules["required_status_checks"]["parameters"]["required_status_checks"],
            [CHECK],
        )

    def test_only_selected_user_can_bypass_protected_branch_update_restriction_via_pr(
        self,
    ):
        _, gate, _ = configure.build_payloads([CHECK], 42)
        self.assertEqual(
            gate["conditions"]["ref_name"]["include"],
            ["refs/heads/main", "refs/heads/dev"],
        )
        self.assertEqual(
            gate["rules"],
            [
                {
                    "type": "update",
                    "parameters": {"update_allows_fetch_and_merge": False},
                }
            ],
        )
        self.assertEqual(
            gate["bypass_actors"],
            [{"actor_id": 42, "actor_type": "User", "bypass_mode": "pull_request"}],
        )

    def test_sensitive_reviews_only_allow_selected_user_to_bypass_reviews_via_pr(self):
        baseline, _, reviews = configure.build_payloads([CHECK], 42)
        self.assertEqual(reviews["name"], "template-sensitive-file-reviews")
        self.assertEqual(reviews["conditions"], baseline["conditions"])
        self.assertEqual(
            reviews["bypass_actors"],
            [{"actor_id": 42, "actor_type": "User", "bypass_mode": "pull_request"}],
        )
        self.assertEqual(len(reviews["rules"]), 1)
        rule = reviews["rules"][0]
        self.assertEqual(rule["type"], "pull_request")
        self.assertTrue(rule["parameters"]["require_code_owner_review"])
        self.assertTrue(rule["parameters"]["dismiss_stale_reviews_on_push"])
        self.assertEqual(rule["parameters"]["required_approving_review_count"], 0)
        self.assertEqual(baseline["bypass_actors"], [])

    def test_codeowners_protects_ci_itself_policies_scripts_and_tests(self):
        expected = configure.render_codeowners("owner")
        for path in ["/.github/", "/policies/", "/scripts/", "/tests/"]:
            self.assertIn(f"{path} @owner", expected.splitlines())
        committed = (ROOT / ".github/CODEOWNERS").read_text()
        entries = [
            line for line in committed.splitlines() if line and not line.startswith("#")
        ]
        owner = entries[0].split()[-1].removeprefix("@")
        self.assertEqual(committed, configure.render_codeowners(owner))

    def test_local_codeowners_preparation_needs_no_api_and_creates_no_policies(self):
        api = FakeGitHub()
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(configure, "ROOT", Path(temporary)),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                result = configure.main(
                    ["--merger", "new-owner", "--prepare-codeowners"], api=api
                )
            self.assertEqual(result, 0)
            self.assertEqual(
                (Path(temporary) / ".github/CODEOWNERS").read_text(),
                configure.render_codeowners("new-owner"),
            )
        self.assertEqual(api.calls, [])

    def test_missing_or_mismatched_codeowners_prevent_all_mutations(self):
        for missing in [False, True]:
            with self.subTest(missing=missing):
                api = FakeGitHub()
                api.codeowner = "someone-else"
                api.missing_codeowners = missing
                self.assertEqual(self.invoke(api, apply=True), 1)
                self.assertEqual(api.writes, [])

    def test_dev_codeowner_is_checked_independently_of_main(self):
        api = FakeGitHub()
        api.dev_sha = "dev-commit"
        api.dev_codeowner = "someone-else"
        self.assertEqual(self.invoke(api, apply=True), 1)
        self.assertEqual(api.writes, [])

    def test_upgrade_adds_review_policy_without_duplicating_original_rulesets(self):
        api = FakeGitHub()
        for number, policy in enumerate(
            configure.build_payloads([CHECK], 42)[:2], start=1
        ):
            api.stored[number] = {
                **copy.deepcopy(policy),
                "id": number,
                "source_type": "Repository",
                "source": "owner/project",
            }
        self.assertEqual(self.invoke(api, apply=True), 0)
        self.assertEqual([call[0] for call in api.writes], ["PUT", "PUT", "POST"])
        self.assertEqual(len(api.stored), 3)

    def test_policy_templates_are_not_modified_by_rendering(self):
        configure.build_payloads([CHECK], 42)
        for filename in configure.POLICY_FILES:
            self.assertEqual(
                json.loads((ROOT / "policies" / filename).read_text())["bypass_actors"],
                [],
            )

    def test_preview_performs_no_writes(self):
        api = FakeGitHub()
        self.assertEqual(self.invoke(api), 0)
        self.assertEqual(api.writes, [])

    def test_apply_creates_then_updates_same_rulesets_and_preserves_unrelated_rules(
        self,
    ):
        api = FakeGitHub()
        self.assertEqual(self.invoke(api, apply=True), 0)
        self.assertEqual([call[0] for call in api.writes], ["POST", "POST", "POST"])
        self.assertEqual(self.invoke(api, apply=True), 0)
        self.assertEqual(
            [call[0] for call in api.writes],
            ["POST", "POST", "POST", "PUT", "PUT", "PUT"],
        )
        self.assertEqual(len(api.stored), 3)
        self.assertFalse(any(call[1].endswith("/999") for call in api.writes))

    def test_failed_ci_prevents_all_mutations(self):
        api = FakeGitHub()
        api.conclusion = "failure"
        self.assertEqual(self.invoke(api, apply=True), 1)
        self.assertEqual(api.writes, [])

    def test_ambiguous_check_names_prevent_all_mutations(self):
        api = FakeGitHub()
        api.extra_run = True
        self.assertEqual(self.invoke(api, apply=True), 1)
        self.assertEqual(api.writes, [])

    def test_missing_or_skipped_required_jobs_prevent_all_mutations(self):
        for result in ["skipped", "neutral", None]:
            with self.subTest(conclusion=result):
                api = FakeGitHub()
                api.conclusion = result
                self.assertEqual(self.invoke(api, apply=True), 1)
                self.assertEqual(api.writes, [])

    def test_check_identity_is_bound_to_its_actual_provider(self):
        api = FakeGitHub()
        payloads = configure.inspect_repository(
            api, "owner/project", "owner", ["Repository checks"]
        )
        rules = {rule["type"]: rule for rule in payloads[0]["rules"]}
        self.assertEqual(
            rules["required_status_checks"]["parameters"]["required_status_checks"],
            [CHECK],
        )

    def test_missing_admin_access_prevents_all_mutations(self):
        api = FakeGitHub()
        api.admin = False
        self.assertEqual(self.invoke(api, apply=True), 1)
        self.assertEqual(api.writes, [])

    def test_missing_dev_prevents_all_mutations(self):
        api = FakeGitHub()
        api.missing_dev = True
        self.assertEqual(self.invoke(api, apply=True), 1)
        self.assertEqual(api.writes, [])

    def test_duplicate_managed_ruleset_names_are_rejected(self):
        api = FakeGitHub()
        for number in [1, 2]:
            api.stored[number] = {"id": number, "name": "template-protected-branches"}
        self.assertEqual(self.invoke(api, apply=True), 1)
        self.assertEqual(api.writes, [])

    def test_unavailable_rulesets_stop_the_apply(self):
        api = FakeGitHub()
        api.fail_write = True
        self.assertEqual(self.invoke(api, apply=True), 1)
        self.assertEqual(len(api.writes), 1)

    def test_verification_tolerates_server_defaults_but_rejects_extra_bypasses(self):
        self.assertTrue(
            configure.contains_expected(
                {
                    "rules": [
                        {
                            "type": "update",
                            "parameters": {"update_allows_fetch_and_merge": False},
                        }
                    ]
                },
                {"rules": [{"type": "update"}]},
            )
        )
        expected = {
            "type": "update",
            "parameters": {"update_allows_fetch_and_merge": False},
        }
        self.assertTrue(configure.contains_expected({"type": "update"}, expected))
        self.assertFalse(
            configure.contains_expected(
                {
                    "type": "update",
                    "parameters": {"update_allows_fetch_and_merge": True},
                },
                expected,
            )
        )
        self.assertFalse(
            configure.contains_expected(
                {"bypass_actors": [{"actor_id": 42}]}, {"bypass_actors": []}
            )
        )


if __name__ == "__main__":
    unittest.main()
