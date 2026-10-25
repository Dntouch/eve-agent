import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"


class HTMLContractParser(HTMLParser):
    """Collect the small amount of DOM metadata needed by static contracts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.by_id = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        element_id = attributes.get("id")
        if element_id:
            self.by_id[element_id] = (tag, attributes)

    handle_startendtag = handle_starttag


def function_body(source: str, *names: str) -> str:
    """Return a named function body without depending on formatting/minification."""

    alternatives = "|".join(re.escape(name) for name in names)
    declarations = (
        rf"(?:async\s+)?function\s+(?:{alternatives})\s*\([^)]*\)\s*\{{",
        rf"(?:const|let|var)\s+(?:{alternatives})\s*=\s*(?:async\s*)?"
        rf"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{{",
    )
    match = next((found for pattern in declarations if (found := re.search(pattern, source))), None)
    if match is None:
        raise AssertionError(f"Keine Funktion {', '.join(names)} gefunden")

    opening_brace = source.find("{", match.start())
    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening_brace
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
        elif block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char == "/" and following == "/":
            line_comment = True
            index += 1
        elif char == "/" and following == "*":
            block_comment = True
            index += 1
        elif char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[opening_brace + 1:index]
        index += 1
    raise AssertionError(f"Funktion {', '.join(names)} hat keinen abgeschlossenen Block")


def compact(source: str) -> str:
    return re.sub(r"\s+", "", source)


def css_declarations(css: str, *selectors: str) -> str:
    """Collect declarations for selectors, independent of rule ordering."""

    wanted = set(selectors)
    declarations = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        rule_selectors = {item.strip() for item in match.group(1).split(",")}
        if rule_selectors & wanted:
            declarations.append(match.group(2))
    return "\n".join(declarations)


class FrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_path = WEB_ROOT / "index.html"
        cls.styles_path = WEB_ROOT / "styles.css"
        cls.app_path = WEB_ROOT / "app.js"
        cls.html = cls.index_path.read_text(encoding="utf-8")
        cls.css = cls.styles_path.read_text(encoding="utf-8") if cls.styles_path.exists() else ""
        cls.js = cls.app_path.read_text(encoding="utf-8") if cls.app_path.exists() else ""
        cls.dom = HTMLContractParser()
        cls.dom.feed(cls.html)

    def element(self, element_id):
        self.assertIn(element_id, self.dom.by_id, f"#{element_id} fehlt")
        return self.dom.by_id[element_id]

    def test_frontend_is_split_into_local_html_css_and_javascript(self):
        self.assertTrue(self.styles_path.is_file(), "web/styles.css fehlt")
        self.assertTrue(self.app_path.is_file(), "web/app.js fehlt")
        self.assertNotRegex(self.html, r"(?is)<style(?:\s|>)")
        self.assertNotRegex(self.html, r"(?is)<script(?![^>]*\bsrc=)[^>]*>\s*\S")

        stylesheets = [
            attrs.get("href", "")
            for tag, attrs in self.dom.elements
            if tag == "link" and "stylesheet" in attrs.get("rel", "").split()
        ]
        scripts = [attrs for tag, attrs in self.dom.elements if tag == "script" and attrs.get("src")]
        self.assertTrue(any(Path(urlsplit(path).path).name == "styles.css" for path in stylesheets))
        app_scripts = [attrs for attrs in scripts if Path(urlsplit(attrs["src"]).path).name == "app.js"]
        self.assertTrue(app_scripts, "index.html lädt app.js nicht")
        self.assertTrue(
            any("defer" in attrs or attrs.get("type") == "module" for attrs in app_scripts),
            "app.js muss defer oder als Modul geladen werden",
        )

    def test_dynamic_semantics_controls_are_wired_to_brainwatch_and_runtime_config(self):
        for text in ('ZUORDNUNG KORREKT', 'ZUORDNUNG FALSCH', 'BEZIEHUNG KORRIGIEREN',
                     'KORREKTUR AUFHEBEN', 'semantic-similarity/relations',
                     'semantic_similarity.threshold', 'ALS KORREKT BESTÄTIGT',
                     'ALS FALSCH MARKIERT', 'BEWERTUNG AUFHEBEN', 'user_decision',
                     'Nur unbewertete', 'Nur bewertete', 'eve.semanticReviewFilter',
                     'semanticFilter.value = status', 'semanticLinkFilter.value = linkStatus',
                     'action_link_status', 'Widersprüchliche Verknüpfung',
                     'Gelernte Formulierungen werden durchsucht',
                     'semanticExperienceHeading.scrollIntoView'):
            self.assertIn(text, self.js)
        for style in ('.semantic-review-verdict', '.semantic-write-action.is-selected:disabled',
                      '.semantic-review-controls', '.semantic-metrics button.is-actionable'):
            self.assertIn(style, self.css)

    def test_home_assistant_area_policy_is_user_visible_and_memory_backed(self):
        for text in (
            "Bereiche bei Sammelaktionen", "REGEL IM MEMORY SPEICHERN",
            "/api/home-assistant/policy", "explicit_area_command_overrides",
        ):
            self.assertIn(text, self.js if text != "explicit_area_command_overrides" else (
                PROJECT_ROOT / "src/eve_agent/home_assistant_memory.py"
            ).read_text(encoding="utf-8"))

    def test_provider_independent_training_packages_can_be_previewed_imported_and_exported(self):
        for text in (
            "Community-Training", "/api/training-packages", "PAKET PRÜFEN",
            "IMPORTIEREN UND VERKNÜPFEN", "PAKET EXPORTIEREN",
            "Provider-Adapter", "keine Provider-Aktion und keinen LLM-Aufruf",
        ):
            self.assertIn(text, self.js)
        for style in (".training-packages", ".training-package-preview"):
            self.assertIn(style, self.css)

    def test_training_package_controls_have_detailed_configuration_help(self):
        body = function_body(self.js, "trainingPackagesSection")
        for help_id in (
            "training_packages.provider", "training_packages.kind", "training_packages.entry",
            "training_packages.refresh", "training_packages.export", "training_packages.file",
            "training_packages.preview", "training_packages.import",
        ):
            self.assertIn(help_id, self.js)
            self.assertIn(help_id, body)
        self.assertIn('className = "config-help-trigger"', body)
        self.assertIn("openConfigHelp(button, { id, hide_facts: true })", body)

    def test_memory_cloud_automatically_pages_all_claims_and_relations(self):
        body = function_body(self.js, "readMemoryStructure")
        self.assertIn("graph/relations?", body)
        self.assertIn("while (true)", body)
        self.assertIn("seenCursors", body)
        self.assertNotIn("memoryCloudCursor = page.page?.next_cursor", body)

    def test_static_document_references_only_existing_local_assets(self):
        self.assertNotRegex(
            self.js,
            r"(?i)(?:import\s*\(|\bfrom\s+|new\s+Worker\s*\()\s*['\"]https?://",
            "Remote JavaScript-Abhängigkeit gefunden",
        )
        references = [
            attrs[name]
            for _, attrs in self.dom.elements
            for name in ("src", "href")
            if attrs.get(name)
        ]
        references += [
            value.strip().strip("'\"")
            for value in re.findall(r"url\(([^)]+)\)", self.css, flags=re.I)
        ]
        self.assertTrue(any("eve-logo" in reference for reference in references))
        for reference in references:
            parsed = urlsplit(reference)
            with self.subTest(reference=reference):
                self.assertFalse(parsed.scheme or parsed.netloc or reference.startswith("//"))
                if not parsed.path or parsed.path == "/" or reference.startswith("#"):
                    continue
                target = WEB_ROOT / parsed.path.lstrip("/")
                self.assertTrue(target.is_file(), f"Lokales Asset fehlt: {reference}")
        self.assertNotRegex(self.css, r"(?i)@import\s")

        manifest = json.loads((WEB_ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
        for icon in manifest.get("icons", []):
            source = str(icon.get("src", ""))
            self.assertFalse(urlsplit(source).scheme or urlsplit(source).netloc)
            self.assertTrue((WEB_ROOT / urlsplit(source).path.lstrip("/")).is_file())

    def test_functional_dom_hooks_are_preserved(self):
        expected = {
            "neural", "mark", "label", "ptt", "detail", "reply", "downloads", "sources",
            "shareToggle", "composer", "messageText", "dropzone", "imageInput", "previews",
            "composerActivity", "composerActivityText",
            "workspaceResize", "panelResize",
            "sendMessage", "conversationPanel", "conversationList", "newConversation",
            "conversationTitle", "chatMessages", "chatEmpty", "renameConversation", "deleteConversation",
            "voiceMute",
            "scheduleViewToggle", "scheduledTaskView", "taskViewToggle", "taskList", "taskListEmpty",
        }
        self.assertEqual(set(self.dom.by_id) & expected, expected)
        self.assertEqual(self.element("neural")[0], "canvas")
        for button_id in ("ptt", "shareToggle", "sendMessage", "voiceMute"):
            tag, attrs = self.element(button_id)
            self.assertEqual(tag, "button")
            self.assertEqual(attrs.get("type"), "button")
        self.assertEqual(self.element("messageText")[0], "textarea")
        chat_actions = re.search(
            r'(?s)<div class="chat-actions">(.*?)</div>', self.html,
        ).group(1)
        panel_actions = re.search(
            r'(?s)<div class="panel-head-actions">(.*?)</div>', self.html,
        ).group(1)
        self.assertIn('id="newConversation"', chat_actions)
        self.assertNotIn('id="newConversation"', panel_actions)
        self.assertLess(
            chat_actions.index('id="newConversation"'),
            chat_actions.index('id="renameConversation"'),
        )
        delete_button = re.search(
            r'(?s)<button id="deleteConversation".*?</button>', chat_actions,
        ).group(0)
        self.assertIn('class="chat-action-icon"', delete_button)
        self.assertIn("<svg", delete_button)
        self.assertNotIn("LÖSCHEN", delete_button)
        _, image_input = self.element("imageInput")
        self.assertEqual(image_input.get("type"), "file")
        accepted_images = {item.strip() for item in image_input.get("accept", "").split(",")}
        self.assertTrue(
            accepted_images == {"image/*"}
            or {"image/png", "image/jpeg", "image/gif", "image/webp"} <= accepted_images
        )
        self.assertIn("multiple", image_input)

    def test_chat_uses_shared_visual_system_without_changing_dom_hooks(self):
        self.assertRegex(
            self.html,
            r'<div class="chat-workspace">\s*<div class="panel-resize"[^>]*>.*?</div>\s*<section class="conversation"',
        )

        expected_classes = {
            "messageText": "eve-input",
            "sendMessage": "eve-button--primary",
            "ptt": "eve-button",
            "voiceMute": "eve-icon-button",
            "shareToggle": "eve-icon-button",
        }
        for element_id, class_name in expected_classes.items():
            _, attrs = self.element(element_id)
            with self.subTest(element_id=element_id):
                self.assertIn(class_name, attrs.get("class", "").split())

        self.assertIn("EVE Chat Visual Refresh V1", self.css)
        for selector in (
            ".chat-message.assistant:last-of-type .message-content",
            'body[data-state="thinking"] .composer',
            ".assistant-markdown table",
            ".message-source-links a",
            ".command-dock",
        ):
            self.assertIn(selector, self.css)
        refresh = self.css[self.css.index("EVE Chat Visual Refresh V1"):]
        self.assertIn("var(--eve-accent", refresh)
        self.assertIn("@media (max-width: 899px)", refresh)

    def test_open_chat_repositions_presence_without_dimming_it(self):
        blocks = re.findall(r"body\.chat-open\s+\.presence\s*\{([^}]*)\}", self.css)
        self.assertTrue(blocks)
        self.assertTrue(all("opacity:" not in block for block in blocks))
        self.assertTrue(all("filter:" not in block for block in blocks))
        self.assertTrue(any("transform:" in block for block in blocks))

    def test_nerd_view_exposes_parallel_post_turn_timing(self):
        for label in (
            "Presentation Start", "TTS Start", "P/T-Überlappung",
            "Presentation fertig", "Audio fertig", "Turn vollständig",
        ):
            self.assertIn(f'"{label}"', self.js)

    def test_live_content_and_controls_have_accessible_semantics(self):
        html_elements = [attrs for tag, attrs in self.dom.elements if tag == "html"]
        self.assertTrue(html_elements and html_elements[0].get("lang", "").startswith("de"))
        self.assertEqual(self.element("neural")[1].get("aria-hidden"), "true")

        for element_id in ("label", "detail", "reply"):
            _, attrs = self.element(element_id)
            announced = attrs.get("aria-live") in {"polite", "assertive"} or attrs.get("role") in {
                "status", "alert", "log",
            }
            self.assertTrue(announced, f"#{element_id} ist keine Live-Region")

        _, ptt = self.element("ptt")
        self.assertIn("aria-label", ptt)
        _, voice_mute = self.element("voiceMute")
        self.assertEqual(voice_mute.get("aria-pressed"), "false")
        _, share_toggle = self.element("shareToggle")
        self.assertEqual(set(share_toggle.get("aria-controls", "").split()), {"conversation", "composer"})
        self.assertEqual(share_toggle.get("aria-expanded"), "false")
        self.assertEqual(share_toggle.get("aria-label"), "Seitenbereich öffnen")
        _, composer = self.element("composer")
        self.assertTrue(composer.get("aria-label") or composer.get("aria-labelledby"))

        drop_tag, dropzone = self.element("dropzone")
        keyboard_accessible = drop_tag in {"button", "label"} or (
            dropzone.get("role") == "button" and dropzone.get("tabindex") == "0"
        )
        self.assertTrue(keyboard_accessible, "Screenshot-Dropzone ist nicht per Tastatur bedienbar")
        images = [attrs for tag, attrs in self.dom.elements if tag == "img"]
        self.assertTrue(images)
        self.assertTrue(all("alt" in image for image in images))
        self.assertTrue(any(image.get("alt") for image in images), "Das sichtbare EVE-Logo hat keinen Alt-Text")

    def test_mobile_chat_uses_one_flowing_workspace(self):
        self.assertRegex(
            self.html,
            r'<div class="chat-workspace">\s*<div class="panel-resize"[^>]*>.*?</div>\s*<section class="conversation"',
        )
        workspace = self.html.split('<div class="chat-workspace">', 1)[1].split('</div>\n\n  <footer', 1)[0]
        self.assertLess(workspace.index('id="conversation"'), workspace.index('id="composer"'))
        self.assertIn('<details class="artifact-tray">', workspace)
        self.assertIn('document.createElement("details")', self.js)
        self.assertIn("resizeMessageInput", self.js)
        self.assertNotIn("elements.composer.style.maxHeight", self.js)
        self.assertRegex(self.css, r"\.chat-workspace\s*\{[^}]*display:\s*flex")
        self.assertRegex(self.css, r"\.chat-messages\s*\{[^}]*overflow-y:\s*auto")
        self.assertNotRegex(self.css, r"body\.chat-open\s+\.share-toggle\s*\{[^}]*display:\s*none")
        self.assertRegex(self.css, r"\.chat-head\s*>\s*div:first-child\s*\{[^}]*min-width:\s*0")
        self.assertRegex(
            self.css,
            r"@media\s*\(min-width:\s*900px\)[\s\S]*?\.chat-workspace\s*\{[\s\S]*?flex-direction:\s*column",
        )
        self.assertRegex(self.css, r"\.chat-workspace\s+\.conversation\s*\{[^}]*flex:\s*1\s+1\s+0")
        self.assertRegex(self.css, r"\.command-dock\s+\.voice-mute\s*\{[^}]*position:\s*static")

    def test_chat_integrates_voice_input_and_keeps_mobile_return_multiline(self):
        slot = self.element("composerVoiceSlot")
        dock = self.element("commandDock")
        self.assertEqual("div", slot[0])
        self.assertEqual("footer", dock[0])
        self.assertEqual(1, len(re.findall(r'id="ptt"', self.html)))
        sync = function_body(self.js, "syncIntegratedChatControls")
        self.assertIn("if (chatOpen)", sync)
        self.assertIn("elements.composerVoiceSlot", sync)
        self.assertIn("elements.chatActions.append(elements.voiceMute)", sync)
        self.assertIn("elements.chatActions.append(elements.shareToggle)", sync)
        self.assertIn("elements.commandDock.append(elements.voiceMute, elements.ptt, elements.shareToggle)", sync)
        self.assertIn("syncIntegratedChatControls()", function_body(self.js, "setChatOpen"))
        resize = function_body(self.js, "resizeMessageInput")
        self.assertIn("const minimum = 40", resize)
        self.assertIn('!event.isComposing && !mobileChatQuery.matches', self.js)
        self.assertRegex(
            self.css,
            r"@media \(max-width: 899px\)[\s\S]*?\.composer-voice-slot \.ptt\s*\{[^}]*width:\s*38px[^}]*height:\s*40px",
        )
        self.assertRegex(
            self.css,
            r"body\.chat-open \.command-dock\s*\{[^}]*display:\s*none",
        )
        self.assertRegex(
            self.css,
            r"\.chat-head\s*\{[^}]*min-height:\s*44px[^}]*height:\s*44px",
        )
        self.assertRegex(
            self.css,
            r"@media \(min-width: 900px\)[\s\S]*?\.composer-voice-slot \.ptt\s*\{[^}]*width:\s*42px[^}]*height:\s*46px",
        )

    def test_voice_and_workspace_controls_are_icon_only_in_command_dock(self):
        dock = self.html.split('<footer class="command-dock"', 1)[1].split('</footer>', 1)[0]
        self.assertLess(dock.index('id="voiceMute"'), dock.index('id="ptt"'))
        self.assertLess(dock.index('id="ptt"'), dock.index('id="shareToggle"'))
        self.assertNotIn('id="voiceMuteText"', dock)
        self.assertIn('class="panel-toggle-icon"', dock)
        self.assertIn('class="panel-open-mark"', dock)
        self.assertIn('class="panel-close-mark"', dock)
        self.assertNotIn('<span>CHAT</span>', self.html)
        self.assertNotIn('class="share-plus"', self.html)
        self.assertNotIn('id="closeChat"', self.html)
        chat_state = function_body(self.js, "setChatOpen")
        self.assertIn('chatOpen ? "Seitenbereich schließen" : "Seitenbereich öffnen"', chat_state)
        self.assertIn('elements.shareToggle.title = chatOpen ?', chat_state)
        self.assertRegex(
            self.css,
            r'\.share-toggle\[aria-expanded="true"\]\s+\.panel-open-mark\s*\{[^}]*opacity:\s*0',
        )
        self.assertRegex(
            self.css,
            r'\.share-toggle\[aria-expanded="true"\]\s+\.panel-close-mark\s*\{[^}]*opacity:\s*1',
        )
        self.assertRegex(self.css, r"\.panel-close-mark\s*\{[^}]*transition:")
        self.assertRegex(
            self.css,
            r"\.command-dock \.voice-mute,\s*\.command-dock \.share-toggle\s*\{[^}]*align-self:\s*stretch[^}]*min-height:\s*57px",
        )

    def test_composer_restores_only_requests_rejected_before_backend_acceptance(self):
        self.assertIn('elements.messageText.value = ""', self.js)
        self.assertIn("submittedText.replace", self.js)
        self.assertIn(": submittedText;", self.js)
        self.assertIn("attachedImages = submittedImages", self.js)
        self.assertIn("let backendAccepted = false", self.js)
        self.assertIn("backendAccepted = true", self.js)
        self.assertIn("if (!messageAccepted && backendAccepted)", self.js)
        self.assertIn("else if (!messageAccepted)", self.js)
        self.assertIn('optimisticMessage.classList.add("failed")', self.js)
        self.assertIn("updateComposerActivity", self.js)
        self.assertIn("composerActivityLabel", self.js)
        self.assertIn("const minimum = 40", self.js)
        self.assertIn("backendTurnStatusLabel", self.js)
        self.assertIn('running: "EVE arbeitet im Hintergrund …"', self.js)
        self.assertNotIn('setDetail(`EVE arbeitet im Backend … ${event.status}`)', self.js)
        self.assertIn("elements.detail.textContent.trim()", self.js)
        self.assertIn("composer-activity-helix", self.html)
        self.assertIn("@keyframes composer-helix", self.css)
        self.assertNotIn("elements.messageText.disabled = true", self.js)
        self.assertIn('composerActivity.classList.toggle("has-draft"', self.js)
        self.assertRegex(
            self.css,
            r'\.chat-workspace \.composer textarea\[aria-busy="true"\]::placeholder\s*\{[^}]*color:\s*transparent',
        )
        self.assertRegex(
            self.css,
            r"\.chat-workspace \.composer-activity\s*\{[^}]*min-height:\s*40px[^}]*overflow:\s*hidden",
        )
        self.assertRegex(
            self.css,
            r"\.chat-workspace \.composer textarea\.eve-input,[\s\S]*?min-height:\s*40px[^}]*font-size:\s*15px",
        )
        self.assertRegex(
            self.css,
            r"\.chat-workspace \.message-content,[\s\S]*?font-size:\s*15px[^}]*line-height:\s*1\.7",
        )
        self.assertIn("const newDraft = elements.messageText.value", self.js)
        self.assertIn("const queuedMessages = []", self.js)
        self.assertIn("queuedMessages.push(message)", self.js)
        self.assertIn("queuedMessages.shift()", self.js)
        self.assertIn("queuedMessages.splice(index, 1)", self.js)
        self.assertIn('createElementNS("http://www.w3.org/2000/svg", "svg")', self.js)
        self.assertIn('id="messageQueue"', self.html)
        composer = self.html.split('<aside class="composer"', 1)[1].split("</aside>", 1)[0]
        self.assertLess(composer.index('id="messageQueue"'), composer.index('id="messageText"'))
        self.assertIn("renderMessageQueue", self.js)
        self.assertIn(".message-queue-item", self.css)
        self.assertIn("window.setTimeout(() => submitMessage(nextMessage), 0)", self.js)
        self.assertNotIn("requestBusy || audioQueued > 0 || playingAudio", function_body(self.js, "submitMessage"))
        self.assertIn('event.key === "Enter" && !event.shiftKey && !event.isComposing && !mobileChatQuery.matches', self.js)
        self.assertIn("Shift + Return für eine neue Zeile", self.html)
        self.assertIn("@keyframes idle-field-breathe", self.css)
        self.assertIn('class="core-orbit orbit-mid"', self.html)
        self.assertIn("@keyframes mid-breathe", self.css)
        self.assertIn("@keyframes far-breathe", self.css)
        self.assertIn("@keyframes thinking-energy", self.css)
        self.assertIn("@keyframes thinking-near", self.css)
        self.assertIn("thinking: 72", self.js)
        self.assertIn("drawToolField(time, first, second)", self.js)
        self.assertIn('this.stateKind() !== "tool"', self.js)
        self.assertIn("const routeCount = Math.min(10, this.nodes.length)", self.js)
        self.assertIn("ctx.quadraticCurveTo", self.js)
        self.assertIn("for (let trail = 0; trail < 3; trail += 1)", self.js)
        self.assertIn("idle: 50", self.js)
        self.assertIn("thinking: 22.2", self.js)
        self.assertIn("speaking: 33.3", self.js)
        self.assertIn("translate3d(34px, -50%, 0)", self.css)
        self.assertIn("drawSpeakingPresence(time, first, second)", self.js)
        self.assertNotIn("drawSpeakingEgress", self.js)
        self.assertIn("this.speechRipples.push", self.js)
        self.assertIn("now - this.lastSpeechRipple > 320", self.js)
        self.assertIn("@keyframes rail-neuron-pulse", self.css)
        self.assertIn("@keyframes rail-synapse-flare", self.css)
        self.assertRegex(self.css, r"\.composer \.dropzone\s*\{[^}]*align-self:\s*center")
        self.assertRegex(self.css, r"\.composer \.composer-actions\s*\{[^}]*align-self:\s*center")
        self.assertIn('class="send-icon"', self.html)
        self.assertNotIn("<span>AN EVE</span>", self.html)
        _, send = self.element("sendMessage")
        self.assertEqual(send.get("title"), "Nachricht an EVE senden")
        self.assertRegex(self.css, r"\.send-icon\s*\{[^}]*stroke:\s*currentColor")
        self.assertRegex(self.css, r"\.composer \.composer-actions\s*\{[^}]*justify-content:\s*flex-end")
        self.assertRegex(
            self.css,
            r"@media\s*\(min-width:\s*900px\)[\s\S]*?\.composer \.composer-input\s*\{[^}]*grid-column:\s*1[^}]*grid-row:\s*1",
        )
        self.assertRegex(
            self.css,
            r"@media\s*\(min-width:\s*900px\)[\s\S]*?\.composer \.composer-actions\s*\{[^}]*grid-column:\s*2[^}]*grid-row:\s*1[^}]*align-self:\s*start",
        )
        self.assertRegex(self.css, r'body\[data-state="thinking"\] \.rail-separator::before\s*\{[^}]*animation-duration:\s*\.95s')
        self.assertRegex(self.css, r'body\[data-state\^="tool"\] \.rail-separator::before\s*\{[^}]*animation-duration:\s*1\.2s')
        self.assertNotIn("updatePresenceBreath", self.js)

    def test_desktop_chat_workspace_and_history_panel_are_resizable(self):
        self.assertIn("attachHorizontalResize(elements.workspaceResize, historyWidth, setHistoryPanelWidth)", self.js)
        self.assertIn("attachHorizontalResize(elements.panelResize, activeChatWidth, setActiveChatWidth)", self.js)
        self.assertIn('style.setProperty("--chat-total-width"', self.js)
        self.assertIn('style.setProperty("--history-panel-width"', self.js)
        self.assertIn("applyDesktopChatWidths", self.js)
        self.assertIn("elements.conversationPanel.style.width", self.js)
        self.assertIn("elements.chatWorkspace.style.width", self.js)
        self.assertIn("const MIN_HISTORY_PANEL_WIDTH = 280", self.js)
        self.assertIn("const MIN_ACTIVE_CHAT_WIDTH = 560", self.js)
        history_resize = function_body(self.js, "setHistoryPanelWidth")
        chat_resize = function_body(self.js, "setActiveChatWidth")
        self.assertIn("const main = activeChatWidth()", history_resize)
        self.assertIn("width + 12 + main", history_resize)
        self.assertIn("const history = historyWidth()", chat_resize)
        self.assertIn("history + 12 + width", chat_resize)
        self.assertIn('localStorage.setItem("eve.historyPanelWidth"', self.js)
        self.assertIn('localStorage.setItem("eve.activeChatWidth"', self.js)
        self.assertIn('localStorage.getItem("eve.historyPanelWidth"', self.js)
        self.assertIn('localStorage.getItem("eve.activeChatWidth"', self.js)
        self.assertRegex(self.css, r"\.chat-workspace\s*\{[^}]*min-width:\s*560px")
        self.assertRegex(self.css, r"\.conversation-panel\s*\{[^}]*min-width:\s*280px")
        self.assertIn('style.setProperty("--presence-scale"', self.js)
        self.assertRegex(
            self.html,
            r'<aside class="conversation-panel"[^>]*>\s*<div class="workspace-resize"',
        )
        self.assertRegex(
            self.html,
            r'<div class="chat-workspace">\s*<div class="panel-resize"',
        )
        self.assertNotIn("syncDesktopResizeHandles", self.js)
        persistent_width = function_body(self.js, "persistentLayoutWidth")
        self.assertIn("element.getBoundingClientRect().width", persistent_width)
        self.assertIn("window.localStorage.getItem(storageKey)", persistent_width)
        self.assertIn("window.getComputedStyle(document.documentElement)", persistent_width)
        self.assertIn(
            "const desktopChatWidth = () => historyWidth() + activeChatWidth() + 12",
            self.js,
        )
        apply_widths = function_body(self.js, "applyDesktopChatWidths")
        self.assertIn("Math.max(MIN_ACTIVE_CHAT_WIDTH, requestedMain)", apply_widths)
        self.assertIn("Math.max(MIN_HISTORY_PANEL_WIDTH, history)", apply_widths)
        self.assertRegex(
            self.css,
            r"body\.chat-open \.panel-resize\s*\{[^}]*left:\s*-7px",
        )
        self.assertRegex(
            self.css,
            r"body\.chat-open \.workspace-resize\s*\{[^}]*left:\s*-7px",
        )
        self.assertRegex(
            self.css,
            r"body\.chat-open \.workspace-resize,[\s\S]*?body\.chat-open \.panel-resize\s*\{[^}]*position:\s*absolute",
        )
        self.assertIn('style.setProperty("--left-free-width"', self.js)
        self.assertIn('classList.toggle("chat-stacked-dock"', self.js)
        self.assertRegex(self.css, r"body\.chat-open\.chat-stacked-dock\s+\.command-dock")
        self.assertRegex(
            self.css,
            r"chat-stacked-dock\s+\.chat-workspace\s*\{[^}]*bottom:\s*76px",
        )
        self.assertRegex(
            self.css,
            r"chat-stacked-dock\s+\.command-dock\s*\{[^}]*right:\s*16px[^}]*left:\s*calc\(100vw - 16px - var\(--active-chat-width\)\)[^}]*justify-content:\s*center",
        )
        self.assertIn("canvasEngine.syncCoreBounds(520)", self.js)
        self.assertIn("this.coreSyncUntil = Math.max(this.coreSyncUntil", self.js)

    def test_chat_and_sidebar_mode_are_restored_after_reload(self):
        self.assertIn('let chatOpen = window.localStorage.getItem("eve.chatOpen") === "true"', self.js)
        self.assertIn('let sidebarOpen = window.localStorage.getItem("eve.sidebarOpen") !== "false"', self.js)
        self.assertIn('let panelView = window.localStorage.getItem("eve.panelView")', self.js)
        self.assertIn('["conversations", "schedules", "tasks"]', self.js)
        self.assertIn('localStorage.setItem("eve.chatOpen"', function_body(self.js, "setChatOpen"))
        self.assertIn('localStorage.setItem("eve.sidebarOpen"', function_body(self.js, "setSidebarOpen"))
        self.assertIn('localStorage.setItem("eve.panelView"', function_body(self.js, "setPanelView"))

    def test_brainwatch_open_state_and_mode_are_restored_after_reload(self):
        self.assertIn('localStorage.getItem("eve.brainwatchOpen") === "true"', self.js)
        self.assertIn('localStorage.getItem("eve.brainwatchMode")', self.js)
        self.assertIn('localStorage.setItem("eve.brainwatchOpen"', function_body(self.js, "setBrainwatchOpen"))
        self.assertIn('localStorage.setItem("eve.brainwatchMode"', function_body(self.js, "setBrainwatchMode"))
        startup = self.js.rsplit("updatePTT();", 1)[1]
        self.assertIn('setBrainwatchMode(restoreBrainwatchMode, {load: false})', startup)
        self.assertIn("if (restoreBrainwatchOpen) setBrainwatchOpen(true)", startup)

    def test_mobile_nerd_mode_hides_floating_status_readout(self):
        self.assertRegex(
            self.css,
            r"@media\s*\(max-width:\s*899px\)[\s\S]*?body\.nerd-open \.state-readout\s*\{[^}]*opacity:\s*0[^}]*visibility:\s*hidden",
        )
        startup = self.js.rsplit("updatePTT();", 1)[1]
        self.assertIn("setChatOpen(chatOpen)", startup)
        self.assertIn("setPanelView(panelView)", startup)

    def test_conversation_and_task_sidebar_can_be_hidden_independently(self):
        self.assertNotIn('id="closeSidebar"', self.html)
        sidebar = function_body(self.js, "setSidebarOpen")
        self.assertIn('classList.toggle("sidebar-hidden", !sidebarOpen)', sidebar)
        self.assertIn('setAttribute("aria-expanded", String(sidebarOpen))', sidebar)
        self.assertRegex(self.css, r"body\.chat-open\.sidebar-hidden\s+\.conversation-panel\s*\{[^}]*visibility:\s*hidden")
        self.assertRegex(self.css, r"body\.chat-open\s+\.conversation-toggle\s*\{[^}]*display:\s*grid")
        chat_head = self.html.split('<header class="chat-head">', 1)[1].split('</header>', 1)[0]
        self.assertIn('class="sidebar-open-mark"', chat_head)
        self.assertIn('class="sidebar-close-mark"', chat_head)
        self.assertRegex(
            self.css,
            r'\.conversation-toggle\[aria-expanded="true"\]\s+\.sidebar-open-mark\s*\{[^}]*opacity:\s*0',
        )
        self.assertRegex(
            self.css,
            r'\.conversation-toggle\[aria-expanded="true"\]\s+\.sidebar-close-mark\s*\{[^}]*opacity:\s*1',
        )
        self.assertRegex(self.css, r"\.sidebar-close-mark\s*\{[^}]*transition:")
        self.assertIn('class="chat-title-cluster"', chat_head)
        self.assertIn('id="conversationToggle"', chat_head)
        self.assertLess(chat_head.index('id="conversationToggle"'), chat_head.index('id="conversationTitle"'))

    def test_visible_work_tasks_refresh_without_overwriting_inline_drafts(self):
        refresh = function_body(self.js, "refreshWorkTasksIfVisible")
        for guard in (
            "!chatOpen", "!showingTasks", "document.hidden", "workMutationBusy",
            "workRefreshBusy", "editingWorkItemId", "addingToWorkListId",
            "!elements.newWorkListForm.hidden",
        ):
            self.assertIn(guard, refresh)
        self.assertIn("await loadWorkTasks(true)", refresh)
        loader = function_body(self.js, "loadWorkTasks")
        self.assertIn("workTaskRevision", loader)
        self.assertIn("nextRevision === workDataRevision", loader)
        self.assertIn("return false", loader)
        self.assertIn("window.setInterval(refreshWorkTasksIfVisible, 2000)", self.js)
        self.assertIn("refreshWorkTasksIfVisible();", self.js)

    def test_work_items_use_pointer_drag_handle_and_atomic_server_move(self):
        item = function_body(self.js, "workItemNode")
        self.assertIn('handle.className = "work-drag-handle"', item)
        self.assertIn('handle.addEventListener("pointerdown"', item)
        self.assertIn("startWorkItemDrag(event, item, row, handle)", item)
        self.assertIn('row.dataset.itemId = item.id', item)

        drag = function_body(self.js, "startWorkItemDrag")
        self.assertIn("handle.setPointerCapture(event.pointerId)", drag)
        self.assertIn('handle.addEventListener("pointermove"', drag)
        self.assertIn('handle.addEventListener("pointerup"', drag)
        self.assertIn('handle.addEventListener("pointercancel"', drag)
        self.assertIn("Math.hypot", drag)
        self.assertIn("persistWorkItemMove(item, targetListId, targetPosition)", drag)

        target = function_body(self.js, "updateWorkDropTarget")
        self.assertIn("document.elementFromPoint", target)
        self.assertIn('.closest(".work-list[data-list-id]")', target)
        self.assertIn("if (!targetList.open)", target)
        self.assertIn('targetList.classList.add("work-drop-list")', target)
        self.assertIn('before.classList.add("work-drop-before")', target)

        persist = function_body(self.js, "persistWorkItemMove")
        self.assertIn('method: "PATCH"', persist)
        self.assertIn("JSON.stringify({ list_id: listId, position })", persist)
        self.assertIn("await loadWorkTasks()", persist)
        self.assertIn("setWorkTaskError(error.message)", persist)

        handle_css = css_declarations(self.css, ".conversation-panel .work-drag-handle")
        self.assertIn("touch-action: none", handle_css)
        self.assertIn("min-height: 44px", handle_css)
        self.assertIn("cursor: grab", handle_css)

    def test_voice_dock_is_a_single_layer_above_chat_surfaces(self):
        dock = css_declarations(self.css, ".command-dock")
        panel = css_declarations(self.css, ".conversation-panel")
        self.assertRegex(dock, r"z-index:\s*37")
        self.assertRegex(panel, r"z-index:\s*36")

    def test_core_stage_is_fixed_and_independent_of_output_flow(self):
        stage_css = css_declarations(
            self.css,
            "#mark", ".mark", "#presence", ".presence", ".core-scene",
            "#coreStage", ".core-stage", "[data-core-stage]",
        )
        self.assertTrue(stage_css, "Kein CSS-Selektor für die Core-Bühne gefunden")
        self.assertRegex(stage_css, r"(?i)\bposition\s*:\s*fixed\b")
        self.assertNotRegex(stage_css, r"(?i)\bposition\s*:\s*(?:static|relative)\b")
        self.assertRegex(stage_css, r"(?i)\b(?:inset|left|top)\s*:")

    def test_responsive_and_reduced_motion_contracts_cover_css_and_canvas(self):
        viewport = [attrs for tag, attrs in self.dom.elements if tag == "meta" and attrs.get("name") == "viewport"]
        self.assertTrue(viewport)
        self.assertIn("width=device-width", viewport[0].get("content", ""))
        self.assertRegex(self.css, r"(?i)@media\s*\([^)]*max-width\s*:")
        self.assertRegex(self.css, r"(?i)@media\s*\([^)]*max-height\s*:")
        self.assertRegex(self.css, r"(?i)@media\s*\([^)]*prefers-reduced-motion\s*:\s*reduce")
        self.assertRegex(
            self.css,
            r"(?i)(?:animation\s*:\s*none|animation-duration\s*:\s*(?:0|\.0*1)ms)",
        )
        self.assertRegex(
            self.css,
            r"(?i)(?:transition\s*:\s*none|transition-duration\s*:\s*(?:0|\.0*1)ms)",
        )
        self.assertIn(":focus-visible", self.css)
        self.assertRegex(
            self.js,
            r"matchMedia\s*\(\s*['\"]\(prefers-reduced-motion:\s*reduce\)['\"]\s*\)",
        )

    def test_api_paths_and_notification_method_are_stable(self):
        for path in ("/api/state", "/api/message", "/api/turn", "/api/notifications"):
            self.assertIn(path, self.js)
        notifications = function_body(self.js, "checkNotifications", "pollNotifications")
        self.assertIn("/api/notifications", notifications)
        self.assertRegex(notifications, r"(?i)\bmethod\s*:\s*['\"]POST['\"]")
        self.assertIn("/api/conversations", self.js)
        self.assertIn("/api/tasks", self.js)
        for method in ("POST", "PATCH", "DELETE"):
            self.assertIn(method, self.js)

    def test_work_task_frontend_uses_persistent_lists_and_server_state(self):
        for element_id in (
            "taskViewToggle", "taskList", "workLists", "workTaskError",
            "newWorkList", "newWorkListForm", "newWorkListName",
            "newWorkListDescription",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('aria-label="Arbeitslisten"', self.html)
        _, new_list = self.element("newWorkList")
        self.assertEqual(new_list.get("aria-label"), "Neue Arbeitsliste")
        self.assertEqual(new_list.get("title"), "Neue Arbeitsliste")
        self.assertIn('class="work-list-add"', self.html)
        self.assertNotIn("＋ LISTE", self.html)
        self.assertRegex(self.css, r"\.work-list-add svg\s*\{")
        self.assertIn('role="alert"', self.html)

        loader = function_body(self.js, "loadWorkTasks")
        self.assertIn('"/api/work-lists?limit=200"', loader)
        self.assertIn('"/api/work-items?status=all&limit=200"', loader)
        self.assertIn("Promise.all", loader)
        self.assertIn("renderWorkLists", loader)

        renderer = function_body(self.js, "renderWorkLists")
        self.assertIn('document.createElement("details")', renderer)
        self.assertIn('document.createElement("summary")', renderer)
        self.assertIn("openItems", renderer)
        self.assertIn("completedItems", renderer)
        self.assertIn('completed.className = "work-completed"', renderer)
        self.assertIn("workItemForm", renderer)
        self.assertNotIn('method: "DELETE"', renderer)
        self.assertIn('persistWorkDisclosures("eve.openWorkLists"', self.js)
        self.assertIn("window.localStorage.setItem(key", function_body(self.js, "persistWorkDisclosures"))

    def test_work_items_complete_reopen_edit_move_and_create_inline(self):
        row = function_body(self.js, "workItemNode")
        self.assertIn('checkbox.type = "checkbox"', row)
        self.assertIn('method: "PATCH"', row)
        self.assertIn('status: checkbox.checked ? "completed" : "open"', row)
        self.assertIn("await loadWorkTasks()", row)
        self.assertIn("renderWorkLists()", row)
        self.assertIn("editingWorkItemId = item.id", row)

        editor = function_body(self.js, "workItemForm")
        self.assertIn('document.createElement("textarea")', editor)
        self.assertIn('document.createElement("select")', editor)
        self.assertIn("payload.list_id = listSelect.value", editor)
        self.assertIn("payload.title === item.title", editor)
        self.assertIn("payload.list_id === item.list_id", editor)
        self.assertIn('item ? "PATCH" : "POST"', editor)
        self.assertIn('item ? `/api/work-items/${encodeURIComponent(item.id)}` : "/api/work-items"', editor)
        self.assertNotRegex(editor, r"\b(?:input|change)\b[^\n]*workTaskRequest")

        delete_item = function_body(self.js, "deleteWorkItem")
        self.assertIn("window.confirm", delete_item)
        self.assertIn('method: "DELETE"', delete_item)
        self.assertIn("await loadWorkTasks()", delete_item)
        delete_list = function_body(self.js, "deleteWorkList")
        self.assertIn("window.confirm", delete_list)
        self.assertIn('method: "DELETE"', delete_list)
        self.assertIn("await loadWorkTasks()", delete_list)
        self.assertIn('remove.className = "work-delete-item work-delete-action"', editor)
        self.assertIn('remove.setAttribute("aria-label"', editor)
        self.assertIn("remove.append(workDeleteIcon())", editor)
        renderer = function_body(self.js, "renderWorkLists")
        self.assertIn('removeList.className = "work-delete-list work-delete-action"', renderer)
        self.assertIn('removeList.setAttribute("aria-label"', renderer)
        self.assertIn("workDeleteIcon()", renderer)
        delete_icon = function_body(self.js, "workDeleteIcon")
        self.assertIn('createElementNS("http://www.w3.org/2000/svg", "svg")', delete_icon)

        panel_view = function_body(self.js, "setPanelView")
        self.assertIn('"Arbeitsaufgaben"', panel_view)
        self.assertIn("loadWorkTasks", panel_view)

        self.assertRegex(self.css, r"\.work-list\s*>\s*summary\s*\{[^}]*min-height:\s*48px")
        self.assertRegex(self.css, r"\.work-item-row\s*\{[^}]*min-height:\s*44px")
        self.assertRegex(self.css, r"\.conversation-panel \.work-item-content\s*\{[^}]*align-content:\s*center")
        self.assertIn("touch-action: manipulation", self.css)

    def test_scheduled_eve_turns_have_their_own_sidebar_view(self):
        for element_id in ("scheduleViewToggle", "scheduledTaskView", "scheduledTaskList", "scheduledTaskListEmpty", "taskEditor", "taskMessage"):
            self.element(element_id)
        renderer = function_body(self.js, "renderTaskList")
        editor = function_body(self.js, "editTask")
        submit = self.js[self.js.index('elements.taskEditorForm.addEventListener("submit"'):]
        self.assertIn("task.action?.request", renderer)
        self.assertIn("elements.scheduledTaskList.replaceChildren", renderer)
        self.assertIn('delay: "Einmalig verzögert"', self.js)
        self.assertIn('task.action?.request', editor)
        self.assertIn('request: elements.taskMessage.value.trim()', submit)
        self.assertIn("ZEITPLÄNE", self.html)
        self.assertIn("Von EVE später oder regelmäßig ausgeführte Aufträge", self.html)
        self.assertRegex(self.css, r"\.scheduled-task-intro\s*\{")
        task_markup = self.html[self.html.index('id="taskList"'):self.html.index('</section>', self.html.index('id="taskList"'))]
        self.assertNotIn('id="scheduledTaskList"', task_markup)

    def test_desktop_sidebar_and_chat_share_the_same_bottom_edge(self):
        self.assertIn("--eve-desktop-edge-gap: 16px", self.css)
        self.assertRegex(
            self.css,
            r"body\.chat-open \.conversation-panel,\s*body\.chat-open \.chat-workspace\s*\{[^}]*bottom:\s*var\(--eve-desktop-edge-gap\)",
        )

    def test_chat_history_uses_safe_dom_rendering_and_active_conversation(self):
        self.assertIn("activeConversationId", self.js)
        self.assertIn("conversation_id", self.js)

    def test_opening_chat_resolves_inactivity_before_showing_old_history(self):
        opener = function_body(self.js, "openCurrentChat")
        self.assertIn("await synchronizeConversationLifecycle()", opener)
        self.assertIn("setChatOpen(true)", opener)
        lifecycle = function_body(self.js, "synchronizeConversationLifecycle")
        self.assertIn('"/api/conversations/active"', lifecycle)
        self.assertIn("activeConversationId", lifecycle)
        self.assertIn("await loadConversations(activeConversationId)", lifecycle)
        self.assertRegex(self.js, r"chatMessages\s*\.\s*(?:append|replaceChildren)\s*\(")
        message_renderer = function_body(self.js, "createMessageNode", "renderMessage")
        self.assertIn("textContent", message_renderer)
        self.assertNotIn("innerHTML", message_renderer)

    def test_clicking_saved_conversation_only_loads_that_conversation(self):
        renderer = function_body(self.js, "renderConversationList")
        self.assertIn("selectConversation(conversation.id)", renderer)
        selector = function_body(self.js, "selectConversation")
        self.assertNotIn('"/api/conversations/active"', selector)
        self.assertIn("encodeURIComponent(conversationId)", selector)
        self.assertIn("explicitConversationResume = true", selector)

    def test_work_task_context_links_open_and_highlight_saved_chat_location(self):
        renderer = function_body(self.js, "workItemNode")
        navigator = function_body(self.js, "openTaskContext")
        self.assertIn("context_links", renderer)
        self.assertIn("work-context-link", renderer)
        self.assertIn("await toggleTaskView(false)", navigator)
        self.assertIn("start_message_id", navigator)
        self.assertIn("context-highlight", navigator)
        self.assertIn("scrollIntoView", navigator)
        self.assertIn("dataset.messageId", self.js)
        self.assertIn("await selectConversation(link.conversation_id, false, true)", navigator)
        self.assertNotIn("before", navigator)

    def test_context_anchor_does_not_filter_conversation_messages(self):
        selector = function_body(self.js, "selectConversation")
        navigator = function_body(self.js, "openTaskContext")
        self.assertIn("...(data.messages || [])", selector)
        self.assertIn("...(data.failures || [])", selector)
        self.assertIn("renderMessages(timeline)", selector)
        self.assertIn("?limit=200", selector)
        self.assertNotIn("beforeQuery", selector)
        self.assertNotIn("renderMessages", navigator)
        self.assertNotIn("replaceChildren", navigator)
        self.assertIn('querySelectorAll(".chat-message")', navigator)
        self.assertIn("ordinal >= firstOrdinal && ordinal <= endOrdinal", navigator)
        self.assertIn("(start || elements.chatMessages.firstElementChild)?.scrollIntoView", navigator)

    def test_work_task_context_links_are_compact_accessible_and_grouped(self):
        renderer = function_body(self.js, "workItemNode")
        self.assertIn('compactLabel.textContent = "Kontext"', renderer)
        self.assertIn('"Chat-Kontext öffnen"', renderer)
        self.assertIn("work-context-chooser", renderer)
        self.assertIn("contextLinks.length > 1", renderer)
        self.assertIn("work-context-option", renderer)
        self.assertNotIn("button.textContent = `Kontext ·", renderer)
        self.assertRegex(self.css, r"\.work-context-links\s*\{[^}]*flex:\s*0 0 auto")
        self.assertIn(".work-context-text", self.css)

    def test_visible_chat_is_persistently_resumed_in_text_and_voice_turns(self):
        submit = function_body(self.js, "submitMessage")
        voice = function_body(self.js, "stopPTT")
        lifecycle = function_body(self.js, "synchronizeConversationLifecycle")
        self.assertIn("resume_conversation: explicitConversationResume", submit)
        self.assertIn('"&resume_conversation=true"', voice)
        self.assertIn("if (explicitConversationResume) return", lifecycle)
        self.assertNotIn("explicitConversationResume = false", submit)
        self.assertNotIn("explicitConversationResume = false", voice)

    def test_assistant_markdown_is_parsed_sanitized_and_user_text_stays_plain(self):
        marked_path = WEB_ROOT / "vendor" / "marked.umd.js"
        purify_path = WEB_ROOT / "vendor" / "purify.min.js"
        self.assertTrue(marked_path.is_file())
        self.assertTrue(purify_path.is_file())
        self.assertIn("marked v18.0.14", marked_path.read_text(encoding="utf-8")[:300])
        self.assertIn("DOMPurify 3.4.16", purify_path.read_text(encoding="utf-8")[:300])
        self.assertLess(self.html.index('src="vendor/marked.umd.js"'), self.html.index('src="app.js'))
        self.assertLess(self.html.index('src="vendor/purify.min.js"'), self.html.index('src="app.js'))

        renderer = function_body(self.js, "renderAssistantMarkdown")
        self.assertIn("window.marked.parse", renderer)
        self.assertIn("window.DOMPurify.sanitize", renderer)
        self.assertIn("RETURN_DOM_FRAGMENT: true", renderer)
        self.assertIn("ALLOWED_TAGS", renderer)
        self.assertIn("ALLOWED_ATTR", renderer)
        self.assertIn("ALLOW_DATA_ATTR: false", renderer)
        self.assertIn("renderer.html", renderer)
        self.assertIn("escapeChatHtml", renderer)
        self.assertIn('fragment.querySelectorAll("a").forEach(safeChatLink)', renderer)
        self.assertIn("target.replaceChildren(fragment)", renderer)
        self.assertNotIn("innerHTML", renderer)

        link_safety = function_body(self.js, "safeChatLink")
        self.assertIn('"http:"', link_safety)
        self.assertIn('"https:"', link_safety)
        self.assertIn('anchor.target = "_blank"', link_safety)
        self.assertIn('anchor.rel = "noopener noreferrer"', link_safety)
        self.assertIn("anchor.replaceWith", link_safety)

        message_renderer = function_body(self.js, "createMessageNode")
        self.assertIn('message.role === "assistant"', message_renderer)
        self.assertIn("renderAssistantMarkdown(content, message.content)", message_renderer)
        self.assertIn('content.textContent = String(message.content || "")', message_renderer)

    def test_assistant_markdown_styles_remain_responsive(self):
        markdown = css_declarations(self.css, ".message-content.assistant-markdown")
        code_block = css_declarations(self.css, ".assistant-markdown pre")
        link = css_declarations(self.css, ".assistant-markdown a")
        self.assertIn("min-width: 0", markdown)
        self.assertIn("white-space: normal", markdown)
        self.assertIn("max-width: 100%", code_block)
        self.assertIn("overflow-x: auto", code_block)
        self.assertIn("white-space: pre", code_block)
        self.assertIn("overflow-wrap: anywhere", link)

    def test_voice_mute_is_persistent_and_stops_active_playback(self):
        self.assertIn("eve.voiceMuted", self.js)
        mute = function_body(self.js, "toggleVoiceMute")
        playback = function_body(self.js, "playReply")
        self.assertIn("localStorage.setItem", mute)
        self.assertRegex(mute, r"activeOutputSource\s*\.\s*stop\s*\(")
        self.assertIn("voiceMuted", playback)

    def test_push_to_talk_tracks_release_while_permission_is_pending(self):
        start = function_body(self.js, "startPTT", "startRecording")
        stop = function_body(self.js, "stopPTT", "stopRecording")
        get_media_match = re.search(r"\bgetUserMedia\s*\(", start)
        start_recording_match = re.search(r"\brecorder\s*\.\s*start\s*\(", start)
        self.assertIsNotNone(get_media_match)
        self.assertIsNotNone(start_recording_match)
        get_media = get_media_match.start()
        start_recording = start_recording_match.start()
        self.assertGreater(start_recording, get_media)

        candidates = re.findall(
            r"\b([A-Za-z_$][\w$]*)\s*=\s*true\b",
            start[:get_media],
        )
        protected_by_intent = []
        for hold_flag in candidates:
            release = re.search(rf"\b{re.escape(hold_flag)}\s*=\s*false\b", stop)
            pending_guard = re.search(
                rf"if\s*\(\s*!\s*{re.escape(hold_flag)}\b",
                start[get_media:start_recording],
            )
            first_recorder_reference = stop.find("recorder")
            if (
                release is not None
                and pending_guard is not None
                and (first_recorder_reference < 0 or release.start() < first_recorder_reference)
            ):
                protected_by_intent.append(hold_flag)
        self.assertTrue(
            protected_by_intent,
            "PTT muss frühes Loslassen vor und nach await getUserMedia explizit berücksichtigen",
        )

    def test_push_to_talk_uses_pointer_capture_without_disabling_active_press(self):
        update_ptt = function_body(self.js, "updatePTT")
        self.assertRegex(compact(update_ptt), r"\.disabled=unavailable&&!pressActive")
        self.assertRegex(self.js, r"addEventListener\s*\(\s*[\"']pointerdown[\"']")
        self.assertRegex(self.js, r"\.setPointerCapture\s*\(\s*event\.pointerId\s*\)")
        self.assertRegex(self.js, r"addEventListener\s*\(\s*[\"']pointerup[\"']\s*,\s*finishPTT")
        self.assertRegex(self.js, r"addEventListener\s*\(\s*[\"']pointercancel[\"']\s*,\s*finishPTT")
        self.assertRegex(self.js, r"addEventListener\s*\(\s*[\"']lostpointercapture[\"']")
        release = function_body(self.js, "releaseActivePointerCapture")
        self.assertIn("releasePointerCapture", release)
        self.assertIn("hasPointerCapture", release)

        ptt_css = css_declarations(self.css, ".ptt")
        self.assertRegex(ptt_css, r"touch-action\s*:\s*none")
        self.assertRegex(ptt_css, r"user-select\s*:\s*none")
        self.assertRegex(ptt_css, r"-webkit-touch-callout\s*:\s*none")

    def test_push_to_talk_stop_is_idempotent(self):
        stop = function_body(self.js, "stopPTT", "stopRecording")
        self.assertIn("stopRecordingPromise", stop)
        self.assertRegex(stop, r"if\s*\(\s*stopRecordingPromise\s*\)\s*return")

    def test_audio_queue_and_request_cleanup_keep_independent_state(self):
        update_ptt = function_body(self.js, "updatePTT")
        self.assertIn(".disabled", update_ptt)
        for state in ("requestBusy", "captureBusy", "audioQueued", "playingAudio"):
            self.assertIn(state, update_ptt)

        play_reply = function_body(self.js, "playReply", "playAudioReply")
        stop_wait = play_reply.find("waitUntilRecordingStops")
        unlock = play_reply.find("unlockAudio")
        self.assertGreaterEqual(stop_wait, 0)
        self.assertGreater(unlock, stop_wait)

        queue_reply = function_body(self.js, "queueReply", "enqueueReply")
        self.assertIn("MAX_AUDIO_QUEUE", queue_reply)
        self.assertRegex(compact(queue_reply), r"audioQueued>=MAX_AUDIO_QUEUE")
        self.assertRegex(self.js, r"\bMAX_AUDIO_QUEUE\s*=\s*8\b")

        for name in ("submitMessage", "stopPTT"):
            body = function_body(self.js, name)
            self.assertNotRegex(body, r"\bplayingAudio\s*=\s*false\b")
            self.assertRegex(body, r"\bfinally\s*\{")
            self.assertRegex(body, r"\brequestBusy\s*=\s*false\b")
            self.assertRegex(body, r"\bupdatePTT\s*\(")

    def test_playback_uses_analyser_data_for_visuals(self):
        analyser_match = re.search(
            r"\b([A-Za-z_$][\w$]*)\s*=\s*(?:audioCtx|audioContext)\.createAnalyser\s*\(",
            self.js,
        )
        self.assertIsNotNone(analyser_match, "Playback erzeugt keinen Audio-Analyser")
        analyser = re.escape(analyser_match.group(1))
        self.assertRegex(self.js, r"\.frequencyBinCount\b")
        self.assertRegex(self.js, r"\.getByte(?:Frequency|TimeDomain)Data\s*\(")
        self.assertRegex(
            self.js,
            rf"{analyser}\.connect\s*\(\s*(?:audioCtx|audioContext)\.destination\s*\)",
        )
        play_reply = function_body(self.js, "playReply", "playAudioReply")
        self.assertRegex(play_reply, r"\.createBufferSource\s*\(")
        source_connection = re.search(
            r"\b[A-Za-z_$][\w$]*\.connect\s*\(\s*([A-Za-z_$][\w$]*)\s*\)",
            play_reply,
        )
        self.assertIsNotNone(source_connection, "Reply-Audio wird nicht durch einen Node geleitet")
        connected_node = source_connection.group(1)
        if connected_node != analyser_match.group(1):
            self.assertRegex(
                play_reply,
                rf"\b{re.escape(connected_node)}\s*=\s*[A-Za-z_$][\w$]*Analyser\s*\(",
                "Der verbundene Playback-Node stammt nicht aus dem Audio-Analyser",
            )

    def test_sources_are_created_as_text_and_restricted_to_http_urls(self):
        self.assertNotRegex(self.js, r"\.(?:innerHTML|outerHTML)\s*=")
        self.assertNotIn("insertAdjacentHTML", self.js)
        render_sources = function_body(self.js, "renderSources")
        self.assertRegex(render_sources, r"createElement\s*\(\s*['\"]a['\"]\s*\)")
        self.assertIn("textContent", render_sources)
        self.assertIn("noopener", render_sources)
        self.assertIn("noreferrer", render_sources)
        self.assertRegex(self.js, r"new\s+URL\s*\(")
        self.assertRegex(self.js, r"\.protocol\b")
        self.assertIn("http:", self.js)
        self.assertIn("https:", self.js)

    def test_integrated_config_view_uses_safe_server_described_fields(self):
        for element_id in ("systemMenuToggle", "systemMenu", "openConfig", "configView", "configForm", "configSections", "configSave"):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertNotIn('id="configToggle"', self.html)
        self.assertIn('fetchWithTimeout("/api/config"', self.js)
        self.assertIn('method: "PATCH"', function_body(self.js, "saveConfig"))
        self.assertIn("data-config-field", self.js)
        self.assertIn("textContent", function_body(self.js, "renderConfig"))
        self.assertNotRegex(self.js, r"(?:token|api_key).*\.value\s*=\s*field\.value")
        self.assertIn("Gesetzt – leer lassen zum Beibehalten", self.js)
        self.assertIn("nach einem EVE-Neustart wirksam", self.js)
        self.assertRegex(self.css, r"\.system-menu-toggle\s*\{[^}]*width\s*:\s*44px[^}]*height\s*:\s*44px")

    def test_config_sections_are_persistent_native_disclosures_and_new_sections_default_closed(self):
        render = function_body(self.js, "renderConfig")
        self.assertIn('document.createElement("details")', render)
        self.assertIn('document.createElement("summary")', render)
        self.assertIn('body.className = "config-section-body"', render)
        self.assertIn("card.open = openSections.has(section.id)", render)
        self.assertIn('card.addEventListener("toggle"', render)
        self.assertIn('localStorage.setItem("eve.openConfigSections"', render)
        stored = function_body(self.js, "storedConfigSections")
        self.assertIn('localStorage.getItem("eve.openConfigSections")', stored)
        self.assertIn("return new Set()", stored)
        self.assertRegex(self.css, r"\.config-section\[open\]")
        self.assertRegex(self.css, r"\.config-section\s*>\s*summary")
        sections = css_declarations(self.css, ".config-sections")
        section = css_declarations(self.css, ".config-section")
        self.assertIn("align-items: flex-start", sections)
        self.assertIn("align-self: flex-start", section)
        self.assertNotIn("height: max-content", section)
        opened = css_declarations(self.css, ".config-section[open]")
        self.assertIn("width: 100%", section)
        self.assertIn("flex: 0 0 auto", section)
        self.assertNotIn("grid-column", opened)
        body = css_declarations(self.css, ".config-section-body")
        self.assertIn("width: 100%", body)
        fields = css_declarations(self.css, ".config-field")
        self.assertIn("grid-template-columns: clamp(170px, 22%, 240px) minmax(0, 1fr)", fields)

    def test_home_assistant_config_has_read_only_inventory_action(self):
        action = function_body(self.js, "homeAssistantInventoryAction")
        self.assertIn("ENTITÄTEN ENTDECKEN", action)
        self.assertIn("/api/home-assistant/inventory", action)
        self.assertIn('method: "POST"', action)
        self.assertIn("ohne Geräteaktion", action)
        self.assertIn("data.inventory?.counts", action)
        self.assertNotIn("configValues.set", action)
        render = function_body(self.js, "renderConfig")
        self.assertIn('section.id === "home_assistant"', render)
        self.assertIn("homeAssistantInventoryAction()", render)
        style = css_declarations(self.css, ".config-provider-action")
        self.assertIn("display: grid", style)

    def test_config_sections_have_safe_source_specific_eve_icons(self):
        icons = function_body(self.js, "configSectionIcon")
        for section in ("home_assistant", "llm", "speech_to_text", "text_to_speech", "web", "nova_maintenance", "conversation", "local_files"):
            self.assertIn(f"{section}:", icons)
        self.assertIn('createElementNS("http://www.w3.org/2000/svg", "svg")', icons)
        self.assertIn('svg.setAttribute("aria-hidden", "true")', icons)
        self.assertNotIn("innerHTML", icons)
        render = function_body(self.js, "renderConfig")
        self.assertIn("configSectionIcon(section.id)", render)
        icon_style = css_declarations(self.css, ".config-section-icon")
        self.assertIn("stroke: currentColor", icon_style)
        self.assertIn("filter: drop-shadow", icon_style)

    def test_config_help_covers_every_current_editable_field(self):
        expected = {
            "home_assistant.enabled", "home_assistant.url", "home_assistant.language",
            "home_assistant.timeout_seconds", "home_assistant.token",
            "llm.base_url", "llm.model", "llm.timeout_seconds", "llm.use_server_limits",
            "llm.max_tokens", "llm.api_key",
            "speech_to_text.model", "speech_to_text.language", "speech_to_text.device",
            "speech_to_text.compute_type", "speech_to_text.initial_prompt", "speech_to_text.hotwords",
            "text_to_speech.engine", "text_to_speech.voice", "text_to_speech.data_dir",
            "text_to_speech.piper_chunk_chars", "web.enabled", "web.searxng_url",
            "web.image_results", "web.timeout_seconds", "nova_maintenance.enabled",
            "nova_maintenance.command", "nova_maintenance.timeout_seconds",
            "semantic_similarity.enabled",
            "semantic_similarity.mode", "semantic_similarity.threshold",
            "semantic_composition.enabled", "semantic_composition.mode", "local_files.roots",
            "shell.enabled", "shell.executable", "shell.forbidden_commands",
        }
        for field_id in expected:
            self.assertIn(f'"{field_id}":', self.js)
        render = function_body(self.js, "renderConfig")
        self.assertIn("CONFIG_HELP[field.id]", render)
        self.assertIn('help.className = "config-help-trigger"', render)
        self.assertIn('help.type = "button"', render)
        self.assertIn('description.className = "config-field-description"', render)
        self.assertIn('control.disabled = Boolean(field.locked)', function_body(self.js, "configControl"))
        self.assertIn('document.createElement("datalist")', render)

    def test_config_help_is_single_touch_safe_and_does_not_change_values(self):
        opener = function_body(self.js, "openConfigHelp")
        closer = function_body(self.js, "closeConfigHelp")
        positioner = function_body(self.js, "positionConfigHelp")
        renderer = function_body(self.js, "renderConfig")
        self.assertIn("closeConfigHelp()", opener)
        self.assertIn("configHelpAnchor = button", opener)
        self.assertIn('button.setAttribute("aria-expanded", "true")', opener)
        self.assertIn('configHelpAnchor.setAttribute("aria-expanded", "false")', closer)
        self.assertNotIn("configValues", opener)
        self.assertNotRegex(opener, r"\.value\s*=")
        self.assertIn('help.addEventListener("click"', renderer)
        self.assertIn("event.preventDefault()", renderer)
        self.assertIn("event.stopPropagation()", renderer)
        self.assertIn('const row = document.createElement("div")', renderer)
        self.assertIn("getBoundingClientRect", positioner)
        self.assertIn("window.innerWidth", positioner)
        self.assertIn("window.innerHeight", positioner)

    def test_config_help_closes_outside_and_with_escape(self):
        self.assertIn('event.key === "Escape" && !elements.configHelpPopover.hidden', self.js)
        self.assertIn('!event.target.closest(".config-help-trigger")', self.js)
        self.assertIn("!elements.configHelpPopover.contains(event.target)", self.js)
        self.assertIn('configHelpClose.addEventListener("click", closeConfigHelp)', self.js)
        self.assertIn('configSections.addEventListener("scroll", closeConfigHelp', self.js)
        popover = css_declarations(self.css, ".config-help-popover")
        self.assertIn("position: fixed", popover)
        self.assertIn("max-height:", popover)
        self.assertIn("overflow: auto", popover)

    def test_system_menu_and_config_are_touch_responsive_and_scrollable(self):
        menu = function_body(self.js, "setSystemMenuOpen")
        config = function_body(self.js, "setConfigOpen")
        self.assertIn("aria-expanded", menu)
        self.assertIn("systemMenu.hidden", menu)
        self.assertIn("setSystemMenuOpen(false)", config)
        self.assertIn('elements.openConfig.addEventListener("click"', self.js)
        self.assertIn('document.addEventListener("pointerdown"', self.js)
        self.assertIn(">Konfiguration</button>", self.html)
        self.assertRegex(self.css, r"\.config-sections\s*\{[^}]*overflow-y\s*:\s*auto")
        self.assertRegex(self.css, r"\.config-sections\s*\{[^}]*touch-action\s*:\s*pan-y")
        self.assertRegex(self.css, r"\.config-sections\s*\{[^}]*flex-direction:\s*column")
        self.assertIn("@media (max-width: 899px)", self.css)
        self.assertIn("@media (max-width: 390px)", self.css)
        self.assertNotRegex(self.css, r"body\.config-open\s+\.command-dock")
        self.assertNotRegex(self.css, r"body\.config-open\s+\.share-toggle")
        self.assertIn("attachHorizontalResize(elements.configResize", self.js)
        self.assertIn('window.localStorage.setItem("eve.configWidth"', self.js)
        self.assertRegex(self.css, r"width:\s*var\(--config-width,\s*clamp\(760px,\s*68vw,\s*1800px\)\)")
        self.assertIn("--safe-top: env(safe-area-inset-top, 0px)", self.css)
        self.assertRegex(self.css, r"height:\s*calc\(100dvh\s*-\s*126px[^}]*var\(--safe-top,\s*0px\)")
        self.assertRegex(self.css, r"\.config-head h1\s*\{[^}]*font-size:\s*17px")
        self.assertRegex(self.css, r"\.config-head button\s*\{[^}]*width:\s*31px[^}]*font-size:\s*17px")
        self.assertRegex(self.css, r"\.config-footer button\s*\{[^}]*min-height:\s*38px[^}]*font:\s*650 9px")
        config_save = self.html.split('id="configSave"', 1)[1].split("</button>", 1)[0]
        self.assertIn("<svg", config_save)
        self.assertIn("SPEICHERN", config_save)
        disabled_save = css_declarations(self.css, ".config-footer button:disabled")
        self.assertIn("cursor: default", disabled_save)
        self.assertIn("color: #48636b", disabled_save)
        self.assertNotRegex(self.css, r"\.config-footer\s*\{[^}]*margin:[^;}]*-14px")
        self.assertRegex(self.css, r"@media \(max-width: 899px\)\s*\{[^}]*\.config-view\s*\{[^}]*left:\s*0")

    def test_nerd_mode_is_a_display_only_persistent_menu_toggle(self):
        for element_id in ("nerdModeToggle", "nerdModeState", "nerdView", "nerdTurns"):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertNotIn('id="nerdClose"', self.html)
        toggle = function_body(self.js, "setNerdMode")
        self.assertIn('localStorage.setItem("eve.nerdMode"', toggle)
        self.assertIn("nerdView.hidden", toggle)
        self.assertNotIn("/api/message", toggle)
        self.assertNotIn("/api/turn", toggle)
        self.assertIn('fetchWithTimeout(`/api/telemetry${suffix}`', self.js)
        self.assertIn("observability_only", (PROJECT_ROOT / "src" / "eve_agent" / "telemetry.py").read_text(encoding="utf-8"))
        self.assertNotRegex(self.js, r"innerHTML\s*=")
        self.assertRegex(self.css, r"\.nerd-view\s*\{[^}]*z-index:\s*11")
        self.assertRegex(self.css, r"\.conversation\s*\{[^}]*z-index:\s*12")
        self.assertRegex(self.css, r"\.nerd-view\s*\{[^}]*border:\s*0[^}]*border-radius:\s*0")
        self.assertIn("box-shadow: none; backdrop-filter: none", self.css)
        self.assertNotIn("body.nerd-open .system-menu-wrap", self.css)
        render = function_body(self.js, "renderNerdTurns")
        self.assertIn('querySelectorAll("details[open][data-nerd-key]")', render)
        self.assertIn("previousScrollTop", render)
        self.assertIn("rawScrollPositions", render)
        self.assertIn("distanceFromBottom", render)
        self.assertIn("position.pinnedToBottom", render)
        self.assertIn("pre.scrollTop =", render)
        self.assertIn("pre.scrollLeft = position.left", render)
        self.assertIn("details.open = openDetails.has", render)
        self.assertIn('call.role === "string"', render)
        self.assertIn(': "LLM-Aufruf"', render)
        self.assertNotRegex(render, r"callIndex\s*===|llm_calls\[[01]\]")

    def test_brainwatch_is_a_separate_read_only_graph_view(self):
        for element_id in (
            "openBrainwatch", "brainwatchView", "brainwatchSearchForm", "brainwatchSearch",
            "brainwatchCanvas", "brainwatchInspector", "brainwatchZoomIn", "brainwatchZoomOut",
            "brainwatchCenter", "brainwatchReset", "brainwatchMore",
        ):
            self.element(element_id)
        self.assertIn("Bitte nicht gegen die Scheibe klopfen.", self.html)
        self.assertIn("class BrainwatchGraph", self.js)
        self.assertIn("pointerdown", self.js)
        self.assertIn('addEventListener("wheel"', self.js)
        self.assertIn("encodeURIComponent(nodeId)", self.js)
        self.assertIn("/api/brainwatch/search", self.js)
        self.assertIn("new Map()", self.js)
        self.assertNotRegex(function_body(self.js, "searchBrainwatch"), r"method\s*:\s*['\"](?:POST|PATCH|DELETE)")
        self.assertNotRegex(function_body(self.js, "focusBrainwatchNode"), r"method\s*:\s*['\"](?:POST|PATCH|DELETE)")
        self.assertIn("semantic_similarity", self.js)
        self.assertIn("lexical_match", self.js)
        self.assertRegex(self.css, r"body\.brainwatch-open")

    def test_brainwatch_information_graph_focus_modes_and_visual_hierarchy(self):
        for element_id in (
            "brainwatchToggleBranch", "brainwatchContextView", "brainwatchFlowView",
            "brainwatchOverviewView", "brainwatchPath", "brainwatchSearchCollapse",
        ):
            self.element(element_id)
        graph_start = self.js.index("class BrainwatchGraph")
        graph = self.js[graph_start:self.js.index("  const brainwatchGraph", graph_start)]
        self.assertIn("this.expansions = new Map()", graph)
        self.assertIn("this.anchors = new Set()", graph)
        self.assertIn("collapse(nodeId)", graph)
        self.assertIn("contribution.nodes.has(candidate)", graph)
        self.assertIn("setViewMode(mode)", graph)
        self.assertIn('["context", "flow", "overview"]', graph)
        self.assertIn("layoutFocusedNeighborhood()", graph)
        self.assertIn("centerOnFocus()", graph)
        self.assertIn("BRAINWATCH_FLOW_RELATIONS.has(edge.data.type)", graph)
        self.assertIn('["lineage", "retrieval"].includes(edge.data.category)', graph)
        self.assertIn("focusContext()", graph)
        self.assertIn("graphDistances()", graph)
        self.assertIn("node.pinned = true", graph)
        self.assertIn("activePointers", graph)
        self.assertIn("pinchDistance", graph)
        self.assertIn("prefers-reduced-motion: reduce", self.js)
        edge = graph[graph.index("    drawEdge(edge) {"):graph.index("    drawNode(node) {")]
        self.assertIn("this.hoveredEdge === edge.data.id", edge)
        self.assertIn("this.selected === edge.data.id", edge)
        self.assertNotRegex(edge, r"fillText\(edge\.data\.label[^}]+\}\s*$")
        self.assertRegex(self.css, r"\.brainwatch-view\.navigation-collapsed")
        self.assertIn("var(--eve-surface-raised)", self.css)
        self.assertIn("text-shadow", self.css)
        self.assertIn("shadowBlur=24", graph)
        self.assertIn("rememberBrainwatchFocus(nodeId)", self.js)
        self.assertIn("renderBrainwatchPath()", self.js)
        self.assertRegex(self.css, r"\.brainwatch-path\s*\{")

    def test_brainwatch_v12_spatial_grammar_progressive_disclosure_and_distance_light(self):
        self.element("brainwatchGroups")
        graph = self.js[self.js.index("const BRAINWATCH_SPATIAL_GROUPS"):self.js.index("const metric")]
        for key, direction in (
            ("origin", "left"), ("consequence", "right"),
            ("context", "up"), ("retrieval", "down"),
        ):
            self.assertRegex(graph, rf'{key}:\s*\{{[^}}]*direction:\s*"{direction}"')
        self.assertIn("brainwatchSpatialGroup(edge, focusId)", graph)
        self.assertIn('edge.category === "retrieval"', graph)
        self.assertIn("BRAINWATCH_CONTAINER_RELATIONS", graph)
        self.assertIn("!introduced.has(otherId)", graph)
        self.assertIn("node.pinned", graph)
        self.assertIn("node.spatialGroup = group", graph)
        self.assertIn("ensureFocusVisible()", graph)
        self.assertIn("graphDistances()", graph)
        self.assertIn("distance === 1 ? .48 : distance === 2 ? .2 : .07", graph)
        self.assertIn("neighbor ? .88 : distance === 2 ? .48 : .16", graph)
        self.assertIn("BRAINWATCH_DIRECT_LIMIT = 5", graph)
        self.assertIn("BRAINWATCH_INITIAL_GROUP_LIMIT = 2", graph)
        self.assertIn("brainwatchGroupSlice(nodeId, group, BRAINWATCH_INITIAL_GROUP_LIMIT)", graph)
        self.assertIn("group.edges.slice(group.revealed, group.revealed + count)", graph)
        self.assertIn("brainwatchPendingGroups", graph)
        self.assertIn("groupedBrainwatchPayload(data, nodeId)", graph)
        self.assertIn("renderBrainwatchGroups(nodeId)", graph)
        self.assertIn("brainwatchGraph.merge(payload, nodeId)", graph)
        self.assertIn("brainwatchPendingGroups.delete(focused)", self.js)
        self.assertIn("brainwatchPendingGroups.clear()", self.js)
        self.assertRegex(self.css, r"\.brainwatch-groups\s*\{[^}]*position:\s*absolute")
        self.assertIn(".brainwatch-group.group-origin", self.css)
        self.assertIn(".brainwatch-group.group-retrieval", self.css)

        focus = function_body(self.js, "focusBrainwatchNode")
        self.assertNotRegex(focus, r"method\s*:\s*['\"](?:POST|PATCH|DELETE)")
        graph_class = self.js[self.js.index("class BrainwatchGraph"):self.js.index("  const brainwatchGraph")]
        self.assertNotIn("localStorage", graph_class)

    def test_brainwatch_focused_causal_layout_and_progressive_continuation(self):
        graph_start = self.js.index("class BrainwatchGraph")
        graph = self.js[graph_start:self.js.index("  const brainwatchGraph", graph_start)]
        layout = graph[graph.index("    layoutFocusedNeighborhood()"):graph.index("    ensureFocusVisible()")]
        self.assertIn("move(focus, 0, 0, 0", layout)
        self.assertIn("origin: new Map()", layout)
        self.assertIn("consequence: new Map()", layout)
        self.assertIn("context: new Map()", layout)
        self.assertIn("retrieval: new Map()", layout)
        self.assertIn("brainwatchSpatialGroup(edge.data, this.focus)", layout)
        self.assertIn("assignedDirect", layout)
        self.assertIn("secondByParent", layout)
        self.assertIn("node.layoutDepth = depth", layout)
        self.assertIn("node.layoutParent = parentId", layout)

        self.assertIn("this.positionGroupOverlay()", graph)
        self.assertIn("drawLaneGuides(ctx)", graph)
        self.assertIn("drawContinuationStubs(ctx)", graph)
        self.assertIn('elements.brainwatchGroups.style.left = `${left}px`', graph)
        self.assertIn('elements.brainwatchGroups.style.bottom = "12px"', graph)
        self.assertRegex(self.css, r"\.brainwatch-groups\s*\{[^}]*bottom:\s*12px")
        self.assertIn("HERKUNFT", graph)
        self.assertIn("FOLGEN", graph)
        self.assertIn("KONTEXT", graph)
        self.assertIn("RETRIEVAL", graph)
        self.assertIn("remaining <= 0", graph)
        self.assertIn("ctx.setLineDash([3, 5])", graph)

        edge = graph[graph.index("    drawEdge(edge) {"):graph.index("    drawNode(node) {")]
        self.assertIn("Math.abs(p2.x-p1.x) >= Math.abs(p2.y-p1.y)", edge)
        self.assertIn("ctx.bezierCurveTo(p1.x, (p1.y+p2.y)/2", edge)
        self.assertIn("distance === 1 ? .48 : distance === 2 ? .2 : .07", edge)
        self.assertIn("if (distance === 1) ctx.setLineDash([4, 6])", edge)
        self.assertIn("ctx.roundRect", edge)
        self.assertIn("node.pinned = true", graph)
        self.assertIn("prune(candidate, visited)", graph)
        self.assertNotIn("localStorage", graph)
        self.assertIn("WARUM VERBUNDEN?", self.js)
        self.assertIn("brainwatch-relation-summary", self.js)
        self.assertRegex(self.css, r"\.brainwatch-relation-summary\s*\{")

    def test_brainwatch_v11_controls_only_change_local_graph_state(self):
        for name in ("updateBrainwatchControls", "selectBrainwatchGraphItem", "setBrainwatchOpen"):
            body = function_body(self.js, name)
            self.assertNotRegex(body, r"method\s*:\s*['\"](?:POST|PATCH|DELETE)")
        graph_start = self.js.index("class BrainwatchGraph")
        self.assertNotIn("localStorage", self.js[graph_start:self.js.index("  const brainwatchGraph", graph_start)])
        self.assertNotIn("/api/message", function_body(self.js, "focusBrainwatchNode"))

    def test_eve_visual_system_v1_exposes_semantic_tokens_and_primitives(self):
        required_tokens = {
            "--eve-bg-deep", "--eve-bg", "--eve-surface", "--eve-surface-raised",
            "--eve-surface-solid", "--eve-border-subtle", "--eve-border-active",
            "--eve-text-primary", "--eve-text-secondary", "--eve-text-muted",
            "--eve-accent", "--eve-success", "--eve-warning", "--eve-error",
            "--eve-unavailable", "--eve-glow-none", "--eve-glow-subtle",
            "--eve-glow-active", "--eve-glow-focus", "--eve-glow-intense",
            "--eve-space-xs", "--eve-space-sm", "--eve-space-md", "--eve-space-lg",
            "--eve-radius-control", "--eve-radius-panel", "--eve-radius-focus",
            "--eve-font-ui", "--eve-font-tech", "--eve-motion-fast",
            "--eve-motion-normal", "--eve-motion-focus", "--eve-ease",
        }
        for token in required_tokens:
            self.assertIn(f"{token}:", self.css)
        for selector in (
            ".eve-surface", ".eve-panel", ".eve-toolbar", ".eve-glow-focus",
            ".eve-button", ".eve-icon-button", ".eve-input", ".eve-select",
            ".eve-badge", ".eve-status", ".eve-inspector-section",
            ".eve-intensity-low", ".eve-intensity-medium", ".eve-intensity-high",
        ):
            self.assertIn(selector, self.css)
        self.assertIn('[data-status="success"]', self.css)
        self.assertIn('[data-status="warning"]', self.css)
        self.assertIn('[data-status="error"]', self.css)
        self.assertIn('[data-status="unavailable"]', self.css)

    def test_brainwatch_uses_visual_system_without_changing_view_contracts(self):
        brainwatch = re.search(r'(?s)<section class="([^"]+)" id="brainwatchView".*?</section>', self.html)
        self.assertIsNotNone(brainwatch)
        self.assertIn("eve-surface", brainwatch.group(1))
        self.assertIn("eve-intensity-high", brainwatch.group(1))
        for class_name in ("eve-panel", "eve-toolbar", "eve-button", "eve-input", "eve-icon-button"):
            self.assertIn(class_name, brainwatch.group(0))
        self.assertIn("var(--eve-border-subtle)", self.css)
        self.assertIn("var(--eve-view-glow)", self.css)
        documentation = (PROJECT_ROOT / "docs" / "EVE-VISUAL-SYSTEM-V1.md").read_text(encoding="utf-8")
        for principle in ("Glow-Hierarchie", "Intensität nach Oberfläche", "Typografie", "Motion", "Regeln für neue Ansichten"):
            self.assertIn(principle, documentation)

    def test_text_response_is_rendered_before_correlated_postprocessing(self):
        submit = function_body(self.js, "submitMessage")
        follow = function_body(self.js, "followTurnCompletion")
        self.assertLess(submit.index("setReply(streamedText)"), submit.index("followTurnCompletion(data)"))
        self.assertIn("result.turn_id !== data.turn_id", follow)
        self.assertIn('result.status === "complete"', follow)
        self.assertIn("Textantwort bleibt sichtbar", self.js)

    def test_text_response_stream_reuses_one_throttled_assistant_message(self):
        submit = function_body(self.js, "submitMessage")
        self.assertIn('fetchWithTimeout("/api/message/stream"', submit)
        self.assertIn('["preview_delta", "delta"].includes(event.type)', submit)
        self.assertIn('event.type === "preview_reset"', submit)
        self.assertIn('event.type === "preview_commit"', submit)
        self.assertIn("if (!streamingMessage)", submit)
        self.assertIn("window.setTimeout(() => paintStream(false), 50)", submit)
        self.assertIn("renderAssistantMarkdown(content, streamedText)", submit)
        self.assertNotIn("content.textContent = streamedText", submit)
        self.assertIn('event.type === "complete"', submit)
        self.assertNotIn(
            "if (streamedText && streamedText !== data.answer) streamedText = data.answer",
            submit,
        )
        self.assertIn("if (!streamedText) streamedText = data.answer", submit)
        self.assertIn("const hasPublishedAnswer = Boolean(streamedText)", submit)
        self.assertIn('streamingMessage?.classList.add("failed")', submit)

    def test_provider_reasoning_is_live_collapsible_and_linked_to_answer(self):
        submit = function_body(self.js, "submitMessage")
        resume = function_body(self.js, "resumeBackendTurn")
        voice = function_body(self.js, "stopPTT")
        append_reasoning = function_body(self.js, "appendLiveReasoning")
        finish_reasoning = function_body(self.js, "finishLiveReasoning")
        disclosure = function_body(self.js, "createReasoningDisclosure")
        attach = function_body(self.js, "attachReasoningLink")
        create_message = function_body(self.js, "createMessageNode")
        for source, marker in (
            (submit, 'event.type === "reasoning_delta"'),
            (resume, 'event.type === "reasoning_delta"'),
            (voice, 'streamEvent.type === "reasoning_delta"'),
        ):
            self.assertIn(marker, source)
            self.assertIn("appendLiveReasoning(reasoning", source)
            self.assertIn("attachReasoningLink(reasoning", source)
        self.assertIn('document.createElement("details")', append_reasoning)
        self.assertIn('summary.textContent = "EVE denkt …"', append_reasoning)
        self.assertIn("content.textContent = state.text", append_reasoning)
        self.assertIn("state.content.scrollTop = state.content.scrollHeight", append_reasoning)
        self.assertIn("state.details.open = false", finish_reasoning)
        self.assertIn('state.badge.textContent = outcome === "cancelled"', finish_reasoning)
        self.assertIn('summary.setAttribute("aria-label", "EVEs Gedankengang anzeigen")', disclosure)
        self.assertIn('document.createElementNS("http://www.w3.org/2000/svg", "svg")', disclosure)
        self.assertIn("content.textContent = reasoning", disclosure)
        self.assertIn("state.article?.remove()", attach)
        self.assertIn("message.metadata?.reasoning", create_message)
        self.assertIn("createReasoningDisclosure(storedReasoning)", create_message)
        self.assertIn(".live-reasoning-details", self.css)
        self.assertIn(".live-reasoning-details::before", self.css)
        self.assertIn("reasoning-cloud-breathe", self.css)
        self.assertIn(".message-reasoning-icon", self.css)
        self.assertIn(".message-reasoning-content", self.css)
        self.assertNotIn("createMessageNode", append_reasoning)

    def test_brainwatch_controls_interruptible_conversation_learning(self):
        render = function_body(self.js, "renderBrainwatchStatistics")
        load = function_body(self.js, "loadBrainwatchStatistics")
        self.assertIn('"Lernen aus Gesprächen"', render)
        self.assertIn('control("JETZT LERNEN", "run_now"', render)
        self.assertIn('control("PAUSIEREN", "pause"', render)
        self.assertIn('control("FORTSETZEN", "resume"', render)
        self.assertIn('"/api/brainwatch/conversation-learning"', render)
        self.assertIn('"/api/brainwatch/conversation-learning"', load)
        self.assertIn("conversation-learning-controls", self.css)
        self.assertIn('control("FEHLER WIEDERHOLEN", "retry_failed"', render)
        self.assertIn('"Mit persistierter Evidenz"', render)
        self.assertIn("learning.evidence_records", render)
        self.assertIn("learning.evidenced_claims", render)
        self.assertIn("learning.applied_without_evidence", render)
        self.assertIn('"Inkonsistente Lernläufe"', render)

    def test_conversation_learning_results_drill_into_persisted_claims_in_neurocloud(self):
        loader = function_body(self.js, "loadConversationLearningResults")
        navigate = function_body(self.js, "showConversationLearningClaims")
        restore = function_body(self.js, "restoreMemoryCloudLearningHighlight")
        vendor = (WEB_ROOT / "vendor" / "neurocloud-webgl-v1.js").read_text(encoding="utf-8")
        for element_id in (
            "memoryCloudLearningFocus", "memoryCloudLearningTitle",
            "memoryCloudLearningDetail", "memoryCloudLearningClear",
        ):
            self.element(element_id)
        self.assertIn('view: "jobs"', loader)
        self.assertIn("conversationLearningJobCard(item)", loader)
        self.assertIn('setBrainwatchMode("memory", { load: false })', navigate)
        self.assertIn('setMemoryExplorerSubview("cloud", { load: false })', navigate)
        self.assertIn("memoryCloudLearningHighlight", navigate)
        self.assertIn("setHighlightedClaims", restore)
        self.assertIn("setHighlightedClaims(ids", vendor)
        self.assertIn("clearHighlightedClaims()", vendor)
        self.assertIn("this.highlightedClaims.has(node.id)", vendor)
        self.assertIn("Claim aus geöffnetem Lernergebnis", self.html)
        self.assertIn(".conversation-learning-results", self.css)
        self.assertIn(".memory-cloud-learning-focus", self.css)
        self.assertIn(".brainwatch-view button.brainwatch-statistic-card.is-interactive", self.css)
        self.assertIn(".brainwatch-statistic-card.is-textual strong", self.css)

    def test_voice_and_reconnected_streams_render_live_markdown(self):
        voice = function_body(self.js, "stopPTT")
        resume = function_body(self.js, "resumeBackendTurn")
        self.assertIn(
            'renderAssistantMarkdown(assistantNode.querySelector(".message-content"), answer)',
            voice,
        )
        self.assertIn("window.setTimeout(paintVoiceAnswer, 50)", voice)
        self.assertIn(
            'renderAssistantMarkdown(node.querySelector(".message-content"), answer)',
            resume,
        )
        self.assertIn("window.setTimeout(paintResumedAnswer, 50)", resume)
        self.assertIn("answer && answer !== result.answer", resume)
        self.assertIn('node?.classList.add("failed")', resume)
        self.assertIn("answer && answer !== data.answer", voice)

    def test_nerd_mode_exposes_measured_stream_and_segment_milestones(self):
        render = function_body(self.js, "renderNerdTurns")
        for field in (
            "first_text_chunk_ms", "text_stream_end_ms", "tts_first_segment_ms",
            "tts_segment_count", "first_audio_ready_ms", "answer_committed_at",
        ):
            self.assertIn(field, render)

    def test_nerd_mode_exposes_minimal_decision_state(self):
        render = function_body(self.js, "renderNerdTurns")
        for field in (
            "Entscheidungsweg", "Erste Entscheidung", "Letzte Entscheidung",
            "Capability", "Operation", "Wirkung", "Semantische Entscheidungen",
        ):
            self.assertIn(field, render)
        self.assertIn('step.component === "minimal"', render)
        self.assertIn('step.operation === "decision"', render)

    def test_nerd_mode_badge_uses_the_operational_turn_outcome(self):
        render = function_body(self.js, "renderNerdTurns")
        self.assertIn("turn.summary?.final_turn_state", render)
        self.assertIn('finalTurnState === "operational_resolved"', render)
        self.assertIn('finalTurnState === "operational_unresolved"', render)
        self.assertIn('status.textContent = displayedStatus', render)
        self.assertIn(".nerd-status.warning", self.css)

    def test_nerd_mode_displays_stream_ttft_and_generation_duration(self):
        render = function_body(self.js, "renderNerdTurns")
        rate_presentation = function_body(self.js, "tokenRatePresentation")
        self.assertIn('"TTFT"', render)
        self.assertIn("call.ttft_ms", render)
        self.assertIn('"Generierungsdauer"', render)
        self.assertIn("call.generation_ms", render)
        self.assertIn('"Turn-ID"', render)
        self.assertIn('"Backend-Status"', render)
        self.assertIn('"Output / Request"', rate_presentation)
        self.assertIn('"Outputrate (Gesamtrequest)"', rate_presentation)
        self.assertIn('"Provider-Rate"', rate_presentation)
        self.assertIn('"Tok/s-Messbasis"', render)
        self.assertNotIn('addHudMetric("Generation"', render)

    def test_nerd_mode_renders_backend_knowledge_flow_without_classification(self):
        renderer = function_body(self.js, "renderKnowledgeFlow")
        self.assertIn("turn.knowledge_flow?.stages", renderer)
        self.assertIn("for (const [index, stage] of stages.entries())", renderer)
        self.assertIn("stage.summary", renderer)
        self.assertIn("stage.details", renderer)
        self.assertNotRegex(renderer, r"includes\(|match\(|RegExp|keyword")
        self.assertIn("knowledgeFlow = renderKnowledgeFlow(turn, openDetails)", self.js)
        self.assertIn(".knowledge-flow", self.css)
        self.assertIn(".knowledge-node.not_supported", self.css)
        self.assertIn('content: " · nicht belegt"', self.css)

    def test_nerd_mode_v2_uses_existing_measurements_as_mission_control(self):
        timeline = function_body(self.js, "renderTurnTimeline")
        measured = function_body(self.js, "measuredTimeline")
        modules = function_body(self.js, "renderSystemModules")
        render = function_body(self.js, "renderNerdTurns")
        self.assertIn("item.start / extent * 100", timeline)
        self.assertIn("item.duration / extent * 100", timeline)
        self.assertIn('" hotspot"', timeline)
        self.assertIn("turn.steps || []", measured)
        self.assertIn("turn.llm_calls || []", measured)
        self.assertIn("turn.knowledge_flow?.stages?.length", modules)
        self.assertIn('eyebrow.textContent = "TURN HUD"', render)
        self.assertIn('knowledgeTitle.textContent = "Knowledge Flow"', render)
        self.assertIn('summary.textContent = "Deep Telemetry"', render)
        self.assertIn("call.ttft_ms == null ? null", render)
        self.assertIn(".nerd-hud-metric.primary", self.css)
        self.assertIn(".nerd-timeline-bar.hotspot", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)

    def test_backend_turn_is_saved_for_reload_and_reconnected(self):
        submit = function_body(self.js, "submitMessage")
        resume = function_body(self.js, "resumeBackendTurn")
        self.assertIn('event.type === "accepted"', submit)
        self.assertIn('localStorage.setItem("eve.activeBackendTurn"', submit)
        self.assertIn('localStorage.removeItem("eve.activeBackendTurn")', submit)
        self.assertIn('localStorage.getItem("eve.activeBackendTurn")', resume)
        self.assertIn('/api/message/stream/${encodeURIComponent(turnId)}', resume)
        self.assertIn('["preview_delta", "delta"].includes(event.type)', resume)
        self.assertIn('event.type === "complete"', resume)
        catch_block = submit[submit.index("} catch (error) {"):]
        self.assertIn('localStorage.removeItem("eve.activeBackendTurn")', catch_block)

    def test_timeout_rollover_switches_visible_chat_on_turn_acceptance(self):
        submit = function_body(self.js, "submitMessage")
        voice = function_body(self.js, "stopPTT")
        for source, accepted_marker, input_marker in (
            (submit, 'event.type === "accepted"', 'event.type === "input"'),
            (voice, 'streamEvent.type === "accepted"', 'streamEvent.type === "transcript"'),
        ):
            with self.subTest(accepted_marker=accepted_marker):
                accepted = source.index(accepted_marker)
                switch = source.index("event.conversation_id", accepted) if source is submit else source.index("streamEvent.conversation_id", accepted)
                load = source.index("await loadConversations(activeConversationId)", switch)
                self.assertLess(accepted, switch)
                self.assertLess(load, source.index(input_marker, accepted))

    def test_selected_browser_chat_does_not_roll_over_at_server_timeout(self):
        scheduler = function_body(self.js, "scheduleConversationRollover")
        lifecycle = function_body(self.js, "synchronizeConversationLifecycle")
        selector = function_body(self.js, "selectConversation")
        self.assertIn("configured_session_timeout_seconds", scheduler)
        self.assertIn("idle_time_seconds", scheduler)
        self.assertIn("synchronizeConversationLifecycle()", scheduler)
        self.assertIn('"/api/conversations/active"', lifecycle)
        self.assertIn("scheduleConversationRollover(data.lifecycle)", lifecycle)
        self.assertIn("await loadConversations(activeConversationId)", lifecycle)
        self.assertIn("explicitConversationResume = true", selector)
        self.assertIn("if (explicitConversationResume) return", lifecycle)
        self.assertIn("clearTimeout(conversationRolloverTimer)", selector)
        self.assertIn(".then(() => synchronizeConversationLifecycle())", self.js)

    def test_voice_transcript_uses_backend_stream_before_answer_completion(self):
        stop = function_body(self.js, "stopPTT")
        ensure = function_body(self.js, "ensureBackendUserMessage")
        resume = function_body(self.js, "resumeBackendTurn")
        self.assertIn("/api/turn/stream", stop)
        self.assertIn('streamEvent.type === "transcript"', stop)
        self.assertLess(stop.index('streamEvent.type === "transcript"'), stop.index('streamEvent.type === "complete"'))
        self.assertIn("ensureBackendUserMessage(turnId, streamEvent.content)", stop)
        self.assertIn("node.dataset.backendTurnId === turnId", ensure)
        self.assertIn("latest?.querySelector", ensure)
        self.assertIn('event.type === "transcript"', resume)

    def test_explicit_cancel_targets_active_backend_turn_and_handles_terminal_event(self):
        cancel = function_body(self.js, "cancelActiveBackendTurn")
        submit = function_body(self.js, "submitMessage")
        resume = function_body(self.js, "resumeBackendTurn")
        stop = function_body(self.js, "stopPTT")
        self.assertIn('/api/backend-turns/${encodeURIComponent(turnId)}/cancel', cancel)
        self.assertIn('method: "POST"', cancel)
        self.assertIn("backendTurnCancellable = false", cancel)
        self.assertIn('event.type === "cancelled"', submit)
        self.assertIn('event.type === "cancelled"', resume)
        self.assertIn('streamEvent.type === "cancelled"', stop)
        self.assertIn('removeItem("eve.activeBackendTurn")', submit)

    def test_streaming_voice_audio_is_queued_by_turn_and_cancel_stops_it(self):
        stop = function_body(self.js, "stopPTT")
        resume = function_body(self.js, "resumeBackendTurn")
        cancel = function_body(self.js, "cancelActiveBackendTurn")
        play = function_body(self.js, "playReply")
        queue = function_body(self.js, "queueReply")
        self.assertIn('streamEvent.type === "audio"', stop)
        self.assertIn("streamEvent.turn_id", stop)
        self.assertIn('event.type === "audio"', resume)
        self.assertIn("cancelTurnAudio(turnId)", cancel)
        self.assertIn("cancelledAudioTurns.has(turnId)", play)
        self.assertIn("playReply(bytes, turnId)", queue)

    def test_presentation_work_status_is_transient_and_correlated_to_its_turn(self):
        start = function_body(self.js, "startPresentationTurnStatus")
        clear = function_body(self.js, "clearPresentationTurnStatus")
        restore = function_body(self.js, "restorePresentationTurnStatuses")
        follow = function_body(self.js, "followTurnCompletion")
        render = function_body(self.js, "renderMessages")
        self.assertIn("data.presentation_pending", start)
        self.assertIn("data.assistant_message_id", start)
        self.assertIn("presentationTurnStates.set(data.turn_id", start)
        self.assertIn("presentationTurnStates.delete(turnId)", clear)
        self.assertIn("node.dataset.turnId === turnId", clear)
        self.assertIn("presentationTurnStates.forEach", restore)
        self.assertIn("restorePresentationTurnStatuses()", render)
        self.assertIn("startPresentationTurnStatus(data)", follow)
        self.assertIn('presentationStatus !== "pending"', follow)
        self.assertIn('result.presentation.action !== "none"', follow)
        self.assertIn("clearPresentationTurnStatus(data.turn_id)", follow)
        self.assertIn("Darstellung wird vorbereitet …", self.js)
        self.assertRegex(self.css, r"\.presentation-work-status\s*\{")
        self.assertNotIn("presentation-work-status", self.html)

    def test_presentation_work_status_lifecycle_covers_all_terminal_outcomes(self):
        submit = function_body(self.js, "submitMessage")
        follow = function_body(self.js, "followTurnCompletion")
        self.assertLess(submit.index("setReply(streamedText)"), submit.index("followTurnCompletion(data)"))
        self.assertLess(submit.index("await loadConversations"), submit.index("followTurnCompletion(data)"))
        self.assertIn('presentationStatus === "success"', follow)
        self.assertIn('result.presentation.action !== "none"', follow)
        self.assertIn("await loadPresentation()", follow)
        self.assertIn('presentationStatus === "error"', follow)
        self.assertIn("latestVisibleTurnId === data.turn_id", follow)
        self.assertNotIn("renderMessages", follow)
        self.assertNotIn("replaceChildren", follow)

    def test_overlapping_presentation_statuses_use_independent_turn_keys(self):
        start = function_body(self.js, "startPresentationTurnStatus")
        clear = function_body(self.js, "clearPresentationTurnStatus")
        render = function_body(self.js, "renderPresentationTurnStatus")
        self.assertIn("presentationTurnStates.set(data.turn_id", start)
        self.assertIn("presentationTurnStates.delete(turnId)", clear)
        self.assertIn("node.dataset.turnId === turnId", clear)
        self.assertIn("indicator.dataset.turnId = state.turnId", render)
        self.assertIn("state.messageId", render)
        self.assertNotIn("latestVisibleTurnId", clear)

    def test_generic_output_layer_is_separate_and_mutually_exclusive_with_nerd_mode(self):
        for element_id in ("presentationView", "presentationTitle", "presentationComponents", "presentationClose"):
            self.assertIn(f'id="{element_id}"', self.html)
        render = function_body(self.js, "renderPresentation")
        nerd = function_body(self.js, "setNerdMode")
        self.assertIn("setNerdMode(false)", render)
        self.assertIn("presentationView.hidden", nerd)
        self.assertIn('fetchWithTimeout("/api/presentation"', self.js)
        self.assertNotRegex(render, r"innerHTML\s*=")
        for component in ("text", "markdown", "image", "video", "metric", "progress", "badge", "list", "table", "chart", "divider", "container"):
            self.assertIn(f'"{component}"', self.js)

    def test_output_layer_does_not_replace_chat_audio_or_pointer_controls(self):
        self.assertIn('id="conversation"', self.html)
        self.assertIn('id="composer"', self.html)
        self.assertIn('id="ptt"', self.html)
        self.assertIn('elements.ptt.addEventListener("pointerdown"', self.js)
        self.assertIn('elements.ptt.setPointerCapture(event.pointerId)', self.js)
        self.assertNotRegex(self.css, r"body\.presentation-open\s+\.(?:command-dock|composer|share-toggle)\s*\{[^}]*display:\s*none")

    def test_inline_presentation_media_uses_released_blob_urls(self):
        resource = function_body(self.js, "presentationResource")
        release = function_body(self.js, "releasePresentationResources")
        render = function_body(self.js, "renderPresentation")
        self.assertIn("URL.createObjectURL", resource)
        self.assertIn("new Blob", resource)
        self.assertIn("URL.revokeObjectURL", release)
        self.assertIn("releasePresentationResources()", render)

    def test_same_origin_presentation_media_is_fetched_and_errors_are_visible(self):
        loader = function_body(self.js, "loadPresentationMedia")
        renderer = function_body(self.js, "renderPresentationComponent")
        self.assertIn("fetchWithTimeout", loader)
        self.assertIn("response.blob()", loader)
        self.assertIn("response.status", loader)
        self.assertIn("expectedMediaType", loader)
        self.assertIn("receivedType", loader)
        self.assertIn("presentationRenderGeneration", loader)
        self.assertIn('addEventListener("load"', loader)
        self.assertIn('addEventListener("error"', loader)
        self.assertIn("media.naturalWidth", loader)
        self.assertIn("media.style.aspectRatio", loader)
        self.assertIn("window.createImageBitmap", loader)
        self.assertIn('document.createElement("canvas")', loader)
        self.assertIn('getContext("2d").drawImage', loader)
        self.assertNotIn("3000", loader)
        self.assertLess(loader.index("window.createImageBitmap"), loader.index('addEventListener("load"'))
        self.assertIn("component-media-error", renderer)
        self.assertIn("loadPresentationMedia", renderer)
        self.assertIn("component.type", renderer)

    def test_saved_and_presentation_images_open_original_view_and_can_download(self):
        message = function_body(self.js, "createMessageNode")
        viewer = function_body(self.js, "openImageViewer")
        expandable = function_body(self.js, "makeImageExpandable")
        loader = function_body(self.js, "loadPresentationMedia")
        self.assertIn("openImageViewer(attachment.url, filename)", message)
        self.assertIn("elements.imageViewerImage.src = source", viewer)
        self.assertIn("elements.imageViewerDownload.href = source", viewer)
        self.assertIn("elements.imageViewerDownload.download", viewer)
        self.assertIn("openImageViewer(source, filename)", expandable)
        self.assertIn("makeImageExpandable(canvas, objectUrl", loader)
        self.assertIn('id="imageViewerDownload"', self.html)
        self.assertIn('class="image-viewer-stage"', self.html)

    def test_structured_lists_render_as_semantic_rows_without_raw_json(self):
        renderer = function_body(self.js, "renderPresentationComponent")
        self.assertIn('list.className = "component-list"', renderer)
        self.assertIn('entry.className = "component-list-row"', renderer)
        self.assertIn('label.className = "component-list-label"', renderer)
        self.assertIn('value.className = "component-list-value"', renderer)
        self.assertIn('entry.className = "component-list-item"', renderer)
        self.assertIn("Nicht unterstützter Listeneintrag", renderer)
        self.assertNotIn("JSON.stringify(item)", renderer)
        rows = css_declarations(self.css, ".component-list-row")
        self.assertIn("display: grid", rows)
        self.assertIn("grid-template-columns:", rows)

    def test_vertical_output_uses_an_asymmetric_media_workspace(self):
        vertical = css_declarations(self.css, ".presentation-components.layout-vertical")
        bitmap = css_declarations(
            self.css, ".presentation-components.layout-vertical > .component-image .presentation-bitmap",
        )
        self.assertIn("align-items: center", vertical)
        self.assertIn("width: 100%", bitmap)
        self.assertRegex(
            self.css,
            r"\.presentation-components\.layout-vertical:has\([^}]+\)\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:",
        )
        self.assertRegex(
            self.css,
            r"@media \(max-width:\s*1050px\)[\s\S]*?\.presentation-components\.layout-vertical:has\([^}]+\)\s*\{[^}]*display:\s*flex",
        )

    def test_output_motion_is_subtle_and_respects_reduced_motion(self):
        self.assertIn("@keyframes presentation-arrive", self.css)
        self.assertIn("@keyframes presentation-scan", self.css)
        self.assertIn("@keyframes presentation-signal", self.css)
        self.assertRegex(self.css, r"@media \(prefers-reduced-motion:\s*reduce\)")
        reduced_motion = self.css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        self.assertIn("animation: none", reduced_motion)

    def test_output_motion_has_a_persistent_nerd_menu_toggle(self):
        for element_id in ("presentationMotionToggle", "presentationMotionState"):
            self.assertIn(f'id="{element_id}"', self.html)
        toggle = function_body(self.js, "setPresentationMotion")
        self.assertIn('localStorage.setItem("eve.presentationMotion"', toggle)
        self.assertIn("motion-off", toggle)
        self.assertIn('presentationMotionToggle.addEventListener("click"', self.js)
        self.assertRegex(
            self.css,
            r"body\.motion-off[\s\S]*?animation:\s*none\s*!important[\s\S]*?transition:\s*none\s*!important",
        )
        self.assertIn("systemReducedMotionQuery.matches || !presentationMotion", self.js)

    def test_output_layer_reflows_beside_chat_and_uses_compact_chromeless_surface(self):
        presentation = css_declarations(self.css, ".presentation-view")
        heading = css_declarations(self.css, ".presentation-head h1")
        root_image = css_declarations(
            self.css, ".presentation-components > .component-image",
        )
        self.assertIn("border: 0", presentation)
        self.assertIn("box-shadow: none", presentation)
        self.assertIn("font-size: 18px", heading)
        self.assertIn("border: 0", root_image)
        self.assertRegex(
            self.css,
            r"body\.chat-open \.presentation-view\s*\{[^}]*right:\s*min\(calc\(32px \+ var\(--chat-total-width\)\)",
        )
        self.assertRegex(
            self.css,
            r"body\.chat-open\.sidebar-hidden \.presentation-view\s*\{[^}]*right:\s*min\(calc\(32px \+ var\(--active-chat-width\)\)",
        )
        self.assertRegex(
            self.css,
            r"body\.presentation-open \.state-readout\s*\{[^}]*opacity:\s*0",
        )

    def test_conversation_history_renders_persisted_attachments_and_tool_events(self):
        create_message = function_body(self.js, "createMessageNode")
        self.assertIn("message.attachments", create_message)
        self.assertIn("attachment.url", create_message)
        self.assertIn("message.tool_events", create_message)
        self.assertIn("Tool-Ereignis", create_message)

    def test_returning_from_brainwatch_scrolls_chat_to_latest_message(self):
        scroll = function_body(self.js, "scrollChatToLatest")
        brainwatch = function_body(self.js, "setBrainwatchOpen")
        chat = function_body(self.js, "setChatOpen")
        render = function_body(self.js, "renderMessages")
        append = function_body(self.js, "appendChatMessage")
        self.assertIn("scrollTop = elements.chatMessages.scrollHeight", scroll)
        self.assertGreaterEqual(scroll.count("window.requestAnimationFrame"), 2)
        self.assertIn("window.cancelAnimationFrame(chatScrollFrame)", scroll)
        self.assertIn("scrollChatToLatest()", brainwatch)
        self.assertIn("scrollChatToLatest()", chat)
        self.assertIn("scrollChatToLatest()", render)
        self.assertIn("scrollChatToLatest()", append)
        self.assertIn(".message-attachments", self.css)
        self.assertIn(".message-tool-events", self.css)

    def test_tool_events_offer_individual_and_collection_raw_data_copy(self):
        create_message = function_body(self.js, "createMessageNode")
        self.assertIn("createDiagnosticCopyControl(toolEvent)", create_message)
        self.assertIn('createDiagnosticCopyControl(toolEvents, "Alle Rohdaten kopieren")', create_message)
        self.assertIn("toolEvents.length > 1", create_message)
        self.assertIn(".diagnostic-copy-control", self.css)
        self.assertIn(".diagnostic-copy-button", self.css)

    def test_successful_semantic_actions_offer_reversible_direct_feedback(self):
        renderer = function_body(self.js, "createMessageNode")
        feedback = function_body(self.js, "createActionFeedbackControl")
        self.assertIn("createActionFeedbackControl(message)", renderer)
        self.assertIn('turn_state === "operational_resolved"', feedback)
        self.assertIn("details?.operational_execution === true", feedback)
        self.assertIn("semantic_link_candidate_id", feedback)
        self.assertIn('button("👍", `${subject} war hilfreich / korrekt`, "correct")', feedback)
        self.assertIn('button("👎", `${subject} war nicht hilfreich / falsch`, "", () => {', feedback)
        self.assertIn('input.placeholder = "Was war falsch?', feedback)
        self.assertIn('submit("incorrect", explanation)', feedback)
        self.assertIn('data.feedback.explanation', feedback)
        self.assertIn('button("Rückgängig", "Bewertung rückgängig machen", "undo")', feedback)
        self.assertIn("/feedback", feedback)
        self.assertIn('const feedbackKey = semantic ? "semantic_feedback" : "answer_feedback"', feedback)
        self.assertIn('method: "POST"', feedback)
        self.assertIn("fetchWithTimeout", feedback)
        self.assertIn(".action-feedback", self.css)
        self.assertIn(".action-feedback-link", self.css)
        self.assertIn(".action-feedback-explanation-input", self.css)

    def test_diagnostic_copy_formats_real_data_and_never_calls_an_api(self):
        formatter = function_body(self.js, "formatDiagnosticJson")
        copier = function_body(self.js, "createDiagnosticCopyControl")
        self.assertIn("redactDiagnosticData(value)", formatter)
        self.assertIn("JSON.stringify", formatter)
        self.assertIn("navigator.clipboard.writeText(formatDiagnosticJson(value))", copier)
        self.assertNotIn("fetch", copier)
        self.assertIn('status.textContent = "Kopiert"', copier)
        self.assertIn("Kopieren fehlgeschlagen:", copier)
        self.assertIn("Keine Rohdaten verfügbar.", copier)

    def test_diagnostic_copy_redacts_nested_keys_and_secret_text(self):
        redactor = function_body(self.js, "redactDiagnosticData")
        text_redactor = self.js.split("function redactDiagnosticText", 1)[1].split(
            "function redactDiagnosticData", 1,
        )[0]
        self.assertIn("DIAGNOSTIC_SECRET_KEY.test(key)", redactor)
        self.assertIn("Object.entries(value)", redactor)
        self.assertIn("Bearer", text_redactor)
        self.assertIn("authorization", text_redactor)
        self.assertIn("DIAGNOSTIC_REDACTION", text_redactor)

    def test_nerdmode_copies_the_complete_turn_and_displays_redacted_json(self):
        renderer = function_body(self.js, "renderNerdTurns")
        self.assertIn("createDiagnosticCopyControl(turn)", renderer)
        self.assertIn("formatDiagnosticJson(turn)", renderer)
        self.assertIn('rawSummary.textContent = "Redigierte Rohdaten (JSON)"', renderer)

    def test_memory_explorer_is_integrated_as_a_read_only_brainwatch_mode(self):
        for element_id in (
            "brainwatchInfoMode", "brainwatchMemoryMode", "brainwatchInfoNavigation",
            "memoryExplorerNavigation", "memoryExplorerForm", "memoryExplorerSearch",
            "memoryExplorerScope", "memoryExplorerKind", "memoryExplorerLifecycle",
            "memoryExplorerStatus", "memoryExplorerResults", "memoryExplorerMore",
        ):
            self.element(element_id)

        reader = function_body(self.js, "memoryExplorerRead")
        browse = function_body(self.js, "loadMemoryClaims")
        focus = function_body(self.js, "focusMemoryClaim")
        self.assertIn("/api/brainwatch/memory/", reader)
        self.assertIn('cache: "no-store"', reader)
        self.assertIn("headers: auth", reader)
        self.assertNotRegex(reader + browse, r'method:\s*["\'](?:POST|PUT|PATCH|DELETE)')
        self.assertIn('new URLSearchParams({ limit: "20" })', browse)
        self.assertNotIn("if (!query)", browse)
        self.assertIn("/evidence?limit=20", self.js)
        self.assertIn("/relations?", self.js)

    def test_memory_graph_uses_persistent_claim_and_relation_identities(self):
        claim_node = function_body(self.js, "memoryClaimNode")
        relation_graph = function_body(self.js, "memoryRelationGraphPayload")
        inspector = function_body(self.js, "renderMemoryClaimInspector")
        self.assertIn('type: "claim"', claim_node)
        self.assertIn("id: claim.id", claim_node)
        self.assertIn("id: relation.id", relation_graph)
        self.assertIn("source: relation.from_claim.id", relation_graph)
        self.assertIn("target: relation.to_claim.id", relation_graph)
        self.assertIn("appendEvidenceCards", inspector)
        self.assertIn("appendRelationCards", inspector)
        self.assertIn("Eine vollständige Änderungshistorie ist nicht aufgezeichnet", inspector)
        self.assertIn(".memory-inspector-section", self.css)
        self.assertIn(".provenance-partial", self.css)
        self.assertNotIn("WebGLRenderer", self.js)

    def test_neurocloud_is_a_memory_subview_with_local_event_driven_webgl(self):
        for element_id in (
            "memoryCloudView", "memoryCloudWorkspace", "memoryCloudCanvas",
            "memoryCloudReset", "memoryCloudFocus", "memoryCloudOverview",
            "memoryCloudRelationType", "memoryCloudIntensity", "memoryCloudQuality", "memoryCloudStatus",
            "memoryCloudMore", "memoryCloudFallback",
        ):
            self.element(element_id)
        self.assertNotIn('id="memoryClaimsView"', self.html)
        self.assertNotIn('id="memoryGraphView"', self.html)
        vendor = (WEB_ROOT / "vendor" / "neurocloud-webgl-v1.js").read_text(encoding="utf-8")
        self.assertRegex(self.html, r'src="vendor/neurocloud-webgl-v1\.js(?:\?[^"]+)?"')
        self.assertNotRegex(self.html, r"https?://[^\"']*(?:three|webgl)")
        self.assertEqual(4, len(re.findall(r'id="brainwatch(?:Info|Memory|Semantic|Statistics)Mode"', self.html)))
        self.assertIn('getContext?.("webgl2"', vendor)
        self.assertIn("drawArraysInstanced", vendor)
        self.assertIn("drawArrays(gl.LINES", vendor)
        self.assertIn("requestRender()", vendor)
        self.assertNotIn("Math.random", vendor)
        self.assertIn("cancelAnimationFrame", vendor)
        self.assertIn("deleteBuffer", vendor)
        self.assertIn("ResizeObserver", vendor)
        self.assertIn("position_is_semantic", (PROJECT_ROOT / "src" / "eve_agent" / "brainwatch.py").read_text(encoding="utf-8"))

    def test_eve_avatar_reuses_real_neurocloud_with_depth_and_persisted_activity(self):
        avatar = self.element("eveAvatarCloud")
        self.assertEqual("canvas", avatar[0])
        self.assertIn("persistenten Claims und Relations", avatar[1].get("aria-label", ""))
        loader = function_body(self.js, "loadAvatarMemoryCloud")
        activity = function_body(self.js, "pollAvatarCloudActivity")
        apply_activity = function_body(self.js, "applyAvatarCloudActivity")
        impulse_queue = function_body(self.js, "queueAvatarCloudActivityEvents")
        renderer = function_body(self.js, "ensureAvatarMemoryCloud")
        brainwatch_renderer = function_body(self.js, "ensureMemoryCloud")
        self.assertIn("graph?${params}", loader)
        self.assertIn('node_limit: "160"', loader)
        self.assertIn('edge_limit: "320"', loader)
        self.assertIn('depth: "2"', loader)
        self.assertIn("graph/relations?${params}", loader)
        self.assertIn('limit: "200"', loader)
        self.assertIn("while (true)", loader)
        self.assertIn("seenCursors", loader)
        self.assertIn('params.set("cursor", cursor)', loader)
        self.assertIn("nodes.set(node.id, node)", loader)
        self.assertIn("edges.set(edge.id, edge)", loader)
        self.assertIn("page.nodes || []", loader)
        self.assertIn("page.edges || []", loader)
        self.assertIn('document.body.classList.toggle("memory-avatar-active"', loader)
        self.assertNotRegex(loader + activity, r'method:\s*["\'](?:POST|PUT|PATCH|DELETE)')
        self.assertIn("readMemoryCloudLivePage", activity)
        self.assertIn("projectRuntimeActivity", self.js)
        self.assertIn("animateActivityEvent(event)", self.js)
        self.assertIn("queueAvatarCloudActivityEvents(events)", apply_activity)
        self.assertIn("avatarCloudImpulseQueue.push(...events)", impulse_queue)
        self.assertIn("window.setTimeout(next, 220)", impulse_queue)
        self.assertIn("...BRAINWATCH_NEUROCLOUD_PROFILE", renderer)
        self.assertIn("...BRAINWATCH_NEUROCLOUD_PROFILE", brainwatch_renderer)
        self.assertIn('quality: "medium"', self.js)
        self.assertIn('intensity: 1', self.js)
        for avatar_only_override in ("cameraDistance", "fieldOfView"):
            self.assertNotIn(avatar_only_override, renderer)
        self.assertIn('intensity: .92', renderer)
        for shared_optical_setting in (
            "haloStrength",
            "fogStrength",
            "densityAwareExposure",
            "densityReference",
            "relationStrength",
            "additiveRelations",
            "boundedBaseBlend",
        ):
            self.assertNotIn(shared_optical_setting, renderer)
        self.assertIn('activityTimeScale: 2.2', renderer)
        self.assertIn('spatialShape: "brain"', renderer)
        self.assertNotIn('spatialShape: "brain"', brainwatch_renderer)
        self.assertIn('orbitMode: "sway"', renderer)
        self.assertIn('cameraYaw: -.12', renderer)
        self.assertNotIn('orbitMode: "sway"', brainwatch_renderer)
        self.assertIn('transparentBackground: true', renderer)
        self.assertIn('continuousAmbientMotion: true', renderer)
        self.assertIn('depthMotion: true', renderer)
        self.assertIn('powerPreference: "low-power"', renderer)
        avatar_css = css_declarations(self.css, ".eve-avatar-cloud")
        self.assertIn("filter: none", avatar_css)
        self.assertIn("mask-image: radial-gradient", avatar_css)
        self.assertIn("ellipse 50% 50%", avatar_css)
        self.assertIn("transparent 100%", avatar_css)
        self.assertIn("translateZ(18px)", avatar_css)
        self.assertIn("pointer-events: none", avatar_css)
        self.assertIn("width: 170%", avatar_css)
        self.assertIn("height: 145%", avatar_css)
        core_css = css_declarations(self.css, ".core-scene")
        self.assertIn("top: calc(var(--core-y) + var(--avatar-y-offset))", core_css)
        self.assertIn("width: calc(var(--core-size) * var(--avatar-stage-scale))", core_css)
        self.assertIn("--avatar-stage-scale: 1.2", self.css)
        self.assertIn("translateY(calc(var(--core-size) * -.708))", self.css)
        self.assertIn("body.memory-avatar-active #neural", self.css)
        self.assertIn('--core-y: 46dvh', self.css)
        self.assertIn('--core-y: 35dvh', self.css)
        self.assertIn('--core-size: clamp(425px, min(31.5vw, 59dvh), 625px)', self.css)

    def test_avatar_is_selectable_per_device_and_logo_mode_stops_neurocloud_work(self):
        toggle = self.element("avatarModeToggle")
        self.element("avatarModeState")
        self.assertEqual("button", toggle[0])
        self.assertIn("auf diesem Gerät", toggle[1].get("title", ""))
        setter = function_body(self.js, "setAvatarMode")
        loader = function_body(self.js, "loadAvatarMemoryCloud")
        renderer = function_body(self.js, "ensureAvatarMemoryCloud")
        poller = function_body(self.js, "pollAvatarCloudActivity")
        starter = function_body(self.js, "startAvatarCloudActivity")
        disposer = function_body(self.js, "disposeAvatarMemoryCloud")
        self.assertIn('localStorage.setItem("eve.avatarMode", avatarMode)', setter)
        self.assertIn('document.body.dataset.avatar = avatarMode', setter)
        self.assertIn('avatarMode === "brainwatch" ? "logo" : "brainwatch"', self.js)
        self.assertIn('setAvatarMode(avatarMode, false)', self.js)
        self.assertIn('if (avatarMode !== "brainwatch") return null', loader)
        self.assertIn('if (avatarMode !== "brainwatch") return null', renderer)
        self.assertIn('avatarMode !== "brainwatch"', poller)
        self.assertIn('if (avatarMode !== "brainwatch") return', starter)
        self.assertIn("disposeAvatarMemoryCloud()", setter)
        self.assertIn("stopAvatarCloudActivity({ clear: true })", disposer)
        self.assertIn("avatarCloudRenderer?.dispose()", disposer)
        self.assertIn('body[data-avatar="logo"] .eve-avatar-cloud', self.css)
        self.assertIn("display: none", css_declarations(self.css, 'body[data-avatar="logo"] .eve-avatar-cloud'))

    def test_eve_avatar_visual_demo_is_explicit_local_and_clearly_marked(self):
        loader = function_body(self.js, "loadAvatarMemoryCloud")
        demo = function_body(self.js, "runAvatarCloudDemo")
        self.assertIn('get("avatar_demo") === "1"', loader)
        self.assertIn('turnId = "avatar-visual-demo"', demo)
        self.assertIn("projectRuntimeActivity(", demo)
        self.assertIn("visibleEvents", demo)
        self.assertIn("animateActivityEvent(event)", demo)
        self.assertIn("index * 240", demo)
        self.assertIn("12000", demo)
        self.assertNotRegex(demo, r"fetch\(|memoryExplorerRead|readMemoryCloudLivePage")
        self.assertIn('content: "VISUAL TEST"', self.css)

    def test_neurocloud_uses_real_graph_api_without_a_second_graph_view(self):
        loader = function_body(self.js, "readMemoryStructure")
        parameters = function_body(self.js, "memoryCloudParameters")
        relation = function_body(self.js, "memoryCloudRelationEdge")
        self.assertIn("graph?${memoryCloudParameters", loader)
        self.assertIn('node_limit: "160"', parameters)
        self.assertIn("anchor_claim_id", parameters)
        self.assertIn("relation_type", parameters)
        self.assertIn("relation.relation_id", relation)
        self.assertIn("relation.from_claim_id", relation)
        self.assertIn("relation.to_claim_id", relation)
        self.assertNotIn('setMemoryExplorerSubview("graph")', self.js)
        self.assertNotIn("2D ÖFFNEN", self.html)
        self.assertIn("WebGL2 ist nicht verfügbar", self.js)
        self.assertIn("räumliche Nähe allein ist keine semantische Aussage", self.html)
        self.assertIn("keine simulierte Aktivität", self.html)
        self.assertRegex(self.css, r"\.memory-cloud-workspace\s*\{")

    def test_neurocloud_color_legend_explains_activity_status_and_structure(self):
        legend = self.element("memoryCloudLegend")
        self.assertEqual("details", legend[0])
        for label in (
            "Retrieval", "LLM-Kontext", "Deterministisch", "Aktionen",
            "Memory-Änderung", "Relationsnutzung", "Fehlgeschlagen",
            "Abgebrochen", "Ungewiss / laufend", "Provider-Binding",
            "Alias", "Gespeicherte Relation", "Ausgewählter Claim",
            "Direkte Beziehung", "Nächster Hop",
        ):
            self.assertIn(label, self.html)
        self.assertIn("STATUS · ÜBERSCHREIBT AKTIVITÄTSFARBE", self.html)
        self.assertIn("Sie beweisen keine semantische Beziehung", self.html)
        self.assertIn(".memory-cloud-legend .retrieval", self.css)
        self.assertIn(".memory-cloud-legend .failed", self.css)
        self.assertIn(".memory-cloud-legend .relation-line", self.css)
        self.assertIn(".memory-cloud-legend .direct-hop", self.css)
        self.assertIn(".memory-cloud-legend .next-hop", self.css)

    def test_neurocloud_visual_polish_is_organic_deterministic_and_data_bound(self):
        vendor = (WEB_ROOT / "vendor" / "neurocloud-webgl-v1.js").read_text(encoding="utf-8")
        for contract in (
            "neuronAppearance", "relationCurve", "buildFogRegions",
            "claim_ids", "curveSegments", "fogLayers", "fogLimit",
            "cameraDistance", "fieldOfView", "setQuality(value)",
            "selectionNeighborhood", "startAmbientMotion", "pauseAmbientMotion",
            "clearSelection()",
        ):
            self.assertIn(contract, vendor)
        self.assertIn("bezierPoint", vendor)
        self.assertIn("fbm(vec2 p)", vendor)
        self.assertIn("fogVisibility", vendor)
        self.assertIn("depthDistance", vendor)
        self.assertIn("haloPass", vendor)
        self.assertIn("filamentPass", vendor)
        self.assertIn("this.curves.set(edge.id,curve)", vendor)
        self.assertIn("this.curves.get(edge.id)", vendor)
        self.assertIn("neurocloud-layout-v3-provenance-regions", vendor)
        self.assertIn('quality: elements.memoryCloudQuality.value', self.js)
        self.assertIn('setQuality(elements.memoryCloudQuality.value)', self.js)
        self.assertNotIn("Math.random", vendor)
        self.assertNotIn("setInterval", vendor)
        self.assertIn("prefers-reduced-motion: reduce", vendor)
        self.assertIn("neighborhood.relationHops.get(edge.id)", vendor)
        self.assertIn("neighborhood.claimHops.get(node.id)", vendor)
        self.assertIn("focusEmphasis", vendor)
        self.assertIn("ringA", vendor)
        self.assertIn('uniform(this.fogProgram,"focusMode")', vendor)
        for profile_setting in (
            "haloStrength: .14", "fogStrength: .38", "densityAwareExposure: true",
            "densityReference: 460", "relationStrength: 2.4", "boundedBaseBlend: true",
            "additiveRelations: true",
        ):
            self.assertIn(profile_setting, self.js)
        self.assertIn("this.additiveRelations=options.additiveRelations===true", vendor)
        self.assertIn("if(this.additiveRelations)this.blend(gl.ONE)", vendor)
        self.assertIn("nextHop?7", vendor)
        self.assertIn("focused?.07", vendor)
        self.assertIn("focusPath=step(5.0,strength)", vendor)
        self.assertIn("max(relationExposure,.72)", vendor)
        self.assertIn('event.key!=="Escape"', vendor)
        self.assertIn("else this.clearSelection()", vendor)
        cloud_css = css_declarations(self.css, ".memory-cloud-workspace")
        self.assertNotIn("radial-gradient", cloud_css)

    def test_brainwatch_statistics_show_persisted_counts_and_separate_tool_outcomes(self):
        for element_id in (
            "brainwatchStatisticsMode", "brainwatchStatisticsNavigation",
            "brainwatchStatisticsRefresh", "brainwatchStatisticsStatus",
            "brainwatchStatisticsWorkspace", "brainwatchStatisticsContent",
        ):
            self.element(element_id)
        loader = function_body(self.js, "loadBrainwatchStatistics")
        renderer = function_body(self.js, "renderBrainwatchStatistics")
        mode = function_body(self.js, "setBrainwatchMode")
        self.assertIn('fetchWithTimeout("/api/brainwatch/statistics"', loader)
        self.assertIn('cache: "no-store"', loader)
        self.assertNotRegex(loader, r'method:\s*["\'](?:POST|PUT|PATCH|DELETE)')
        for label in (
            "Claims / Neuronen", "Relations / Kanten", "Aktive HA-Entitäten",
            "HA-Verbindungen", "Tool-Aufrufe", "Erfolgreich", "Fehlerhaft",
            "Abgelehnt", "Ausgang unklar", "Exciting Fun Facts™",
        ):
            self.assertIn(label, renderer)
        self.assertIn("tools.by_tool", renderer)
        self.assertIn("most_connected_claim", renderer)
        self.assertIn('"statistics"', mode)
        self.assertIn("brainwatchStatisticsWorkspace.hidden = !statistics", mode)
        self.assertIn("loadBrainwatchStatistics()", mode)

    def test_neurocloud_phase7_uses_persisted_paginated_turn_activity(self):
        activity_controls = self.element("memoryCloudActivityControls")
        self.assertEqual("details", activity_controls[0])
        self.assertIn("TURN-AKTIVITÄT", self.html)
        self.assertIn(".memory-cloud-activity-panel", self.css)
        for element_id in (
            "memoryCloudTurn", "memoryCloudActivityLoad", "memoryCloudActivityCategory",
            "memoryCloudActivityPrevious", "memoryCloudActivityPlay", "memoryCloudActivityNext",
            "memoryCloudActivityClear", "memoryCloudActivitySpeed", "memoryCloudLive",
            "memoryCloudActivityPosition",
        ):
            self.element(element_id)
        load = function_body(self.js, "loadMemoryCloudTurnActivity")
        live = function_body(self.js, "pollMemoryCloudLive")
        select = function_body(self.js, "selectMemoryCloudActivityEvent")
        timeline_select = function_body(self.js, "selectMemoryTimelineEvent")
        self.assertIn("while (hasMore", load)
        self.assertIn("MEMORY_CLOUD_ACTIVITY_LIMIT", load)
        self.assertIn("page.page?.next_cursor", load)
        self.assertIn("memoryCloudActivityComplete", load)
        self.assertIn("runtime-events/live?", self.js)
        self.assertIn("page.page?.poll_cursor", live)
        self.assertIn("new Set(memoryCloudActivityEvents.map", live)
        self.assertIn("memoryCloudRenderer?.animateActivityEvent(event)", select)
        self.assertIn("memoryCloudRenderer?.animateActivityEvent(selected)", timeline_select)
        self.assertIn("document.hidden", function_body(self.js, "startMemoryCloudLive"))
        self.assertIn("stopMemoryCloudLive()", function_body(self.js, "disposeMemoryCloud"))
        self.assertIn("syncMemoryCloudLive()", function_body(self.js, "setMemoryExplorerSubview"))
        self.assertNotRegex(load + live, r'method:\s*["\'](?:POST|PUT|PATCH|DELETE)')

    def test_neurocloud_manual_selection_stays_pinned_during_activity(self):
        renderer = function_body(self.js, "ensureMemoryCloud")
        pin = function_body(self.js, "pinMemoryCloudSelection")
        restore = function_body(self.js, "restoreMemoryCloudSelection")
        activity_target = function_body(self.js, "focusMemoryCloudActivityTarget")
        activity_select = function_body(self.js, "selectMemoryCloudActivityEvent")
        timeline_select = function_body(self.js, "selectMemoryTimelineEvent")
        loader = function_body(self.js, "readMemoryStructure")
        claim_focus = function_body(self.js, "focusMemoryClaim")
        self.assertIn('pinMemoryCloudSelection("claim", claim.id)', renderer)
        self.assertIn('pinMemoryCloudSelection("relation", relation.id)', renderer)
        self.assertIn("onSelectionClear", renderer)
        self.assertIn("memoryCloudPinnedSelection = { kind, id }", pin)
        self.assertIn("memoryCloudRenderer.selectClaim(selected.id)", restore)
        self.assertIn("memoryCloudRenderer.selectRelation(selected.id)", restore)
        self.assertIn("if (memoryCloudPinnedSelection) return", activity_target)
        self.assertIn("focusMemoryCloudActivityTarget(event)", activity_select)
        self.assertIn("focusMemoryCloudActivityTarget(selected)", timeline_select)
        self.assertIn("!restoreMemoryCloudSelection()", loader)
        self.assertIn('pinMemoryCloudSelection("claim", fullClaimId)', claim_focus)

    def test_neurocloud_phase7_renderer_api_and_real_event_contract(self):
        vendor = (WEB_ROOT / "vendor" / "neurocloud-webgl-v1.js").read_text(encoding="utf-8")
        for contract in (
            "projectRuntimeActivity", "setActivityPattern(pattern)", "animateActivityEvent(event)",
            "clearActivity()", "pauseActivity()", "resumeActivity()", "setQuality(value)",
            "relation_traversed_for_retrieval", "relation_bound_to_plan", "Math.log1p(count)",
        ):
            source = vendor + self.js
            self.assertIn(contract, source)
        self.assertIn("activityMotionAllowed()", vendor)
        self.assertIn("updateActivityImpulseBuffer", vendor)
        self.assertIn("bufferSubData", vendor)
        self.assertIn("performance.now()<this.ambientDeadline", vendor)
        self.assertIn("this.stopActivityMotion()", vendor)
        self.assertIn("this.claimImpulses.clear()", vendor)
        self.assertIn("this.relationImpulses.clear()", vendor)
        self.assertIn("this.reducedMotionQuery?.matches", vendor)
        self.assertNotIn("Math.random", vendor)
        self.assertNotIn("fetch(", vendor)

    def test_memory_explorer_navigates_bidirectionally_between_claims_and_turns(self):
        claim_focus = function_body(self.js, "focusMemoryClaim")
        turn_loader = function_body(self.js, "loadTurnMemoryParticipation")
        turn_navigation = function_body(self.js, "navigateBrainwatchTurn")
        claim_navigation = function_body(self.js, "navigateBrainwatchClaim")
        mode = function_body(self.js, "setBrainwatchMode")
        self.assertIn("/turns?limit=20", claim_focus)
        self.assertIn("renderMemoryClaimInspector(detail, evidence, visibleRelations, turns)", claim_focus)
        self.assertIn("turnMemoryRead(turnId)", turn_loader)
        self.assertIn('setBrainwatchMode("information", { load: false })', turn_navigation)
        self.assertIn("focusBrainwatchNode(turnId, { anchor: true })", turn_navigation)
        self.assertIn('setBrainwatchMode("memory", { load: false })', claim_navigation)
        self.assertIn("focusMemoryClaim(claimId, { anchor: true })", claim_navigation)
        self.assertIn("if (load)", mode)
        self.assertNotIn("searchBrainwatch", turn_navigation + claim_navigation)
        self.assertIn("Bei diesem Turn beteiligt ist nicht gleich von EVE tatsächlich verwendet", self.js)
        self.assertIn("Technischer Herkunftsbeleg", self.js)
        self.assertIn("Zugehörige Turns", self.js)
        self.assertIn("Memory-Beteiligung", self.js)
        self.assertIn(".memory-origin-badge", self.css)
        self.assertIn(".memory-participation-notice", self.css)

    def test_memory_explorer_timeline_filters_replays_and_navigates_persisted_events(self):
        for element_id in (
            "memoryCloudView", "memoryTimelineView", "memoryTimelineForm",
            "memoryTimelineKind", "memoryTimelineFidelity", "memoryTimelineFrom",
            "memoryTimelineTo", "memoryTimelineClaim", "memoryTimelineTurn",
            "memoryTimelineScope", "memoryTimelineConsumer", "memoryTimelineStage",
            "memoryTimelineWorkspace", "memoryTimelineList", "memoryTimelineMore",
            "memoryTimelineFirst", "memoryTimelinePrevious", "memoryTimelinePlay",
            "memoryTimelineNext", "memoryTimelineSpeed", "memoryTimelinePosition",
        ):
            self.element(element_id)
        loader = function_body(self.js, "loadMemoryTimeline")
        player = function_body(self.js, "playMemoryTimeline")
        pause = function_body(self.js, "pauseMemoryTimeline")
        inspector = function_body(self.js, "renderMemoryEventInspector")
        subview = function_body(self.js, "setMemoryExplorerSubview")
        self.assertIn("events?${memoryTimelineParameters(cursor)}", loader)
        self.assertIn("left.timestamp.localeCompare(right.timestamp)", loader)
        self.assertIn("window.setInterval", player)
        self.assertIn("selectMemoryTimelineEvent(memoryTimelineIndex + 1)", player)
        self.assertIn("window.clearInterval", pause)
        self.assertIn('memoryTimelinePlay.textContent = "START"', pause)
        self.assertIn("event.source_table", inspector)
        self.assertIn("event.source_id", inspector)
        self.assertIn("navigateBrainwatchClaim", inspector)
        self.assertIn("navigateBrainwatchTurn", inspector)
        self.assertIn('memoryExplorerSubview = view', subview)
        self.assertIn('pauseMemoryTimeline()', subview)
        self.assertIn("Tatsächliche Prompt-Aufnahme und Verwendung sind nicht zuverlässig belegt", self.js)
        self.assertIn("Zeitliche Lücken werden nicht aufgefüllt", self.html)
        self.assertIn(".memory-timeline-event", self.css)
        self.assertNotIn("requestAnimationFrame", player)

    def test_runtime_inspector_is_integrated_without_a_fourth_mode(self):
        for element_id in (
            "memoryTimelineSource", "memoryTimelineCategory", "memoryTimelineProof",
            "memoryTimelineTrace", "memoryTimelinePlannerRound", "memoryTimelineLlmCall",
            "memoryTimelineAttempt", "memoryTimelineOperation", "memoryTimelinePlan",
            "memoryTimelineAction", "memoryTimelineStatus",
        ):
            self.element(element_id)
        loader = function_body(self.js, "loadMemoryTimeline")
        event_inspector = function_body(self.js, "renderMemoryEventInspector")
        claim_inspector = function_body(self.js, "renderMemoryClaimInspector")
        turn_loader = function_body(self.js, "loadTurnRuntime")
        self.assertIn('"historical", "runtime"', loader)
        self.assertIn("runtime-events?", loader)
        self.assertIn("markMemoryCorroboration", loader)
        self.assertIn("Runtime-Aktivität", claim_inspector)
        self.assertIn("appendRuntimeCounts", claim_inspector)
        self.assertIn("turnRuntimeRead(turnId)", turn_loader)
        self.assertIn("event.proof_level", event_inspector)
        self.assertIn("event.planner_round_id", event_inspector)
        self.assertIn("event.action_index", event_inspector)
        self.assertIn("navigateRuntimeTimeline", event_inspector)
        self.assertIn("VOLLSTÄNDIGEN EVENT ÖFFNEN", self.js)
        self.assertIn("Write-Delay", self.js)
        self.assertIn("source-runtime", self.css)
        self.assertNotIn('id="brainwatchRuntimeMode"', self.html)

    def test_brainwatch_has_separate_modes_without_a_global_semantic_panel(self):
        for element_id in (
            "brainwatchInfoMode", "brainwatchMemoryMode", "brainwatchSemanticMode",
            "semanticNavigation", "semanticWorkspace", "brainwatchStage",
        ):
            self.element(element_id)
        mode = function_body(self.js, "setBrainwatchMode")
        self.assertIn('["information", "memory", "semantic", "statistics", "events"]', mode)
        self.assertIn("elements.semanticNavigation.hidden = !semantic", mode)
        self.assertIn("elements.semanticWorkspace.hidden = !semantic", mode)
        self.assertIn("storeBrainwatchViewState()", mode)
        self.assertIn("restoreBrainwatchViewState(mode)", mode)
        self.assertIn("elements.semanticWorkspace.append(semanticPanel)", self.js)
        self.assertNotIn(
            'elements.brainwatchView.insertBefore(semanticPanel, elements.brainwatchView.querySelector(".brainwatch-shell"))',
            self.js,
        )
        for capability in (
            "loadSemanticActions", "loadDynamicSemantics", "loadDifferentialComposition",
            "semantic-similarity/relations", "semantic-similarity/recognitions",
            "KORREKTUR AUFHEBEN", "ERFAHRUNG ABLEHNEN",
        ):
            self.assertIn(capability, self.js)
        self.assertIn("semantic-metrics", self.js)
        self.assertIn("semantic-write-action", self.js)
        for guidance in (
            "Was kann ich hier tun?", "1 · Zuordnungen prüfen", "2 · Gelerntes ansehen",
            "3 · Fehler korrigieren", "Aktuelle Zuordnungen prüfen",
            "Warum wurde das zugeordnet?", "Bedeutung manuell korrigieren",
            "Was EVE bereits als gleiche Handlung versteht",
            "Technische Details und vollständiger Bestand",
        ):
            self.assertIn(guidance, self.js)
        for style in (
            ".semantic-guide", ".semantic-review-card", ".semantic-experience-card",
            ".semantic-badge", ".semantic-empty-state",
        ):
            self.assertIn(style, self.css)

    def test_brainwatch_columns_resize_collapse_restore_and_reset_per_mode(self):
        for element_id in (
            "brainwatchNavigationResize", "brainwatchInspectorResize",
            "brainwatchInspectorShell", "brainwatchInspectorCollapse", "brainwatchLayoutReset",
        ):
            self.element(element_id)
        reset_tag, reset_attrs = self.element("brainwatchLayoutReset")
        self.assertEqual(reset_tag, "button")
        self.assertEqual(reset_attrs.get("title"), "Layout dieses Bereichs zurücksetzen")
        self.assertEqual(reset_attrs.get("aria-label"), "Layout dieses Bereichs zurücksetzen")
        modes = self.html[self.html.index('<nav class="brainwatch-modes'):self.html.index("</nav>", self.html.index('<nav class="brainwatch-modes'))]
        self.assertIn('id="brainwatchLayoutReset"', modes)
        self.assertNotIn("LAYOUT ↺", modes)
        self.assertIn(".brainwatch-modes .brainwatch-layout-reset", self.css)
        resize = function_body(self.js, "attachBrainwatchResize")
        for contract in (
            'addEventListener("pointerdown"', 'setPointerCapture(event.pointerId)',
            'addEventListener("pointermove"', 'addEventListener("pointerup"',
            'addEventListener("pointercancel"', 'addEventListener("lostpointercapture"',
            'addEventListener("dblclick"',
        ):
            self.assertIn(contract, resize)
        self.assertIn('"eve.brainwatchLayout.v1"', self.js)
        self.assertIn("information: { navigation:", self.js)
        self.assertIn("memory: { navigation:", self.js)
        self.assertIn("semantic: { navigation:", self.js)
        self.assertIn("navigation >= 210 && navigation <= 480", self.js)
        self.assertIn("inspector >= 230 && inspector <= 520", self.js)
        self.assertIn('toggleBrainwatchColumn("navigation")', self.js)
        self.assertIn('toggleBrainwatchColumn("inspector")', self.js)
        self.assertIn("resetBrainwatchLayout()", self.js)
        reset = function_body(self.js, "resetBrainwatchLayout")
        self.assertIn("BRAINWATCH_LAYOUT_DEFAULTS[brainwatchMode]", reset)
        self.assertIn("brainwatchLayouts[brainwatchMode]", reset)
        self.assertIn(".brainwatch-column-resize", self.css)
        self.assertIn(".brainwatch-view.navigation-collapsed", self.css)
        self.assertIn(".brainwatch-view.inspector-collapsed", self.css)

    def test_brainwatch_layout_keeps_graph_state_and_has_responsive_scroll_regions(self):
        graph_start = self.js.index("class BrainwatchGraph")
        graph = self.js[graph_start:self.js.index("  const brainwatchGraph", graph_start)]
        self.assertIn("new ResizeObserver(() => this.resize())", graph)
        self.assertIn("captureState()", graph)
        self.assertIn("restoreState(state)", graph)
        self.assertIn("scale: this.scale", graph)
        self.assertIn("offset: { ...this.offset }", graph)
        self.assertIn("inspectorNodes: [...elements.brainwatchInspector.childNodes]", self.js)
        self.assertIn("replaceChildren(...saved.inspectorNodes)", self.js)
        self.assertRegex(self.css, r"\.brainwatch-shell\s*\{[^}]*grid-template-columns:[^}]*var\(--brainwatch-navigation-width")
        self.assertRegex(self.css, r"\.brainwatch-search-panel, \.brainwatch-inspector\s*\{[^}]*overflow:\s*auto")
        self.assertRegex(self.css, r"\.semantic-workspace\s*\{[^}]*overflow-y:\s*auto")
        self.assertIn("@media (max-width: 899px)", self.css)
        self.assertIn(".brainwatch-column-resize { display: none !important; }", self.css)


if __name__ == "__main__":
    unittest.main()
