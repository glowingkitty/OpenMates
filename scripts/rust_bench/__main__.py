"""CLI for the paired Rust-vs-TypeScript CLI benchmark.

Subcommands (run from the repository root):

  python3 -m scripts.rust_bench run --api-url URL --rust-profile DIR --ts-profile DIR [...]
  python3 -m scripts.rust_bench login --arm rust|typescript --api-url URL --rust-profile DIR --ts-profile DIR
  python3 -m scripts.rust_bench arm-env --arm rust|typescript ...   (JSON argv prefix + env for a CI driver)
  python3 -m scripts.rust_bench selftest [--meter auto|cgroup|rusage]

Profiles must already be signed in (use `login`, or let the CI spec pair each
arm with the env printed by `arm-env`). Exit codes: 0 all samples ok,
2 some samples failed (or a flow was skipped with --require-all-flows),
1 usage/isolation/not-signed-in error.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import flows as F
from .meter import MeterError, build_meter, maybe_reexec_in_scope
from .runner import Runner, build_report, cli_version, now_iso, write_outputs
from .selftest import run_selftest

REPO = Path(__file__).resolve().parents[2]


def default_rust_bin() -> str:
    target = os.environ.get("CARGO_TARGET_DIR") or str(REPO / "frontend/packages/openmates-tui-native/target")
    return str(Path(target) / "release" / "openmates")


def add_arm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-url", required=True, help="API base URL, e.g. http://localhost:8000 in CI")
    parser.add_argument("--app-url", help="Web app URL (OPENMATES_APP_URL), needed for pairing links")
    parser.add_argument("--rust-bin", default=default_rust_bin(), help="native Rust `openmates` binary")
    parser.add_argument("--ts-cmd", default="openmates",
                        help='TypeScript CLI command, e.g. "node frontend/packages/openmates-cli/dist/cli.js" '
                             "(default: global npm `openmates` launcher)")
    parser.add_argument("--rust-profile", type=Path, required=True, help="private profile root for the Rust arm")
    parser.add_argument("--ts-profile", type=Path, required=True, help="private profile root for the TS arm")
    parser.add_argument("--pass-env", action="append", default=[],
                        help="extra env var to inherit into both arms (repeatable)")


def build_arms(args) -> dict[str, F.Arm]:
    rust_cmd = [str(Path(args.rust_bin).resolve())]
    ts_cmd = F.parse_command(args.ts_cmd)
    resolved_ts = shutil.which(ts_cmd[0]) or ts_cmd[0]
    if not (Path(rust_cmd[0]).is_file() and os.access(rust_cmd[0], os.X_OK)):
        raise F.IsolationError(f"Rust binary not found/executable: {rust_cmd[0]} (cargo build --release)")
    if not shutil.which(ts_cmd[0]) and not Path(ts_cmd[0]).exists():
        raise F.IsolationError(f"TypeScript CLI command not found: {ts_cmd[0]}")
    if Path(resolved_ts).resolve() == Path(rust_cmd[0]).resolve():
        raise F.IsolationError("--ts-cmd resolves to the Rust binary; pass the npm CLI explicitly")
    arms = {
        "rust": F.Arm("rust", rust_cmd, args.rust_profile.absolute(), args.api_url, args.app_url, args.pass_env),
        "typescript": F.Arm("typescript", ts_cmd, args.ts_profile.absolute(), args.api_url, args.app_url,
                            args.pass_env),
    }
    F.validate_isolation(list(arms.values()), Path(os.path.expanduser("~")))
    for arm in arms.values():
        arm.prepare_dirs()
    return arms


def selected_flows(args) -> list[str]:
    names = [n.strip() for n in args.flows.split(",") if n.strip()] if args.flows else (
        list(F.ALL_FLOWS) if args.inference else list(F.READ_FLOWS))
    unknown = [n for n in names if n not in F.FLOWS]
    if unknown:
        raise F.IsolationError(f"unknown flows: {', '.join(unknown)} (known: {', '.join(F.ALL_FLOWS)})")
    gated = [n for n in names if F.FLOWS[n].needs_inference and not args.inference]
    if gated:
        raise F.IsolationError(f"flows {', '.join(gated)} need AI inference; add --inference to opt in")
    return names


def cmd_run(args) -> int:
    arms = build_arms(args)
    flows = selected_flows(args)
    meter = build_meter(args.meter)
    started = now_iso()
    versions = {name: cli_version(meter, arm) for name, arm in arms.items()}
    runner = Runner(meter, arms, samples=args.samples, warmup=args.warmup, timeout=args.timeout,
                    message=args.message, followup=args.followup_message, app_skill=args.app_skill,
                    chat_ids={"rust": args.rust_chat_id, "typescript": args.ts_chat_id},
                    create_chat=args.inference, keep_output=args.keep_output,
                    arm_messages={"rust": args.rust_message, "typescript": args.ts_message},
                    arm_followups={"rust": args.rust_followup_message, "typescript": args.ts_followup_message},
                    expect_model=args.expect_model)
    if args.keep_output:
        args.keep_output.mkdir(parents=True, exist_ok=True)
    try:
        if not args.skip_auth_check:
            problems = {arm: error for arm, error in runner.preflight().items() if error}
            if problems:
                detail = ", ".join(f"{arm}: {error}" for arm, error in problems.items())
                raise F.IsolationError(f"profile not signed in / unusable ({detail}); "
                                       "sign in with `python3 -m scripts.rust_bench login --arm ...`")
        results = runner.run(flows)
    finally:
        runner.close()
    config = {"apiUrl": args.api_url, "samples": args.samples, "warmupPerArm": args.warmup,
              "order": "paired, alternating first arm per pair (AB BA AB ...)", "flows": flows,
              "inference": args.inference, "timeoutSeconds": args.timeout,
              "appSkill": args.app_skill if "app-skill" in flows else None,
              "expectModel": args.expect_model,
              "messages": {"rust": args.rust_message or args.message, "typescript": args.ts_message or args.message},
              "followups": {"rust": args.rust_followup_message or args.followup_message,
                            "typescript": args.ts_followup_message or args.followup_message}}
    report = build_report(meter=meter, arms=arms, config=config, flows=results, started=started, versions=versions)
    markdown = args.markdown or args.out.with_suffix(".md")
    print(write_outputs(report, args.out, markdown))
    print(f"JSON: {args.out}\nMarkdown: {markdown}", file=sys.stderr)
    failed = any((args.require_all_flows if f.get("skipped") else any(not s["ok"] for s in f["samples"]))
                 for f in results)
    return 2 if failed else 0


def cmd_selftest(args) -> int:
    result = run_selftest(build_meter(args.meter))
    text = json.dumps(result, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n")
    print(text)
    return 0 if result["ok"] else 2


def cmd_arm_env(args) -> int:
    arm = build_arms(args)[args.arm]
    print(json.dumps({"argvPrefix": arm.argv([]), "env": arm.env(), "stateDir": str(arm.state_dir)}, indent=2))
    return 0


def cmd_login(args) -> int:
    arm = build_arms(args)[args.arm]
    # Foreground, inherited terminal: the operator (or a CI PTY driver) completes pairing.
    return subprocess.call(arm.argv(["login"]), env=arm.env(), cwd=str(arm.profile))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python3 -m scripts.rust_bench", description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = root.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="paired benchmark")
    add_arm_args(run)
    run.add_argument("--flows", help=f"comma list from {','.join(F.ALL_FLOWS)} "
                                     "(default: read flows; all flows with --inference)")
    run.add_argument("--inference", action="store_true",
                     help="opt in to flows that trigger AI inference / app skills (send, follow-up, app-skill)")
    run.add_argument("--samples", type=int, default=20)
    run.add_argument("--warmup", type=int, default=1, help="untimed warmup invocations per arm per flow")
    run.add_argument("--timeout", type=float, default=300.0, help="per-invocation timeout seconds")
    run.add_argument("--message", default=F.DEFAULT_MESSAGE)
    run.add_argument("--followup-message", default=F.DEFAULT_FOLLOWUP)
    for arm in ("rust", "ts"):
        run.add_argument(f"--{arm}-message", help=f"override --message for the {arm} arm only (same wire request, "
                                                  "different CLI mention syntax)")
        run.add_argument(f"--{arm}-followup-message", help=f"override --followup-message for the {arm} arm only")
    run.add_argument("--expect-model", help='fail send/follow-up samples whose answering modelName differs, '
                                            'e.g. "Gemini 3.8 Flash"')
    run.add_argument("--app-skill", default=F.DEFAULT_APP_SKILL, help="args after `openmates apps`")
    run.add_argument("--rust-chat-id", help="chat for chats-show in the Rust arm (default: first listed)")
    run.add_argument("--ts-chat-id", help="chat for chats-show in the TS arm (default: first listed)")
    run.add_argument("--meter", choices=("auto", "cgroup", "rusage"), default="auto")
    run.add_argument("--require-all-flows", action="store_true",
                     help="exit 2 when a flow was skipped (e.g. no chat to show)")
    run.add_argument("--skip-auth-check", action="store_true",
                     help="skip the untimed signed-in preflight (harness smoke tests only)")
    run.add_argument("--out", type=Path, default=REPO / "test-results/rust-bench/report.json")
    run.add_argument("--markdown", type=Path)
    run.add_argument("--keep-output", type=Path, help="keep CLI stdout/stderr per invocation (private data!)")
    run.set_defaults(func=cmd_run)

    selftest = sub.add_parser("selftest", help="meter smoke test on trivial commands")
    selftest.add_argument("--meter", choices=("auto", "cgroup", "rusage"), default="auto")
    selftest.add_argument("--json", type=Path)
    selftest.set_defaults(func=cmd_selftest)

    for name, func, text in (("arm-env", cmd_arm_env, "print one arm's isolated argv prefix and env as JSON"),
                             ("login", cmd_login, "sign one arm's isolated profile in (foreground)")):
        command = sub.add_parser(name, help=text)
        add_arm_args(command)
        command.add_argument("--arm", choices=("rust", "typescript"), required=True)
        command.set_defaults(func=func)
    return root


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = parser().parse_args(argv)
    if args.command in ("run", "selftest"):
        os.environ.setdefault("PYTHONPATH", str(REPO))
        maybe_reexec_in_scope(args.meter, ["-m", "scripts.rust_bench", *argv])
    try:
        return args.func(args)
    except (F.IsolationError, MeterError) as error:
        print(f"rust_bench: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
