from services.exercise_service import ExerciseService

# ILIAS shows a confirmation screen before actually removing a team member.
CONFIRM_SCREEN = """
<form action="/ilias.php?cmdClass=ilExSubmissionTeamGUI&rtoken=abc123">
  <input type="submit" name="cmd[removeTeamMember]" value="Entfernen">
  <input type="submit" name="cmd[cancel]" value="Abbrechen">
</form>
"""

# The page that produced the confirmation only offers the confirm command.
TEAM_SCREEN = """
<form action="/ilias.php?cmdClass=ilExSubmissionTeamGUI">
  <input type="submit" name="cmd[confirmRemoveTeamMember]" value="Entfernen">
</form>
"""


def test_confirmation_command_is_found_on_confirm_screen() -> None:
    found = ExerciseService._find_confirmation_command(
        CONFIRM_SCREEN, "removeteammember"
    )
    assert found is not None
    action, cmd_name = found
    assert cmd_name == "cmd[removeTeamMember]"
    assert "rtoken=abc123" in action


def test_confirm_command_itself_is_not_reused() -> None:
    # Re-posting cmd[confirmRemoveTeamMember] would loop on the same screen.
    assert (
        ExerciseService._find_confirmation_command(TEAM_SCREEN, "removeteammember")
        is None
    )


# Real row text from an ILIAS "mode=all" assignment overview.
SUBMITTED_ROW = (
    "Beendet Blatt 1 Bereits abgegebene Dateien Beendet am 4. Mai 2026, 08:00 "
    "Anforderung Verpflichtend Datum der letzten Abgabe 3. Mai 2026, 09:51 "
    "Type Datei Status Nicht bewertet"
)


def test_deadline_parses_german_long_form_dates() -> None:
    # ILIAS writes "4. Mai 2026, 08:00", never "04.05.2026".
    assert ExerciseService._extract_deadline(SUBMITTED_ROW) == "4. Mai 2026, 08:00"


def test_deadline_prefers_the_deadline_over_the_submission_date() -> None:
    # "Datum der letzten Abgabe 3. Mai 2026" must not win over "Beendet am".
    assert "3. Mai" not in ExerciseService._extract_deadline(SUBMITTED_ROW)


def test_deadline_still_parses_numeric_dates() -> None:
    assert (
        ExerciseService._extract_deadline("Abgabetermin 04.05.2026 08:00")
        == "04.05.2026 08:00"
    )


def test_deadline_is_empty_when_row_has_no_date() -> None:
    assert ExerciseService._extract_deadline("Blatt 1 Verpflichtend") == ""


def test_status_reports_submission_not_grading() -> None:
    assert ExerciseService._extract_status(SUBMITTED_ROW) == "bereits abgegeben"


def test_unsubmitted_row_is_not_reported_as_submitted() -> None:
    # "abgegeben" is a substring of "nicht abgegeben" -- order matters.
    assert (
        ExerciseService._extract_status("Blatt 2 Nicht abgegeben") == "nicht abgegeben"
    )


def test_rtoken_is_read_from_the_form_action() -> None:
    assert (
        ExerciseService._extract_rtoken(
            "/ilias.php?cmdClass=ilExSubmissionTeamGUI&rtoken=abc123"
        )
        == "abc123"
    )


def test_find_url_with_ass_id_prefers_the_requested_assignment() -> None:
    html = (
        "ilias.php?cmdClass=ilExSubmissionFileGUI&cmd=submissionScreen&ass_id=1 "
        "ilias.php?cmdClass=ilExSubmissionFileGUI&cmd=submissionScreen&ass_id=42"
    )
    url = ExerciseService._find_url_with_ass_id(
        html,
        r"ilias\.php\?[^'\"\s]*cmdClass=ilExSubmissionFileGUI&cmd=submissionScreen[^'\"\s]*",
        "42",
    )
    assert url.endswith("ass_id=42")


def test_find_url_with_ass_id_unescapes_html_entities() -> None:
    html = "ilias.php?cmdClass=ilExSubmissionFileGUI&amp;cmd=submissionScreen&amp;ass_id=42"
    url = ExerciseService._find_url_with_ass_id(
        html,
        r"ilias\.php\?[^'\"\s]*cmdClass=ilExSubmissionFileGUI&amp;cmd=submissionScreen[^'\"\s]*",
        "42",
    )
    assert "&amp;" not in url
    assert url.endswith("ass_id=42")
