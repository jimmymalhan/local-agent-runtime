"""Argument parsing and CLI entry point."""
from __future__ import annotations

import argparse

from .commands import cmd_init, cmd_show, cmd_update
from .types import StageInput


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    sub: argparse._SubParsersAction[argparse.ArgumentParser] = (
        parser.add_subparsers(dest="cmd", required=True)
    )

    init: argparse.ArgumentParser = sub.add_parser("init")
    init.add_argument("--task", required=True)
    init.add_argument("--stages", nargs="+", required=True)
    init.add_argument("--weights", nargs="*")
    init.add_argument("--labels", nargs="*")

    for name in ("start", "tick", "complete", "fail"):
        p: argparse.ArgumentParser = sub.add_parser(name)
        p.add_argument("--stage", required=True)
        p.add_argument("--label")
        p.add_argument("--percent", type=float)
        p.add_argument("--detail")

    sub.add_parser("show")

    args: argparse.Namespace = parser.parse_args()
    if args.cmd == "init":
        weights_list: list[str] | None = args.weights
        if weights_list:
            if len(weights_list) != len(args.stages):
                raise SystemExit("weights length must match stages length")
            labels_list: list[str] = args.labels or args.stages
            if len(labels_list) != len(args.stages):
                raise SystemExit("labels length must match stages length")
            args.stages = [
                StageInput(id=stage_id, weight=float(weight), label=label)
                for stage_id, weight, label in zip(
                    args.stages, weights_list, labels_list
                )
            ]
        else:
            total: int = len(args.stages) or 1
            weight: float = round(100.0 / total, 2)
            args.stages = [
                StageInput(
                    id=stage_id,
                    weight=weight,
                    label=stage_id.replace("-", " "),
                )
                for stage_id in args.stages
            ]
        cmd_init(args)
    elif args.cmd == "show":
        cmd_show(args)
    elif args.cmd == "start":
        cmd_update(args, "running")
    elif args.cmd == "tick":
        cmd_update(args, "running")
    elif args.cmd == "complete":
        cmd_update(args, "completed")
    else:
        cmd_update(args, "failed")
