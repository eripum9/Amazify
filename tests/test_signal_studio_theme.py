from pathlib import Path


THEME_CSS = (
    Path(__file__).parents[1]
    / "sample_plugins"
    / "amazify.theme.signal-studio"
    / "theme.css"
).read_text(encoding="utf-8")


def test_ambience_uses_legacy_position_properties_and_visible_root_layers():
    ambience_start = THEME_CSS.index(
        "body.amazify-signal-studio .signal-studio-ambience {"
    )
    ambience_end = THEME_CSS.index("\n}", ambience_start)
    ambience = THEME_CSS[ambience_start:ambience_end]
    assert "top: 0;" in ambience
    assert "right: 0;" in ambience
    assert "bottom: 0;" in ambience
    assert "left: var(--signal-rail-width);" in ambience
    assert "inset:" not in ambience
    assert "background: transparent !important;" in THEME_CSS


def test_nested_carousel_buttons_do_not_capture_outer_control_clicks():
    selector = (
        ".controlContainer > .prevButton > button,\n"
        "body.amazify-signal-studio:not(.amazify-true-big-mode-active) "
        "#main-content .controlContainer > .nextButton > button"
    )
    assert selector in THEME_CSS
    rule_start = THEME_CSS.index(selector)
    rule_end = THEME_CSS.index("\n}", rule_start)
    assert "pointer-events: none !important;" in THEME_CSS[rule_start:rule_end]


def test_carousel_viewport_preserves_native_scroll_overflow():
    selector = (
        "body.amazify-signal-studio:not(.amazify-true-big-mode-active) "
        "#main-content .pageContainer {"
    )
    rule_start = THEME_CSS.index(selector)
    rule_end = THEME_CSS.index("\n}", rule_start)
    rule = THEME_CSS[rule_start:rule_end]
    assert "padding: 0 4px 6px !important;" in rule
    # Both visible and clip prevent the native scrollLeft assignment from paging.
    assert "overflow" not in rule


def test_fixed_listing_header_is_offset_past_navigation_rail():
    selector = (
        "#main-content .miniHeaderContainer {\n"
        "  right: 0 !important;\n"
        "  left: var(--signal-rail-width) !important;\n"
        "  width: auto !important;"
    )
    assert selector in THEME_CSS
    compact_reset = (
        "#main-content .miniHeaderContainer {\n"
        "    left: 0 !important;"
    )
    assert compact_reset in THEME_CSS


def test_theme_does_not_use_unsupported_modern_css_or_js_syntax():
    assert ":is(" not in THEME_CSS
    plugin_js = (
        Path(__file__).parents[1]
        / "sample_plugins"
        / "amazify.theme.signal-studio"
        / "plugin.js"
    ).read_text(encoding="utf-8")
    assert "?." not in plugin_js
