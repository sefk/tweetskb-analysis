def pytest_addoption(parser):
    parser.addoption(
        "--month",
        default="2013-01",
        help="Year-month to test against (default: 2013-01)",
    )
