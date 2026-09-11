import agent


def test_package_imports_and_has_version():
    assert agent.__version__ == "0.1.0"
