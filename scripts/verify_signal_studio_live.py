"""Probe Signal Studio layout and exercise non-playback carousel controls over CDP.

The script never starts Amazify, navigates routes, or touches transport controls.
Run it against an already-open Amazon Music window, for example:

    python scripts/verify_signal_studio_live.py --port 58963 --output .playwright-mcp/signal-qa

Use --preview-scroll-fix to temporarily remove the installed theme's carousel
overflow override. The CSS and carousel position are restored after the probe.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amazify.devtools import DevToolsClient, DevToolsHttp


METRICS = r"""
JSON.stringify((function () {
  var visible = function (element) {
    if (!element) return false;
    var rect = element.getBoundingClientRect();
    var style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== "none" && style.visibility !== "hidden";
  };
  var rectOf = function (element) {
    if (!element) return null;
    var rect = element.getBoundingClientRect();
    return {
      left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
      width: rect.width, height: rect.height
    };
  };
  var signature = function (section) {
    if (!section) return [];
    return Array.prototype.slice.call(section.querySelectorAll(
      ".verticalTile .title, .horizontalTile .title, img.artImage"
    )).slice(0, 16).map(function (element) {
      var value = element.tagName === "IMG" ? (element.currentSrc || element.src || "") : (element.innerText || element.textContent || "").trim();
      return {value: value, left: element.getBoundingClientRect().left};
    });
  };
  var controls = Array.prototype.slice.call(document.querySelectorAll(
    "#main-content .controlContainer > .prevButton, " +
    "#main-content .controlContainer > .nextButton"
  )).filter(visible).filter(function (element) {
    var rect = element.getBoundingClientRect();
    return rect.top < window.innerHeight && rect.bottom > 0;
  });
  var headings = Array.prototype.slice.call(document.querySelectorAll(
    "#main-content h1, #main-content h2, #main-content h3, #main-content h4, " +
    "#main-content .headline_1, #main-content .headline_2, " +
    "#main-content .headline_3, #main-content .headline_4, " +
    "#main-content .miniHeaderContainer .name"
  )).filter(visible).slice(0, 24);
  var main = document.querySelector("#main-content");
  var rail = document.querySelector("#appchrome");
  var ambience = document.querySelector(".signal-studio-ambience");
  var root = document.querySelector("#caterpillar, #root, #app");
  return {
    href: location.href,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    rail: rectOf(rail),
    main: rectOf(main),
    ambience: ambience ? {
      rect: rectOf(ambience),
      background: getComputedStyle(ambience).backgroundColor,
      image: getComputedStyle(ambience).backgroundImage
    } : null,
    root: root ? {
      id: root.id,
      background: getComputedStyle(root).backgroundColor
    } : null,
    controls: controls.map(function (element) {
      var rect = element.getBoundingClientRect();
      var hit = document.elementFromPoint(
        (rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2
      );
      var section = element.closest("section.container");
      var page = section && section.querySelector(".pageContainer");
      var vue = section && section.__vue__;
      return {
        sectionIndex: Array.prototype.indexOf.call(
          document.querySelectorAll("#main-content section.container"), section
        ),
        direction: element.classList.contains("nextButton") ? "next" : "previous",
        title: section ? ((section.querySelector(".sectionHeader .title") || {}).innerText || "").trim() : "",
        rect: rectOf(element),
        disabled: !!element.disabled,
        hit: hit ? { tag: hit.tagName, className: String(hit.className || "") } : null,
        carousel: page ? {
          scrollLeft: page.scrollLeft,
          scrollWidth: page.scrollWidth,
          clientWidth: page.clientWidth,
          overflowX: getComputedStyle(page).overflowX,
          currentPage: vue ? vue.currentPage : null,
          scrollTarget: vue ? vue.scrollLeft : null
        } : null,
        signature: signature(section)
      };
    }),
    headings: headings.map(function (element) {
      return {
        text: (element.innerText || element.textContent || "").trim().slice(0, 120),
        rect: rectOf(element)
      };
    })
  };
})())
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=58963)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview-scroll-fix", action="store_true")
    return parser.parse_args()


def capture(client: DevToolsClient, path: Path) -> None:
    result = client.call("Page.captureScreenshot", {"format": "png"})
    path.write_bytes(base64.b64decode(result["data"]))


def click_at(client: DevToolsClient, point: dict[str, float]) -> None:
    for event_type in ("mousePressed", "mouseReleased"):
        client.call(
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": point["x"],
                "y": point["y"],
                "button": "left",
                "clickCount": 1,
            },
        )


def first_visible_next(client: DevToolsClient) -> dict[str, float] | None:
    value = client.evaluate(
        r"""
        (function () {
          var buttons = Array.prototype.slice.call(document.querySelectorAll(
            "#main-content .controlContainer > .nextButton"
          ));
          for (var index = 0; index < buttons.length; index += 1) {
            var button = buttons[index];
            var rect = button.getBoundingClientRect();
            var style = getComputedStyle(button);
            if (rect.width > 0 && rect.height > 0 && rect.top < innerHeight &&
                rect.bottom > 0 && style.display !== "none" &&
                style.visibility !== "hidden" && !button.disabled) {
              return {
                x: (rect.left + rect.right) / 2, y: (rect.top + rect.bottom) / 2,
                sectionIndex: Array.prototype.indexOf.call(
                  document.querySelectorAll("#main-content section.container"),
                  button.closest("section.container")
                )
              };
            }
          }
          return null;
        })()
        """.strip()
    )
    return value if isinstance(value, dict) else None


THEME_RULE = r"""
Array.prototype.slice.call(document.querySelectorAll("style")).filter(function (s) {
  return s.getAttribute("data-amazify-style-id") === "amazify.theme.signal-studio";
}).reduce(function (result, s) {
  return result || Array.prototype.slice.call(s.sheet.cssRules).filter(function (r) {
    return r.selectorText === "body.amazify-signal-studio:not(.amazify-true-big-mode-active) #main-content .pageContainer";
  })[0];
}, null)
""".strip()


def matching_control(metrics: dict[str, Any], section_index: int) -> dict[str, Any]:
    return next(
        control for control in metrics["controls"]
        if control["sectionIndex"] == section_index and control["direction"] == "next"
    )


def previous_point(client: DevToolsClient, section_index: int) -> dict[str, float]:
    return client.evaluate(
        "(function () { var s = document.querySelectorAll("
        "'#main-content section.container')[" + str(section_index) + "];"
        "var r = s.querySelector('.controlContainer > .prevButton').getBoundingClientRect();"
        "return {x: (r.left + r.right) / 2, y: (r.top + r.bottom) / 2}; })()"
    )


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    target = DevToolsHttp(args.port).wait_for_amazon_music_target(8)
    client = DevToolsClient(target)
    client.connect()
    original_rule: str | None = None
    pending_previous: int | None = None
    try:
        if args.preview_scroll_fix:
            original_rule = client.evaluate(
                "(function () { var rule = " + THEME_RULE + ";"
                "if (!rule) throw new Error('Signal Studio carousel rule not found');"
                "var original = rule.style.cssText; rule.style.removeProperty('overflow');"
                "return original; })()"
            )
            time.sleep(0.7)
        before = json.loads(client.evaluate(METRICS))
        (args.output / "before.json").write_text(
            json.dumps(before, indent=2), encoding="utf-8"
        )
        capture(client, args.output / "before.png")

        point = first_visible_next(client)
        after: dict[str, Any] | None = None
        after_previous: dict[str, Any] | None = None
        carousel_changed = False
        returned_to_start = False
        if point:
            pending_previous = int(point["sectionIndex"])
            click_at(client, point)
            time.sleep(0.7)
            after = json.loads(client.evaluate(METRICS))
            (args.output / "after-next.json").write_text(
                json.dumps(after, indent=2), encoding="utf-8"
            )
            capture(client, args.output / "after-next.png")
            before_control = matching_control(before, pending_previous)
            after_control = matching_control(after, pending_previous)
            carousel_changed = (
                before_control["carousel"]["scrollLeft"] !=
                after_control["carousel"]["scrollLeft"]
            )
            click_at(client, previous_point(client, pending_previous))
            pending_previous = None
            time.sleep(0.7)
            after_previous = json.loads(client.evaluate(METRICS))
            previous_control = matching_control(after_previous, int(point["sectionIndex"]))
            returned_to_start = (
                before_control["carousel"]["scrollLeft"] ==
                previous_control["carousel"]["scrollLeft"]
            )
            (args.output / "after-previous.json").write_text(
                json.dumps(after_previous, indent=2), encoding="utf-8"
            )

        report = {
            "target": {"title": target.title, "url": target.url, "port": args.port},
            "clickedNext": point is not None,
            "previewScrollFix": args.preview_scroll_fix,
            "carouselChanged": carousel_changed,
            "returnedToStart": returned_to_start,
            "before": before,
            "after": after,
            "afterPrevious": after_previous,
        }
        (args.output / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps({
            "href": before.get("href"),
            "clickedNext": report["clickedNext"],
            "carouselChanged": report["carouselChanged"],
            "returnedToStart": report["returnedToStart"],
            "output": str(args.output),
        }))
    finally:
        try:
            if pending_previous is not None:
                click_at(client, previous_point(client, pending_previous))
                time.sleep(0.7)
        finally:
            try:
                if original_rule is not None:
                    client.evaluate(
                        "(function () { var rule = " + THEME_RULE + ";"
                        "if (!rule) throw new Error('Cannot restore Signal Studio carousel rule');"
                        "rule.style.cssText = " + json.dumps(original_rule) + "; })()"
                    )
            finally:
                client.close()


if __name__ == "__main__":
    main()
