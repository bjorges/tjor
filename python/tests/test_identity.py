"""Unit tests for the session-identity module — each session-identity spec
scenario maps to at least one test."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_identity as ti

ENV = {
    "TJOR_SESSION_ID": "myrepo-a1b2c3d4",
    "TJOR_TASK_ID": "PLT-1234",
    "TJOR_HARNESS": "opencode",
    "TJOR_REPO": "myrepo",
}


def identity():
    return ti.load_identity(ENV)


class TestLoadIdentity:
    def test_loads_present_fields_only(self):
        ident = identity()
        assert ident.valid
        assert ident.values == {
            "x-agent-session-id": "myrepo-a1b2c3d4",
            "x-agent-task-id": "PLT-1234",
            "x-agent-harness": "opencode",
            "x-agent-repo": "myrepo",
        }

    def test_missing_session_id_invalid(self):
        ident = ti.load_identity({"TJOR_HARNESS": "opencode"})
        assert not ident.valid

    def test_malformed_value_invalidates_everything(self):
        env = dict(ENV, TJOR_REPO="evil\r\nx-injected: 1")
        ident = ti.load_identity(env)
        assert not ident.valid  # fail-closed, not partial trust

    def test_overlong_value_invalid(self):
        assert not ti.load_identity(dict(ENV, TJOR_TASK_ID="x" * 300)).valid

    def test_worktree_path_trimmed_to_basename(self):
        # full host paths leak username/directory layout; only the leaf name
        # may reach the wire (the in-cage env var keeps the full path)
        env = dict(ENV, TJOR_WORKTREE="/Users/alice/git/myrepo/wt-featurex")
        ident = ti.load_identity(env)
        assert ident.valid
        assert ident.values["x-agent-worktree"] == "wt-featurex"

    def test_worktree_trailing_slash_still_basename(self):
        env = dict(ENV, TJOR_WORKTREE="/Users/alice/git/myrepo/wt-1/")
        assert ti.load_identity(env).values["x-agent-worktree"] == "wt-1"


class TestTransform:
    def test_matching_headers_pass(self):
        final, stripped = ti.transform(
            identity(), {"x-agent-session-id": "myrepo-a1b2c3d4"}, inject=False
        )
        assert final == {"x-agent-session-id": "myrepo-a1b2c3d4"} and not stripped

    def test_forged_value_stripped(self):
        final, stripped = ti.transform(
            identity(), {"x-agent-session-id": "someone-else"}, inject=False
        )
        assert final == {} and stripped == {"x-agent-session-id": "someone-else"}

    def test_unknown_x_agent_header_stripped(self):
        final, stripped = ti.transform(identity(), {"x-agent-custom": "foo"}, inject=False)
        assert final == {} and "x-agent-custom" in stripped

    def test_unregistered_field_stripped(self):
        # identity has no worktree; a worktree claim is a forgery
        final, stripped = ti.transform(
            identity(), {"x-agent-worktree": "/tmp/x"}, inject=False
        )
        assert final == {} and "x-agent-worktree" in stripped

    def test_invalid_identity_strips_everything(self):
        bad = ti.load_identity({})
        final, stripped = ti.transform(
            bad, {"x-agent-session-id": "myrepo-a1b2c3d4"}, inject=True
        )
        assert final == {} and stripped

    def test_inject_sets_full_identity(self):
        final, stripped = ti.transform(
            identity(), {"x-agent-session-id": "someone-else"}, inject=True
        )
        assert final == identity().values
        assert stripped == {"x-agent-session-id": "someone-else"}

    def test_no_inject_adds_nothing(self):
        final, _ = ti.transform(identity(), {}, inject=False)
        assert final == {}


class TestInjectHosts:
    def test_shared_matcher_semantics(self):
        hosts = ti.parse_inject_hosts("api.anthropic.com, *.githubcopilot.com")
        assert ti.should_inject(hosts, "api.anthropic.com")
        assert ti.should_inject(hosts, "api.githubcopilot.com:443")
        assert not ti.should_inject(hosts, "githubcopilot.com")
        assert not ti.should_inject(hosts, "example.com")
        assert not ti.should_inject([], "api.anthropic.com")

    def test_parse_formats(self):
        assert ti.parse_inject_hosts("") == []
        assert ti.parse_inject_hosts("a.test,b.test c.test") == ["a.test", "b.test", "c.test"]
