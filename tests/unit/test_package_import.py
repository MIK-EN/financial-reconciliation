from importlib.util import find_spec


def test_application_package_uses_product_name():
    assert find_spec("english_for_developers") is not None
