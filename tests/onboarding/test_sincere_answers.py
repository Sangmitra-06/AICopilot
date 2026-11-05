"""Item 2: any sincere free-text answer, however vague, is accepted as given and stored in the reviewer's own words."""
import pytest

from app import onboarding as ob
from test_off_topic import FREE, at

SINCERE = [
    "very descriptive and precise", "descriptive and precise", "precise", "concise and accurate", "honest",
    "polite but direct", "short and to the point", "detailed", "well organized", "balanced and respectful",
    "it should be specific", "insightful comments", "gives concrete suggestions", "one that helps the authors",
    "a good one is easy to act on", "clear and kind", "thoughtful", "careful reading", "not too harsh",
    "backed by examples", "mentions page numbers", "it feels fair", "when it explains why", "constructive tone",
    "I just know it when I see it", "hard to say really", "mostly structure", "making up my mind",
    "being fair to the authors", "finding the time", "writing it all down", "staying objective",
    "authors who don't explain their choices", "sloppy notation", "too many typos", "unclear figures",
    "papers that oversell", "numbers that don't add up", "weak motivation", "missing details about the setup",
    "I care about reproducibility", "how well the story hangs together", "lack of comparison to other work",
    "short reviews with no reasons", "reviews that only say reject", "rude or sarcastic wording",
]


def test_there_are_at_least_thirty_cases():
    assert len(SINCERE) >= 30


@pytest.mark.parametrize("field", FREE)
@pytest.mark.parametrize("text", SINCERE)
def test_sincere_answers_are_stored_as_given_and_never_pushed_back(field, text):
    s = at(field)
    r = s.say(text)
    got = s.profile()["fields"][field]
    assert got["value"] == text and got["source"] == "answer"
    assert r.get("field") != field
    assert "didn't catch" not in str(r)
