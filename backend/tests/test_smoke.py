import zygos


def test_package_importable_and_versioned():
    assert zygos.__version__ == "2.0.0a0"
