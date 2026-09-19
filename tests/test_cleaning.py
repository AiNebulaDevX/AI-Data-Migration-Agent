from backend.cleaning.normalizers import normalize_date, normalize_email, normalize_whitespace


def test_whitespace_normalization():
    val, tr = normalize_whitespace(" John ")
    assert val == "John"
    assert tr is not None


def test_email_normalization():
    val, tr = normalize_email("RAHUL@EXAMPLE.COM")
    assert val == "rahul@example.com"
    assert tr is not None


def test_date_iso_unchanged():
    iso, tr, err = normalize_date("1998-02-10")
    assert iso == "1998-02-10"
    assert tr is None
    assert err is None


def test_ambiguous_date():
    iso, tr, err = normalize_date("01/02/1995")
    assert iso is None
    assert err and "Ambiguous" in err
