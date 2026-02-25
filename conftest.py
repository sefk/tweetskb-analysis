def pytest_addoption(parser):
    parser.addoption(
        "--month",
        default="2013-01",
        help="Year-month to test against (default: 2013-01)",
    )
    parser.addoption(
        "--months",
        nargs="+",
        default=["2013-01", "2013-06", "2014-01"],
        help="Year-months for E2E tests (default: 2013-01 2013-06 2014-01)",
    )
