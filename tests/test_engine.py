"""Template engine, validation and label tests.  Run: python -m unittest discover tests"""
import unittest

from correcty import i18n
from correcty import template_engine as engine
from correcty.validators import validate_template

PANEL_LOGIN = {
    "title": "Panel Login",
    "body": "Please log in to our panel using this URL: panel.example.com.",
    "sections": [
        {
            "id": "s1",
            "question": "Does the student have phone number information?",
            "choices": [
                {"id": "c1", "label": "Has info", "text": "You can log in using your phone number: {{number}}"},
                {"id": "c2", "label": "Has no info", "text": ""},
            ],
        }
    ],
    "variables": [{"name": "number", "label": "Phone number", "type": "number", "required": True}],
}


def clean(payload):
    template, errors = validate_template(payload)
    assert not errors, errors
    return template


class ParseTests(unittest.TestCase):
    def test_detects_variables_in_order_without_duplicates(self):
        tokens, issues = engine.parse("Hi {{name}}, {{ course }} starts. Bye {{name}}")
        self.assertEqual(issues, [])
        self.assertEqual(engine.var_names(tokens), ["name", "course"])

    def test_unicode_names_are_allowed(self):
        self.assertEqual(engine.names_in("سلام {{نام}}"), ["نام"])

    def test_adjacent_variables(self):
        tokens, issues = engine.parse("{{a}}{{b}}")
        self.assertEqual(issues, [])
        self.assertEqual(engine.var_names(tokens), ["a", "b"])

    def test_malformed_placeholders(self):
        for text, code in [
            ("Hi {{student name}}", "var_malformed"),
            ("Hi {{}}", "var_malformed"),
            ("Hi {{1abc}}", "var_malformed"),
            ("Hi {{name-x}}", "var_malformed"),
            ("Hi {{{name}}}", "var_malformed"),
            ("Hi {{name", "var_unclosed"),
            ("Hi name}}", "var_stray"),
            ("Hi {{name\n}}", "var_unclosed"),
        ]:
            with self.subTest(text=text):
                _, issues = engine.parse(text)
                self.assertEqual([i["code"] for i in issues][:1], [code])

    def test_single_braces_are_plain_text(self):
        tokens, issues = engine.parse("Use {curly} braces")
        self.assertEqual(issues, [])
        self.assertEqual(engine.var_names(tokens), [])


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.panel = clean(PANEL_LOGIN)

    def test_has_info_requires_and_inserts_phone(self):
        result = engine.render(self.panel, {"s1": "c1"}, {})
        self.assertFalse(result["ok"])
        self.assertIsNone(result["text"])
        self.assertEqual(result["errors"][0]["field"], "var:number")
        self.assertEqual(result["errors"][0]["code"], "value_required")

        result = engine.render(self.panel, {"s1": "c1"}, {"number": " 09129876543 "})
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["text"],
            "Please log in to our panel using this URL: panel.example.com.\n"
            "You can log in using your phone number: 09129876543",
        )

    def test_has_no_info_needs_no_phone(self):
        result = engine.render(self.panel, {"s1": "c2"}, {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "Please log in to our panel using this URL: panel.example.com.")
        self.assertEqual(result["needed"], [])

    def test_unanswered_section_adds_nothing(self):
        result = engine.render(self.panel, {}, {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "Please log in to our panel using this URL: panel.example.com.")
        self.assertEqual(result["needed"], [])
        self.assertTrue(engine.render(self.panel, {"s1": ""}, {})["ok"])

    def test_old_default_choice_is_ignored(self):
        old = dict(self.panel, sections=[{**self.panel["sections"][0], "default_choice": "c1"}])
        result = engine.render(old, {}, {})
        self.assertEqual(result["text"], "Please log in to our panel using this URL: panel.example.com.")

    def test_unknown_choice_is_rejected(self):
        result = engine.render(self.panel, {"s1": "nope"}, {})
        self.assertEqual(result["errors"][0]["code"], "choice_invalid")

    def test_repeated_variable_uses_one_value(self):
        template = clean({"title": "t", "body": "Hi {{name}}! Bye {{name}}.", "closing": "— {{name}}"})
        result = engine.render(template, {}, {"name": "Sara"})
        self.assertEqual(result["text"], "Hi Sara! Bye Sara.\n— Sara")
        self.assertEqual(result["needed"], ["name"])

    def test_values_are_inserted_literally(self):
        template = clean({"title": "t", "body": "A {{x}} B"})
        for value in ["<b>hi</b>", "{0} %s ${x} {% if %}", "__import__('os')"]:
            with self.subTest(value=value):
                self.assertEqual(engine.render(template, {}, {"x": value})["text"], f"A {value} B")

    def test_values_with_placeholder_braces_are_rejected(self):
        template = clean({"title": "t", "body": "A {{x}} B"})
        result = engine.render(template, {}, {"x": "{{y}}"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "value_braces")

    def test_number_validation_keeps_value_as_typed(self):
        template = clean({"title": "t", "body": "N {{n}}", "variables": [{"name": "n", "type": "number"}]})
        for good in ["09121234567", "+98 912 123 4567", "7.5", "۰۹۱۲۱۲۳۴۵۶۷", "0912-123-4567"]:
            with self.subTest(good=good):
                result = engine.render(template, {}, {"n": good})
                self.assertTrue(result["ok"], result["errors"])
                self.assertEqual(result["text"], f"N {good}")
        for bad in ["abc", "12a", "1..2"]:
            with self.subTest(bad=bad):
                self.assertEqual(engine.render(template, {}, {"n": bad})["errors"][0]["code"], "value_number")

    def test_optional_value_may_be_empty(self):
        template = clean({"title": "t", "body": "Hi {{name}}", "variables": [{"name": "name", "required": False}]})
        result = engine.render(template, {}, {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "Hi")

    def test_multiline_values_keep_newlines_single_line_values_do_not(self):
        template = clean({
            "title": "t", "body": "{{a}}|{{b}}",
            "variables": [{"name": "a", "type": "multiline"}, {"name": "b", "type": "text"}],
        })
        result = engine.render(template, {}, {"a": "x\r\ny", "b": "p\nq"})
        self.assertEqual(result["text"], "x\ny|p q")

    def test_non_string_values(self):
        template = clean({"title": "t", "body": "{{a}}"})
        self.assertEqual(engine.render(template, {}, {"a": 42})["text"], "42")
        self.assertEqual(engine.render(template, {}, {"a": ["x"]})["errors"][0]["code"], "value_invalid")
        self.assertEqual(engine.render(template, {}, {"a": True})["errors"][0]["code"], "value_invalid")

    def test_output_never_contains_placeholders(self):
        result = engine.render(self.panel, {"s1": "c1"}, {"number": "0912"})
        self.assertNotIn("{{", result["text"])
        self.assertNotIn("}}", result["text"])

    def test_broken_stored_template_never_renders(self):
        broken = dict(self.panel, body="Hi {{name")
        result = engine.render(broken, {"s1": "c2"}, {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "template_broken")

    def test_segments_mark_missing_values(self):
        result = engine.render(self.panel, {"s1": "c1"}, {}, label_for=lambda n: n.upper())
        var = [s for s in result["segments"] if s["t"] == "var"][0]
        self.assertEqual(var["name"], "number")
        self.assertFalse(var["filled"])
        self.assertEqual(var["label"], "Phone number")

    def test_multiple_sections_in_order(self):
        template = clean({
            "title": "t", "body": "Main", "closing": "End",
            "sections": [
                {"id": "a", "question": "Q1", "choices": [{"id": "x", "label": "X", "text": "one {{v}}"}, {"id": "y", "label": "Y", "text": ""}]},
                {"id": "b", "question": "Q2", "choices": [{"id": "x", "label": "X", "text": "two {{v}}"}, {"id": "y", "label": "Y", "text": "three"}]},
            ],
        })
        result = engine.render(template, {"a": "x", "b": "x"}, {"v": "V"})
        self.assertEqual(result["text"], "Main\none V\ntwo V\nEnd")
        result = engine.render(template, {"a": "y", "b": "y"}, {})
        self.assertEqual(result["text"], "Main\nthree\nEnd")
        result = engine.render(template, {"b": "x"}, {"v": "V"})
        self.assertEqual(result["text"], "Main\ntwo V\nEnd")

    def test_blank_lines_inside_a_text_are_kept(self):
        template = clean({"title": "t", "body": "Line 1\n\nLine 2", "closing": "Bye"})
        self.assertEqual(engine.render(template, {}, {})["text"], "Line 1\n\nLine 2\nBye")


class FormTests(unittest.TestCase):
    def test_form_layout_follows_message_order(self):
        template = clean({
            "title": "t", "body": "Hi {{name}}", "closing": "{{sign}} {{name}}",
            "sections": [{"id": "s1", "question": "Q", "choices": [
                {"id": "c1", "label": "A", "text": "{{phone}} {{name}}"}, {"id": "c2", "label": "B", "text": ""}]}],
        })
        form = engine.build_form(template, lambda n: n)
        self.assertEqual(form["layout"], [
            {"kind": "var", "name": "name"},
            {"kind": "section", "id": "s1", "vars": ["phone"]},
            {"kind": "var", "name": "sign"},
        ])
        self.assertEqual(form["always"], ["name", "sign"])
        self.assertEqual(form["choice_vars"], {"s1": {"c1": ["phone", "name"], "c2": []}})


class ValidationTests(unittest.TestCase):
    def codes(self, payload):
        return {(e["field"], e["code"]) for e in validate_template(payload)[1]}

    def test_title_and_body_required(self):
        self.assertEqual(self.codes({"title": "  ", "body": ""}), {("title", "title_required"), ("body", "body_required")})

    def test_not_an_object(self):
        self.assertEqual(self.codes(["x"]), {("_", "bad_request")})

    def test_too_long(self):
        self.assertIn(("title", "too_long"), self.codes({"title": "x" * 200, "body": "b"}))

    def test_malformed_variable_reported_on_its_field(self):
        codes = self.codes({"title": "t", "body": "ok", "sections": [{"question": "Q", "choices": [
            {"label": "A", "text": "{{bad name}}"}, {"label": "B", "text": ""}]}]})
        self.assertIn(("sections.0.choices.0.text", "var_malformed"), codes)

    def test_case_conflict(self):
        self.assertIn(("variables", "var_case_conflict"), self.codes({"title": "t", "body": "{{Name}} {{name}}"}))

    def test_duplicate_and_invalid_definitions(self):
        codes = self.codes({"title": "t", "body": "{{a}}", "variables": [
            {"name": "a"}, {"name": "a"}, {"name": "bad name"}, {"name": "a2", "type": "date"}]})
        self.assertIn(("variables", "var_def_duplicate"), codes)
        self.assertIn(("variables", "var_def_invalid"), codes)
        self.assertIn(("variables.a2.type", "var_type_invalid"), codes)

    def test_section_rules(self):
        codes = self.codes({"title": "t", "body": "b", "sections": [
            {"question": "", "choices": [{"label": "A"}]},
            {"question": "Q", "choices": [{"label": "Same"}, {"label": "same"}]},
        ]})
        self.assertIn(("sections.0.question", "question_required"), codes)
        self.assertIn(("sections.0.choices", "choices_min"), codes)
        self.assertIn(("sections.1.choices.1.label", "choice_label_duplicate"), codes)

    def test_old_default_choice_is_dropped(self):
        template = clean({"title": "t", "body": "b", "sections": [
            {"question": "Q", "default_choice": "c1", "choices": [{"label": "A"}, {"label": "B"}]}]})
        self.assertNotIn("default_choice", template["sections"][0])

    def test_variables_follow_text_and_unused_definitions_are_dropped(self):
        template = clean({"title": "t", "body": "{{b}} {{a}}", "variables": [
            {"name": "a", "label": "Alpha", "type": "number"}, {"name": "gone"}]})
        self.assertEqual([v["name"] for v in template["variables"]], ["b", "a"])
        self.assertEqual(template["variables"][1]["label"], "Alpha")
        self.assertEqual(template["variables"][0], engine.default_variable("b"))

    def test_ids_are_assigned_when_missing(self):
        template = clean({"title": "t", "body": "b", "sections": [{"question": "Q", "choices": [{"label": "A"}, {"label": "B"}]}]})
        self.assertEqual(template["sections"][0]["id"], "s1")
        self.assertEqual([c["id"] for c in template["sections"][0]["choices"]], ["c1", "c2"])


class LabelTests(unittest.TestCase):
    def test_english_labels(self):
        self.assertEqual(i18n.auto_label("user_name", "en"), "User name")
        self.assertEqual(i18n.auto_label("studentName", "en"), "Student name")
        self.assertEqual(i18n.auto_label("class_url", "en"), "Class URL")
        self.assertEqual(i18n.auto_label("id", "en"), "ID")

    def test_persian_labels(self):
        self.assertEqual(i18n.auto_label("user_name", "fa"), "نام کاربر")
        self.assertEqual(i18n.auto_label("student_name", "fa"), "نام زبان‌آموز")
        self.assertEqual(i18n.auto_label("phone_number", "fa"), "شماره تلفن")
        self.assertEqual(i18n.auto_label("exam_start_time", "fa"), "ساعت شروع آزمون")

    def test_unknown_words_fall_back_to_english(self):
        self.assertEqual(i18n.auto_label("zebra_name", "fa"), "Zebra name")

    def test_persian_names_are_kept(self):
        self.assertEqual(i18n.auto_label("شماره_تلفن", "fa"), "شماره تلفن")

    def test_both_languages_define_the_same_keys(self):
        self.assertEqual(set(i18n.STRINGS["en"]), set(i18n.STRINGS["fa"]))

    def test_error_messages_fill_params(self):
        self.assertEqual(i18n.error_message("too_long", {"max": 120}, "en"), "Keep this under 120 characters.")
        self.assertIn("۱۲۰", i18n.error_message("too_long", {"max": 120}, "fa"))
        self.assertIn("{{name}} and {{Name}}", i18n.error_message("var_case_conflict", {"a": "name", "b": "Name"}, "en"))


if __name__ == "__main__":
    unittest.main()
