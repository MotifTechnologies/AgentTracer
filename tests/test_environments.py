"""The registry, and what a backend reports about a running sandbox.

`build` and `attach` need a real sandbox and are covered by each server's smoke
test. What is worth pinning here is the part that fails silently: `describe`
returning a plausible-but-wrong directory sends an MCP server looking for the
agent's files somewhere they are not, and the tool call comes back "no such
file" rather than failing where the mistake is.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from agent_tracer.config.schema import ConfigError, EnvironmentConfig
from agent_tracer.environments import (
    BUILTIN,
    MAX_READ_BYTES,
    MAX_WRITE_BYTES,
    WRITE_CHUNK_BYTES,
    _load,
    describe,
    from_env,
    read_bytes,
    resolve,
    write_bytes,
)
from agent_tracer.mcp.discovery import SANDBOX_ENV_VARS, sandbox_env


def _cfg(**kw) -> EnvironmentConfig:
    kw.setdefault("type", "local")
    if kw["type"] != "local":
        kw.setdefault("image", "python:3.13-slim")
    return EnvironmentConfig(**kw)


class TestRegistry:
    def test_every_builtin_implements_the_whole_protocol(self):
        """A backend missing one of the three fails at the point it is used —
        `attach` only when an MCP server first calls a tool, which is late."""
        for name in BUILTIN:
            module = _load(name)
            for func in ("build", "describe", "attach"):
                assert callable(getattr(module, func, None)), f"{name}.{func} missing"

    def test_attach_needs_nothing_only_the_runner_has(self):
        """A spawned MCP server has `agent_tracer` on PYTHONPATH and whatever it
        declares for itself. stirrup belongs to the runner that spawned it, so a
        backend importing its provider at module level makes `attach` unusable
        from a server: the first tool call on that backend dies with
        ModuleNotFoundError rather than doing the work.
        """
        script = textwrap.dedent(
            """
            import sys

            sys.modules["stirrup"] = None  # as absent as it is in a server

            from agent_tracer.environments import attach

            for backend in ("local", "docker"):
                attach(backend, "some-id", {})
            """
        )
        done = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=False
        )

        assert done.returncode == 0, done.stderr

    def test_an_uninstalled_backend_names_the_ones_that_are(self):
        with pytest.raises(ConfigError) as e:
            describe(_cfg(type="no-such-backend"), None)
        message = str(e.value)
        assert "no-such-backend" in message
        for name in BUILTIN:
            assert name in message, f"{name} not offered as an alternative"


class TestBuild:
    """What a backend does with a setting it cannot honour.

    Ignoring one is the worst of the three answers: `local` dropped
    `allowed_commands` and stirrup reads `None` as "every command allowed", so
    an explicit restriction became no restriction.
    caps and said nothing.
    """

    def test_local_passes_on_the_allowlist(self):
        provider = _load("local").build(
            _cfg(type="local", allowed_commands=["^python"]), task_id=None
        )

        assert provider._allowed_commands == ["^python"]

    def test_local_with_no_allowlist_stays_unrestricted(self):
        provider = _load("local").build(_cfg(type="local"), task_id=None)

        assert provider._allowed_commands is None


class TestAttach:
    def test_docker_runs_a_plain_shell_not_a_login_shell(self, monkeypatch):
        """`sh -lc` sources /etc/profile and ~/.profile, and whatever they print
        lands on stdout — which is the channel every sandbox-bound server parses:
        base64 payloads in filesystem, NUL-separated records in list_directory,
        JSON in sqlite. A profile that echoes one line corrupts all three, and
        one that `cd`s moves what a relative path meant.

        It was also the only login shell in the project: stirrup's own code_exec
        runs `bash -c` and the local backend runs `sh -c`, so the agent and its
        tools saw two different environments on docker alone.
        """
        module = _load("docker")
        seen: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(module.subprocess, "run", fake_run)

        module.attach("abc123", {"user": "someone"}).exec("echo hi")

        assert seen["argv"] == [
            "docker",
            "exec",
            "--user",
            "someone",
            "abc123",
            "sh",
            "-c",
            "echo hi",
        ]


class TestDescribe:
    def test_local_reports_the_directory_commands_actually_run_in(self):
        """Not `working_dir`.

        stirrup's local provider makes its own temp directory and runs every
        command there, ignoring the configured value. A server that resolved a
        relative path against `/workspace` would miss the agent's files.
        """
        provider = SimpleNamespace(temp_dir="/tmp/local_exec_env_x")
        out = describe(_cfg(type="local", working_dir="/workspace"), provider)

        assert out["workdir"] == "/tmp/local_exec_env_x"
        assert out["host_dir"] == "/tmp/local_exec_env_x"
        assert out["sandbox_id"] is None

    def test_docker_reports_the_container_and_the_configured_workdir(self):
        provider = SimpleNamespace(container_id="abc123", temp_dir="/tmp/host")
        out = describe(
            _cfg(type="docker", working_dir="/workspace", user="user"), provider
        )

        assert out["sandbox_id"] == "abc123"
        assert out["workdir"] == "/workspace"
        assert out["host_dir"] == "/tmp/host"
        assert out["user"] == "user"


class TestSandboxEnv:
    def test_every_documented_variable_can_be_produced(self):
        out = sandbox_env(
            env_type="docker",
            sandbox_id="abc",
            workdir="/workspace",
            host_dir="/tmp/host",
            user="user",
            options={"k": "v"},
        )
        assert set(out) == set(SANDBOX_ENV_VARS)

    def test_absent_beats_empty(self):
        """Servers test for presence; "" would read as a configured value."""
        out = sandbox_env(env_type="local", sandbox_id=None, workdir=None)

        assert out == {"AGENT_TRACER_ENV_TYPE": "local"}

    def test_describe_feeds_sandbox_env_directly(self):
        """The orchestrator splats one into the other — keep the names aligned."""
        provider = SimpleNamespace(container_id="abc123", temp_dir="/tmp/host")
        cfg = _cfg(type="docker", working_dir="/workspace", user="user")

        out = sandbox_env(
            env_type=cfg.type, options=cfg.options, **describe(cfg, provider)
        )

        assert out["AGENT_TRACER_SANDBOX_ID"] == "abc123"
        assert out["AGENT_TRACER_WORKDIR"] == "/workspace"


class TestFromEnv:
    """The server side of the contract: reading back what the runner wrote."""

    def test_it_reads_what_sandbox_env_wrote(self):
        provider = SimpleNamespace(temp_dir="/tmp/local_exec_env_x")
        cfg = _cfg(type="local", working_dir="/workspace")
        written = sandbox_env(
            env_type=cfg.type, options=cfg.options, **describe(cfg, provider)
        )

        _access, workdir = from_env(written)

        assert workdir == "/tmp/local_exec_env_x"

    def test_options_arrive_as_the_dict_they_were_sent_as(self):
        """They cross as a JSON string and are handed to `attach` untouched."""
        written = sandbox_env(env_type="local", options={"user": "someone"})

        assert written["AGENT_TRACER_OPTIONS"] == '{"user": "someone"}'
        assert from_env(written)[1]  # parses rather than raising

    def test_no_description_means_local_and_this_directory(self):
        """So a server can be run by hand — its smoke test depends on this."""
        import os

        access, workdir = from_env({})

        assert workdir == os.getcwd()
        assert access.exec("true")[0] == 0

    def test_resolve_leaves_absolute_paths_alone(self):
        assert resolve("data.csv", "/work") == "/work/data.csv"
        assert resolve("/etc/hosts", "/work") == "/etc/hosts"
        assert resolve("data.csv", "/work/") == "/work/data.csv"

    def test_resolve_refuses_a_home_it_cannot_know(self):
        """`~` is the sandbox's home directory and this function has no way to
        learn it. Paths are shell-quoted on the way out, so a `~` survives as a
        literal: the read misses and the write makes a directory called `~`
        that nothing else looks in."""
        for path in ("~", "~/data.csv", "~someone/data.csv"):
            with pytest.raises(ValueError, match="~"):
                resolve(path, "/work")

    def test_resolve_refuses_an_empty_path(self):
        """`f"{workdir}/{''}"` is the working directory with a trailing slash,
        which reads as a successfully resolved path and is a missing argument."""
        with pytest.raises(ValueError):
            resolve("", "/work")

    def test_resolve_does_not_police_dot_dot(self):
        """Deliberate. Every tool documents its path as "absolute or relative to
        the working directory" and `/etc/hosts` is passed through above, so a
        containment check here would stop nothing a caller cannot do by writing
        the path out in full. The sandbox is the boundary, not this function."""
        assert resolve("../shared/data.csv", "/work") == "/work/../shared/data.csv"


class TestByteTransfer:
    """Moving bytes across an interface that only offers `exec`.

    Three servers depend on this being exact: filesystem round-trips text, and
    pdf and xlsx parse binary formats where one wrong byte is a corrupt file.
    """

    @pytest.fixture
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        access, _ = from_env({})
        return access, tmp_path

    def test_arbitrary_bytes_survive_the_round_trip(self, sandbox):
        """Not text: a NUL, a lone high byte, and a CRLF that a shell might eat."""
        access, root = sandbox
        payload = bytes(range(256)) + b"\r\n\x00 \xed\x95\x9c\xea\xb8\x80"

        write_bytes(access, str(root / "blob.bin"), payload)

        assert read_bytes(access, str(root / "blob.bin")) == payload

    def test_a_real_zip_container_survives(self, sandbox):
        """What .xlsx actually is — a byte off and it stops being readable."""
        import io
        import zipfile

        access, root = sandbox
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("sheet.xml", "<c>중간</c>")
        original = buffer.getvalue()

        write_bytes(access, str(root / "book.zip"), original)
        recovered = read_bytes(access, str(root / "book.zip"))

        assert recovered == original
        with zipfile.ZipFile(io.BytesIO(recovered)) as archive:
            assert archive.read("sheet.xml").decode() == "<c>중간</c>"

    def test_write_creates_missing_parents(self, sandbox):
        access, root = sandbox

        write_bytes(access, str(root / "a" / "b" / "c.txt"), b"x")

        assert (root / "a" / "b" / "c.txt").read_bytes() == b"x"

    def test_an_empty_file_is_not_an_error(self, sandbox):
        access, root = sandbox
        (root / "empty.txt").write_bytes(b"")

        assert read_bytes(access, str(root / "empty.txt")) == b""

    def test_a_missing_file_says_so(self, sandbox):
        access, root = sandbox

        with pytest.raises(FileNotFoundError, match=r"nope\.bin"):
            read_bytes(access, str(root / "nope.bin"))

    def test_an_oversized_write_is_refused_before_it_is_attempted(self, sandbox):
        """It would otherwise fail as "Argument list too long", which names the
        shell rather than the limit."""
        access, root = sandbox

        with pytest.raises(ValueError, match=str(MAX_WRITE_BYTES)):
            write_bytes(access, str(root / "big.bin"), b"x" * (MAX_WRITE_BYTES + 1))

        assert not (root / "big.bin").exists()

    def test_a_write_past_one_argv_string_still_arrives_exact(self, sandbox):
        """The band the guard never covered.

        A single argv string is capped at MAX_ARG_STRLEN (128 KiB) whatever
        ARG_MAX says, and the whole script is one argument to `sh -c`. base64's
        expansion put the real ceiling at 98,244 bytes, so everything from there
        up to MAX_WRITE_BYTES died as `OSError [Errno 7]` raised by
        `subprocess.run` before a shell existed — never reaching the `rc != 0`
        check, so the guard's message never appeared. A workbook clears 100 KB
        routinely.
        """
        access, root = sandbox
        payload = bytes(range(256)) * 1600  # 409,600 bytes, inside the old band

        write_bytes(access, str(root / "book.xlsx"), payload)

        assert read_bytes(access, str(root / "book.xlsx")) == payload

    def test_nothing_redirects_onto_the_destination(self, sandbox, monkeypatch):
        """`> path` has the shell truncate the target before base64 emits a
        byte. A full disk, or a timeout killing `docker exec` partway, then
        leaves the agent's only workbook truncated while the tool reports that
        it failed to write — and `write_cells` always overwrites in place. The
        bytes have to land on a sibling and be moved over it.
        """
        import re
        import shlex

        access, root = sandbox
        target = root / "book.xlsx"
        target.write_bytes(b"the original workbook")
        payload = b"z" * (WRITE_CHUNK_BYTES + 1)

        seen = []
        real = access.exec

        def record(command, timeout_s=120):
            seen.append(command)
            return real(command, timeout_s=timeout_s)

        monkeypatch.setattr(access, "exec", record, raising=False)
        write_bytes(access, str(target), payload)

        assert target.read_bytes() == payload
        # The staging file is a sibling, so match the redirect target whole.
        redirect = re.compile(rf">>?\s*{re.escape(shlex.quote(str(target)))}(\s|$)")
        assert not [c[:60] for c in seen if redirect.search(c)], (
            "the destination is truncated first"
        )
        assert any(c.startswith("mv ") for c in seen), [c[:60] for c in seen]

    def test_a_write_that_fails_partway_leaves_the_original(self, sandbox, monkeypatch):
        access, root = sandbox
        target = root / "book.xlsx"
        target.write_bytes(b"the original workbook")

        real, calls = access.exec, []

        def full_disk_after_the_first_chunk(command, timeout_s=120):
            calls.append(command)
            if (
                "base64 -d" in command
                and len([c for c in calls if "base64 -d" in c]) > 1
            ):
                return 1, "", "printf: write error: No space left on device"
            return real(command, timeout_s=timeout_s)

        monkeypatch.setattr(
            access, "exec", full_disk_after_the_first_chunk, raising=False
        )
        with pytest.raises(OSError, match=r"book\.xlsx"):
            write_bytes(access, str(target), b"z" * (WRITE_CHUNK_BYTES * 3))

        assert target.read_bytes() == b"the original workbook"
        assert not list(root.glob("book.xlsx.*")), "the staging file was left behind"

    def test_a_bare_filename_is_written_not_made_into_a_directory(self, sandbox):
        """`path.rsplit("/", 1)[0] or "/"` answers "a.txt" for "a.txt", so
        `mkdir -p` made a directory of that name and the redirect then failed
        with "Is a directory". Callers pass absolute paths today; these are
        public helpers."""
        access, root = sandbox  # the fixture is already chdir'd into root

        write_bytes(access, "note.txt", b"hello")

        assert (root / "note.txt").is_file()
        assert (root / "note.txt").read_bytes() == b"hello"

    def test_an_oversized_read_is_refused_by_size_not_by_transferring_it(
        self, sandbox, monkeypatch
    ):
        access, root = sandbox
        target = root / "huge.bin"
        target.write_bytes(b"x" * 32)

        # Patched rather than writing 32 MiB: the check sizes the file first,
        # and that ordering is the point of the test.
        real_exec = access.exec

        def fake_exec(command, timeout_s=120):
            if command.startswith("wc "):
                return 0, str(MAX_READ_BYTES + 1), ""
            raise AssertionError(f"transferred anyway: {command[:40]}")

        monkeypatch.setattr(access, "exec", fake_exec, raising=False)
        with pytest.raises(ValueError, match="larger than this reads"):
            read_bytes(access, str(target))
        assert real_exec


class TestContaminatedStdout:
    """What `exec` hands back is not only the file.

    `docker exec` runs `sh -lc`, a *login* shell, so `/etc/profile` and
    `/etc/profile.d/*` run first and any image that prints `mesg: ttyname
    failed`, an MOTD or a conda banner puts it on the same stdout as the
    payload. `b64decode` defaults to `validate=False`, which discards characters
    outside the alphabet *silently* — so the file comes back a few bytes wrong
    rather than not at all, and a PDF or an .xlsx that is one byte wrong is a
    file that no longer opens.
    """

    BANNER = "mesg: ttyname failed: Inappropriate ioctl for device\n"

    @pytest.fixture
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        access, _ = from_env({})
        return access, tmp_path

    def _wrap(self, access, monkeypatch, transform):
        real = access.exec

        def wrapped(command, timeout_s=120):
            rc, out, err = real(command, timeout_s=timeout_s)
            return rc, transform(command, out), err

        monkeypatch.setattr(access, "exec", wrapped, raising=False)

    def test_a_banner_before_the_payload_names_the_file(self, sandbox, monkeypatch):
        access, root = sandbox
        target = root / "book.xlsx"
        target.write_bytes(bytes(range(256)) * 4)
        self._wrap(
            access, monkeypatch, lambda c, out: out if "wc " in c else self.BANNER + out
        )

        with pytest.raises(OSError, match=r"book\.xlsx"):
            read_bytes(access, str(target))

    def test_a_banner_before_the_size_names_the_file(self, sandbox, monkeypatch):
        """`int(out.strip() or 0)` raised a bare ValueError naming nothing."""
        access, root = sandbox
        target = root / "book.xlsx"
        target.write_bytes(b"abc")
        self._wrap(
            access, monkeypatch, lambda c, out: self.BANNER + out if "wc " in c else out
        )

        with pytest.raises(OSError, match=r"book\.xlsx"):
            read_bytes(access, str(target))

    def test_a_short_transfer_is_caught_by_the_size_already_fetched(
        self, sandbox, monkeypatch
    ):
        """A whole base64 quantum missing still decodes, to a shorter file."""
        access, root = sandbox
        target = root / "book.xlsx"
        target.write_bytes(bytes(range(256)))
        self._wrap(
            access, monkeypatch, lambda c, out: out if "wc " in c else out.strip()[:-8]
        )

        with pytest.raises(OSError, match=r"book\.xlsx"):
            read_bytes(access, str(target))

    def test_base64_wrapped_at_76_columns_still_arrives_exact(
        self, sandbox, monkeypatch
    ):
        """The cost of dropping `-w0`, which is the flag BSD's base64 lacks."""
        import textwrap

        access, root = sandbox
        payload = bytes(range(256)) * 4
        target = root / "book.xlsx"
        target.write_bytes(payload)
        self._wrap(
            access,
            monkeypatch,
            lambda c, out: (
                out if "wc " in c else "\n".join(textwrap.wrap(out.strip(), 76)) + "\n"
            ),
        )

        assert read_bytes(access, str(target)) == payload

    def test_the_transfer_asks_for_no_option_a_BSD_shell_lacks(
        self, sandbox, monkeypatch
    ):
        """`stat -c %s` and `base64 -w0` are GNU/busybox only. On a BSD or macOS
        local backend they fail, and the failure was reported as
        `FileNotFoundError: No such file in the sandbox` — blaming the file for
        a missing flag."""
        access, root = sandbox
        (root / "f.bin").write_bytes(b"abc")

        seen = []
        real = access.exec

        def record(command, timeout_s=120):
            seen.append(command)
            return real(command, timeout_s=timeout_s)

        monkeypatch.setattr(access, "exec", record, raising=False)
        read_bytes(access, str(root / "f.bin"))

        assert not [c for c in seen if "stat -c" in c or "-w0" in c], seen
