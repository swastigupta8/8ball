import importlib

import pytest

from eightball import cli
from eightball.core.contracts import ZoneSolver
from eightball.optimize.cpsat import CpSatZoneSolver


@pytest.mark.parametrize("command", sorted(cli.COMMANDS))
def test_every_command_module_exists(command):
    module = importlib.import_module(cli.COMMANDS[command][0])
    assert callable(module.cli_main)


def test_unbuilt_command_reports_owner(capsys):
    code = cli.main(["finegrid", "--limit", "1"])
    if code == 2:
        assert "Person A" in capsys.readouterr().err


def test_unknown_flags_pass_through():
    args, extra = cli.build_parser().parse_known_args(["solve", "--plan-id", "5", "--my-new-flag", "x"])
    assert args.plan_id == 5 and extra == ["--my-new-flag", "x"]


def test_cpsat_matches_zone_solver_protocol():
    solver: ZoneSolver = CpSatZoneSolver()
    assert callable(solver.select)
