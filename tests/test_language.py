from app.state.language import tag_language


def test_pure_english():
    assert tag_language("I need an appointment tomorrow morning") == "en"


def test_pure_hindi():
    assert tag_language("मुझे कल सुबह अपॉइंटमेंट चाहिए") == "hi"


def test_code_switched():
    assert tag_language("मुझे appointment चाहिए for tomorrow") == "mixed"


def test_romanised_hindi_tags_en_bucket():
    # Romanised Hindi can't be script-detected; it lands in 'en' for metrics
    # bucketing only — understanding is untouched (documented limitation).
    assert tag_language("mujhe kal subah appointment chahiye") == "en"


def test_empty_and_numeric():
    assert tag_language("") == "en"
    assert tag_language("10:30") == "en"
