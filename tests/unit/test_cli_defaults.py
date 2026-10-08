from adaslog.cli.main import build_parser


def test_llm_flag_defaults_to_none_not_rule():
    parser = build_parser()
    args = parser.parse_args(["analyze", "x.log"])
    assert args.llm is None
    assert args.no_progress is False
