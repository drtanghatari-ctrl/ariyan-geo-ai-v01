"""kb-v1 (2026-10-20): ANE names that are already bracketed are not wrapped
a second time in the "not in gazetteer" text (app list, detail, report)."""
import known_sites as ks
import grand_project_report as rpt


def test_bracketed_helper():
    assert ks.bracketed("(Teppe Farukhabad)") == "(Teppe Farukhabad)"
    assert ks.bracketed("Susa") == "(Susa)"
    assert ks.bracketed("Adab (Bismaya)") == "(Adab (Bismaya))"
    assert rpt._bracketed("(Teppe Bowla)") == "(Teppe Bowla)"
    assert rpt._bracketed("Susa") == "(Susa)"


def test_live_annotation_has_no_double_brackets():
    # Real gazetteer, real point (#18 a50df34d, Deh Luran); nearest is the
    # bracketed ANE name "(Teppe Farukhabad)".
    a = ks.annotate(32.594668, 47.232620)
    assert a["nearest_name"] == "(Teppe Farukhabad)"
    assert "((" not in a["text"] and "))" not in a["text"]
    assert a["text"].endswith("(Teppe Farukhabad)")
    for exact in (False, True):
        r = rpt._known_site(32.594668, 47.232620, exact)
        for txt in (r["text_en"], r["text_fa"]):
            assert "((" not in txt and "))" not in txt
            assert "(Teppe Farukhabad)" in txt
