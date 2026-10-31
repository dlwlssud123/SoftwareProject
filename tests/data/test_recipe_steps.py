from agetech_data.recipes.steps import clean_step_text, extract_steps


def _row(**manual):
    """MANUAL01~20 / MANUAL_IMG01~20 을 빈 문자열로 채운 원본 행."""
    row = {f"MANUAL{i:02d}": "" for i in range(1, 21)}
    row.update({f"MANUAL_IMG{i:02d}": "" for i in range(1, 21)})
    row.update(manual)
    return row


def _codes(result):
    return [i.code for i in result.issues]


def test_clean_step_text_removes_number_and_marker_only():
    assert clean_step_text("1. 연두부는 체에 내린다.a") == ("연두부는 체에 내린다.", 1, "a")
    assert clean_step_text("3) 냄비에 끓인다") == ("냄비에 끓인다", 3, None)
    # 문장 중간의 숫자·영문은 건드리지 않는다
    assert clean_step_text("2. 180도 오븐에서 10분 굽는다.") == ("180도 오븐에서 10분 굽는다.", 2, None)
    assert clean_step_text("올리브유를 두른다")[1] is None


def test_original_numbers_preserved_and_not_renumbered():
    """사과 새우 북엇국(33) 형태: 2·3·5단계만 있음 → 번호를 1·2·3으로 다시 매기지 않는다."""
    r = extract_steps(_row(MANUAL02="2. 북어채를 불린다.", MANUAL03="3. 사과를 썬다.", MANUAL05="5. 끓인다."))
    assert [(s.source_field, s.source_no, s.stated_no) for s in r.steps] == [
        ("MANUAL02", 2, 2), ("MANUAL03", 3, 3), ("MANUAL05", 5, 5)]
    assert r.steps[0].text_raw == "2. 북어채를 불린다."
    assert r.missing_nos == [1, 4]
    assert "step_gap" in _codes(r) and "step_first_missing" in _codes(r)


def test_middle_gap_without_first_missing():
    r = extract_steps(_row(MANUAL01="1. a 준비", MANUAL02="2. 섞는다", MANUAL04="4. 담는다"))
    assert r.missing_nos == [3]
    assert "step_gap" in _codes(r) and "step_first_missing" not in _codes(r)


def test_trailing_empty_slots_are_not_missing():
    r = extract_steps(_row(MANUAL01="1. 씻는다", MANUAL02="2. 썬다", MANUAL03="3. 볶는다"))
    assert r.missing_nos == [] and "step_gap" not in _codes(r)


def test_no_steps():
    r = extract_steps(_row())
    assert r.steps == [] and _codes(r) == ["steps_none"]


def test_number_mismatch_duplicate_and_image_only():
    r = extract_steps(_row(
        MANUAL01="1. 씻는다", MANUAL02="1. 또 씻는다", MANUAL_IMG03="http://x/3.png",
    ))
    codes = _codes(r)
    assert "step_number_mismatch" in codes          # MANUAL02 칸에 "1." 이 적힘
    assert "step_number_duplicate" in codes
    assert "step_image_without_text" in codes


def test_unnumbered_step_uses_slot_number():
    r = extract_steps(_row(MANUAL01="씻는다", MANUAL03="볶는다"))
    assert [s.number for s in r.steps] == [1, 3]
    assert r.missing_nos == [2]
    assert _codes(r).count("step_unnumbered") == 2
