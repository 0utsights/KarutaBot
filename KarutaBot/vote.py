"""
vote.py — Automatic top.gg vote pipeline

Handles the full browser-based vote flow with zero user interaction:
  1. Launch undetected-chromedriver (evades bot detection)
  2. Navigate to discord.com/login → inject Discord token into localStorage
  3. Navigate to top.gg vote page → Discord OAuth auto-approves
  4. Click the vote button
  5. Click reCAPTCHA checkbox if it appears
  6. Verify success → close browser

Dependencies:
  pip install undetected-chromedriver selenium

Notes:
  - Chrome/Chromium must be installed on the user's system.
  - The browser launches, votes, and quits in ~20-40 seconds.
  - undetected-chromedriver patches Chrome to avoid Cloudflare/reCAPTCHA
    fingerprinting, so the checkbox captcha almost always auto-passes.
"""

import time
import logging

log = logging.getLogger("aeyori.vote")

# Karuta's bot ID on top.gg
KARUTA_BOT_ID = "646937666251915264"
VOTE_URL = f"https://top.gg/bot/{KARUTA_BOT_ID}/vote"

# ── Timeouts & retries ──
PAGE_LOAD_WAIT   = 8      # seconds to wait for pages to load
TOKEN_INJECT_WAIT = 4     # seconds after token inject before reload
OAUTH_FLOW_WAIT  = 12     # seconds for Discord→top.gg OAuth redirect chain
VOTE_BTN_WAIT    = 45     # seconds to poll for vote button (includes ad wait)
CAPTCHA_WAIT     = 8      # seconds to wait for captcha to resolve after click
SUCCESS_WAIT     = 6      # seconds to check for success confirmation


def _create_driver(headless=True):
    """Create an undetected-chromedriver instance.

    Returns the driver, or raises ImportError / RuntimeError if Chrome
    or the undetected-chromedriver package is unavailable.
    """
    import undetected_chromedriver as uc

    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # Suppress noisy Chrome logs
    options.add_argument("--log-level=3")
    options.add_argument("--silent")

    # Detect installed Chrome version so we download the matching driver.
    # undetected-chromedriver sometimes guesses wrong (e.g. grabs v146
    # when v145 is installed), so we read it ourselves.
    chrome_ver = None
    try:
        import subprocess, re as _re
        # Windows: query registry for Chrome version
        result = subprocess.run(
            ['reg', 'query',
             r'HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon',
             '/v', 'version'],
            capture_output=True, text=True, timeout=5
        )
        match = _re.search(r'(\d+)\.', result.stdout)
        if match:
            chrome_ver = int(match.group(1))
            log.info(f"Detected Chrome version: {chrome_ver}")
    except Exception:
        pass

    if not chrome_ver:
        # Fallback: try reading from the Chrome executable directly
        try:
            import subprocess, re as _re
            for path in [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True, text=True, timeout=5
                )
                match = _re.search(r'(\d+)\.', result.stdout)
                if match:
                    chrome_ver = int(match.group(1))
                    break
        except Exception:
            pass

    kwargs = dict(options=options, use_subprocess=True)
    if chrome_ver:
        kwargs["version_main"] = chrome_ver
        log.info(f"Requesting ChromeDriver for Chrome {chrome_ver}")

    driver = uc.Chrome(**kwargs)
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(5)
    return driver


def _inject_discord_token(driver, token):
    """Navigate to Discord login page and inject a user token via localStorage.

    Discord's web app reads `token` from localStorage on load.  We create a
    temporary iframe to get a fresh localStorage handle (Discord clears it on
    the login page), write the token, then reload so the app picks it up.
    """
    log.info("Navigating to Discord login...")
    driver.get("https://discord.com/login")
    time.sleep(PAGE_LOAD_WAIT)

    # Inject token via iframe trick (the standard approach — Discord clears
    # localStorage on the login page, but iframes get their own copy)
    inject_js = """
    function injectToken(token) {
        // Try iframe approach first (most reliable)
        let iframe = document.createElement('iframe');
        document.body.appendChild(iframe);
        let ls = iframe.contentWindow.localStorage;
        ls.setItem('token', '"' + token + '"');
        iframe.remove();

        // Also try direct set as fallback
        try {
            localStorage.setItem('token', '"' + token + '"');
        } catch(e) {}
    }
    injectToken(arguments[0]);
    """
    driver.execute_script(inject_js, token)
    log.info("Token injected into localStorage")
    time.sleep(TOKEN_INJECT_WAIT)

    # Reload to trigger Discord's auth flow with the injected token
    driver.get("https://discord.com/channels/@me")
    time.sleep(PAGE_LOAD_WAIT)

    # Verify login succeeded by checking the URL — should NOT be /login
    if "/login" in driver.current_url:
        log.warning("Still on login page after token injection — token may be invalid")
        return False

    log.info(f"Discord login successful (URL: {driver.current_url})")
    return True


def _navigate_to_vote(driver):
    """Navigate to the top.gg vote page.

    If not logged into top.gg, this triggers the Discord OAuth flow.
    Since we're already authenticated in Discord, the OAuth should
    auto-approve and redirect back to the vote page.
    """
    log.info(f"Navigating to vote page: {VOTE_URL}")
    driver.get(VOTE_URL)
    time.sleep(OAUTH_FLOW_WAIT)

    # top.gg may redirect through Discord OAuth. If we land on Discord's
    # authorize page, we need to click "Authorize"
    current = driver.current_url
    log.info(f"Current URL after navigation: {current}")

    if "discord.com/oauth2/authorize" in current:
        log.info("Hit Discord OAuth authorize page — clicking Authorize...")
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            auth_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH,
                    "//button[contains(@class, 'authorize') or "
                    "contains(text(), 'Authorize') or "
                    "contains(text(), 'authorise') or "
                    "@type='submit']"
                ))
            )
            auth_btn.click()
            log.info("Clicked Authorize")
            time.sleep(OAUTH_FLOW_WAIT)
        except Exception as exc:
            log.warning(f"Could not find/click Authorize button: {exc}")
            # Try a JS approach as fallback
            try:
                driver.execute_script("""
                    let btns = document.querySelectorAll('button');
                    for (let b of btns) {
                        if (b.textContent.toLowerCase().includes('authorize')) {
                            b.click();
                            break;
                        }
                    }
                """)
                time.sleep(OAUTH_FLOW_WAIT)
            except Exception:
                pass

    # Should now be on the vote page
    current = driver.current_url
    if "top.gg" in current:
        log.info(f"On top.gg: {current}")
        return True

    log.warning(f"Unexpected URL after OAuth flow: {current}")
    return False


def _dump_page_debug(driver, label="debug"):
    """Save page source and screenshot for debugging vote button issues."""
    import os
    debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vote_debug")
    os.makedirs(debug_dir, exist_ok=True)
    try:
        src_path = os.path.join(debug_dir, f"{label}_page.html")
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        log.info(f"Saved page source to {src_path}")
    except Exception as e:
        log.warning(f"Could not save page source: {e}")
    try:
        ss_path = os.path.join(debug_dir, f"{label}_screenshot.png")
        driver.save_screenshot(ss_path)
        log.info(f"Saved screenshot to {ss_path}")
    except Exception as e:
        log.warning(f"Could not save screenshot: {e}")
    # Log current URL and all visible buttons/links for debugging
    log.info(f"[{label}] URL: {driver.current_url}")
    try:
        from selenium.webdriver.common.by import By
        elements = driver.find_elements(By.CSS_SELECTOR, "button, a, [role='button'], input[type='submit']")
        for i, el in enumerate(elements[:30]):
            txt = (el.text or "").strip()[:60]
            tag = el.tag_name
            cls = el.get_attribute("class") or ""
            href = el.get_attribute("href") or ""
            h = el.size.get("height", 0)
            vis = el.is_displayed()
            if txt or "vote" in cls.lower() or "vote" in href.lower():
                log.info(f"  [{i}] <{tag}> text={txt!r} class={cls[:80]!r} href={href[:60]!r} h={h} vis={vis}")
    except Exception:
        pass


def _click_vote_button(driver):
    """Find and click the vote button on the top.gg vote page.

    Top.gg flow: page loads → ad plays (15-30s) → vote button enables → click.
    The button may be hidden, disabled, or behind an overlay until the ad ends.
    We poll repeatedly with increasing waits to handle this.
    """
    from selenium.webdriver.common.by import By

    log.info("Looking for vote button...")

    # Dump initial page state for debugging
    _dump_page_debug(driver, "pre_vote_click")

    # ── Phase 1: Wait for ad to complete (up to ~40s) ──
    # Top.gg shows an ad before enabling the vote button.  We poll the page
    # every few seconds, looking for a clickable vote element.
    MAX_POLL = 45          # total seconds to keep trying
    POLL_INTERVAL = 3      # seconds between attempts
    elapsed = 0

    while elapsed < MAX_POLL:
        result = _try_find_and_click_vote(driver)
        if result == "clicked":
            return True
        if result == "already_voted":
            log.info("Page says already voted — nothing to click")
            return True

        # Log what we see so far (first and last attempt only to avoid spam)
        if elapsed == 0 or elapsed + POLL_INTERVAL >= MAX_POLL:
            _log_visible_elements(driver, f"poll_t{elapsed}")

        elapsed += POLL_INTERVAL
        if elapsed < MAX_POLL:
            log.info(f"Vote button not ready yet — waiting ({elapsed}s / {MAX_POLL}s)...")
            time.sleep(POLL_INTERVAL)

    # ── Phase 2: Last-resort JS brute-force click ──
    log.info("Trying JS brute-force as last resort...")
    try:
        clicked = driver.execute_script(_JS_BRUTE_FORCE_VOTE)
        if clicked:
            log.info(f"JS brute-force result: {clicked}")
            return True
    except Exception as exc:
        log.warning(f"JS brute-force failed: {exc}")

    # ── Failed — dump debug info ──
    _dump_page_debug(driver, "vote_button_not_found")
    log.warning("Could not find vote button — check vote_debug/ folder")
    return False


def _log_visible_elements(driver, label=""):
    """Log every visible button/link/interactive element for debugging."""
    try:
        from selenium.webdriver.common.by import By
        info = driver.execute_script("""
            let out = [];
            let els = document.querySelectorAll(
                'button, a, [role="button"], input[type="submit"], [onclick]'
            );
            for (let el of els) {
                let r = el.getBoundingClientRect();
                if (r.height < 5 || r.width < 5) continue;
                let text = (el.textContent || '').trim().substring(0, 60);
                let tag  = el.tagName;
                let cls  = (el.className && typeof el.className === 'string')
                           ? el.className.substring(0, 100) : '';
                let href = el.getAttribute('href') || '';
                let dis  = el.disabled || el.getAttribute('aria-disabled') === 'true';
                out.push(tag + ' | ' + text + ' | cls=' + cls + ' | href=' + href + ' | dis=' + dis);
            }
            return out;
        """)
        log.info(f"[{label}] Visible interactive elements ({len(info)}):")
        for line in (info or [])[:40]:
            log.info(f"  {line}")
    except Exception as e:
        log.warning(f"Could not log elements: {e}")


def _try_find_and_click_vote(driver):
    """Single attempt to find and click the vote button.

    Returns:
        'clicked'        — successfully clicked the vote button
        'already_voted'  — page indicates we already voted
        None             — button not found / not yet ready
    """
    from selenium.webdriver.common.by import By

    page_text = (driver.page_source or "").lower()

    # Check if we already voted
    already_voted_phrases = [
        "you have voted", "already voted", "come back in",
        "next vote in", "vote again in", "thanks for voting",
    ]
    for phrase in already_voted_phrases:
        if phrase in page_text:
            return "already_voted"

    # ── Strategy A: JavaScript comprehensive search ──
    # This is the most reliable approach for React SPAs — searches the
    # live DOM for any element whose text content is exactly "Vote" (or
    # very close) and that is currently visible + enabled.
    try:
        result = driver.execute_script("""
            // Helper: get only the DIRECT text of an element (not children)
            function directText(el) {
                let t = '';
                for (let n of el.childNodes) {
                    if (n.nodeType === 3) t += n.textContent;
                }
                return t.trim();
            }

            // Collect candidates: any element whose text looks like "vote"
            let candidates = [];
            let all = document.querySelectorAll('*');
            for (let el of all) {
                let dt = directText(el).toLowerCase();
                let ft = (el.textContent || '').trim().toLowerCase();
                let cls = (el.className && typeof el.className === 'string')
                          ? el.className.toLowerCase() : '';
                let tag = el.tagName;
                let rect = el.getBoundingClientRect();

                // Skip tiny/invisible elements
                if (rect.height < 10 || rect.width < 30) continue;
                if (getComputedStyle(el).display === 'none') continue;
                if (getComputedStyle(el).visibility === 'hidden') continue;
                if (getComputedStyle(el).opacity === '0') continue;

                // Skip if text says "voted" "unvote" etc
                if (dt.includes('voted') || dt.includes('unvote')) continue;
                if (ft === 'voted' || ft.includes('already voted')) continue;

                let isVote = false;

                // Direct text match (best signal)
                if (dt === 'vote') isVote = true;
                // Full text is just "vote" (button with only that word)
                if (ft === 'vote') isVote = true;
                // Class-based match
                if (cls.match(/\\bvote\\b/) && !cls.includes('voted')
                    && !cls.includes('unvote')) isVote = true;
                // data-* attribute match
                let dtest = el.getAttribute('data-testid') || '';
                let dcy   = el.getAttribute('data-cy') || '';
                if (dtest.includes('vote') || dcy.includes('vote')) isVote = true;
                // aria-label match
                let aria = (el.getAttribute('aria-label') || '').toLowerCase();
                if (aria === 'vote' || aria === 'vote for this bot') isVote = true;

                if (!isVote) continue;

                // Score: prefer buttons/links, larger elements, enabled elements
                let score = 0;
                if (tag === 'BUTTON') score += 10;
                if (tag === 'A')      score += 8;
                if (el.getAttribute('role') === 'button') score += 7;
                if (dt === 'vote')     score += 5;   // exact direct text
                if (!el.disabled && el.getAttribute('aria-disabled') !== 'true') score += 3;
                score += Math.min(rect.height, 100) / 20;  // bigger = better

                candidates.push({el: el, score: score, tag: tag,
                                 text: ft.substring(0, 40),
                                 dis: el.disabled || el.getAttribute('aria-disabled') === 'true'});
            }

            if (candidates.length === 0) return JSON.stringify({found: false});

            // Sort by score descending
            candidates.sort((a, b) => b.score - a.score);

            let best = candidates[0];

            // If the best candidate is disabled, report it but don't click
            if (best.dis) {
                return JSON.stringify({
                    found: true, disabled: true,
                    tag: best.tag, text: best.text,
                    count: candidates.length
                });
            }

            // Click it!
            best.el.scrollIntoView({block: 'center'});
            best.el.click();
            return JSON.stringify({
                found: true, clicked: true,
                tag: best.tag, text: best.text,
                count: candidates.length
            });
        """)

        if result:
            import json
            data = json.loads(result)
            if data.get("clicked"):
                log.info(f"Clicked vote button: <{data['tag']}> text={data['text']!r}")
                return "clicked"
            if data.get("found") and data.get("disabled"):
                log.info(f"Found vote button but DISABLED (ad still playing?): "
                         f"<{data['tag']}> text={data['text']!r}")
                return None  # will retry
            if not data.get("found"):
                return None  # not found yet, will retry
    except Exception as exc:
        log.warning(f"JS vote search error: {exc}")

    # ── Strategy B: Selenium selectors as fallback ──
    xpath_selectors = [
        "//button[translate(normalize-space(text()),'VOTE','vote')='vote']",
        "//a[translate(normalize-space(text()),'VOTE','vote')='vote']",
        "//*[@role='button'][translate(normalize-space(text()),'VOTE','vote')='vote']",
        "//button[contains(@class,'vote') or contains(@class,'Vote')]",
        "//a[contains(@class,'vote') or contains(@class,'Vote')]",
        "//*[@data-testid='vote-button']",
    ]
    for sel in xpath_selectors:
        try:
            elements = driver.find_elements(By.XPATH, sel)
            for btn in elements:
                try:
                    if not btn.is_displayed():
                        continue
                    if btn.size.get("height", 0) < 10:
                        continue
                    txt = (btn.text or "").strip().lower()
                    if "voted" in txt and txt != "vote":
                        continue
                    if btn.get_attribute("disabled") or \
                       btn.get_attribute("aria-disabled") == "true":
                        log.info(f"Found disabled vote button via xpath: {sel}")
                        return None  # retry later
                    log.info(f"Clicking vote button via xpath: {sel} text={btn.text!r}")
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.3)
                    btn.click()
                    return "clicked"
                except Exception:
                    continue
        except Exception:
            continue

    return None


# JavaScript brute-force: clicks the first visible element whose text is "vote"
# regardless of tag, class, or state.  Used as absolute last resort.
_JS_BRUTE_FORCE_VOTE = """
    let all = document.querySelectorAll('*');
    for (let el of all) {
        let t = '';
        for (let n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; }
        t = t.trim().toLowerCase();
        if (t !== 'vote') continue;
        let r = el.getBoundingClientRect();
        if (r.height < 5 || r.width < 5) continue;
        el.scrollIntoView({block: 'center'});
        el.click();
        return 'brute-clicked: ' + el.tagName + ' ' + el.className;
    }
    // Also try clicking anything with "vote" in the class
    for (let el of document.querySelectorAll('[class*="vote" i], [class*="Vote"]')) {
        let r = el.getBoundingClientRect();
        if (r.height < 10 || r.width < 10) continue;
        let cls = (el.className || '').toLowerCase();
        if (cls.includes('voted') || cls.includes('unvote')) continue;
        el.scrollIntoView({block: 'center'});
        el.click();
        return 'brute-class-clicked: ' + el.tagName + ' ' + el.className;
    }
    return false;
"""


def _handle_captcha(driver):
    """Attempt to solve the reCAPTCHA checkbox if it appears.

    With undetected-chromedriver, the reCAPTCHA v2 checkbox typically
    auto-passes on click (no image challenges). The user confirmed that
    it's a standard checkbox that sometimes doesn't even appear.

    Returns True if captcha was handled or wasn't present.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    log.info("Checking for reCAPTCHA...")
    time.sleep(2)

    # reCAPTCHA lives inside an iframe — we need to switch into it
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        captcha_frame = None
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            title = iframe.get_attribute("title") or ""
            if "recaptcha" in src.lower() or "recaptcha" in title.lower():
                captcha_frame = iframe
                break

        if not captcha_frame:
            log.info("No reCAPTCHA iframe found — captcha not present (good!)")
            return True

        log.info("Found reCAPTCHA iframe — switching into it...")
        driver.switch_to.frame(captcha_frame)

        # Find and click the checkbox
        checkbox = driver.find_element(By.ID, "recaptcha-anchor")
        if checkbox:
            # Human-like: move to element with slight offset, pause, then click
            actions = ActionChains(driver)
            actions.move_to_element(checkbox)
            actions.pause(0.3 + (time.time() % 1) * 0.4)  # slight random delay
            actions.click()
            actions.perform()
            log.info("Clicked reCAPTCHA checkbox")

        # Switch back to main content
        driver.switch_to.default_content()
        time.sleep(CAPTCHA_WAIT)

        # Check if captcha was solved (the checkmark appears)
        try:
            driver.switch_to.frame(captcha_frame)
            anchor = driver.find_element(By.ID, "recaptcha-anchor")
            classes = anchor.get_attribute("class") or ""
            checked = "recaptcha-checkbox-checked" in classes
            driver.switch_to.default_content()

            if checked:
                log.info("reCAPTCHA solved successfully!")
                return True
            else:
                log.warning("reCAPTCHA checkbox clicked but not checked — "
                           "may have triggered image challenge")
                driver.switch_to.default_content()
                return False
        except Exception:
            driver.switch_to.default_content()
            # If we can't verify, assume it worked
            log.info("Could not verify captcha state — proceeding")
            return True

    except Exception as exc:
        log.warning(f"Captcha handling error: {exc}")
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return True  # proceed anyway — captcha may not have been required


def _check_success(driver):
    """Check if the vote was successful by looking for confirmation indicators."""
    time.sleep(SUCCESS_WAIT)

    page_text = driver.page_source.lower()
    success_indicators = [
        "you have voted",
        "thanks for voting",
        "successfully voted",
        "already voted",
        "voted!",
        "come back in",
        "next vote in",
        "vote again in",
    ]

    for indicator in success_indicators:
        if indicator in page_text:
            log.info(f"Vote success confirmed: found '{indicator}'")
            return True

    # Also check if the button changed to a "voted" state
    try:
        from selenium.webdriver.common.by import By
        voted_elements = driver.find_elements(By.XPATH,
            "//*[contains(translate(text(), 'VOTED', 'voted'), 'voted')]"
        )
        if voted_elements:
            log.info("Vote success confirmed: found 'voted' element")
            return True
    except Exception:
        pass

    log.info("Could not confirm vote success — may have worked anyway")
    return False


def auto_vote(token, ui_log=None, headless=True):
    """Execute the full automatic vote pipeline.

    Args:
        token:    Discord user token (the same one used for the bot).
        ui_log:   Optional callback like app.ui_log for status updates.
        headless: If False, browser window is visible for debugging.

    Returns:
        True if vote succeeded (or likely succeeded), False on hard failure.
    """
    def _log(msg):
        log.info(msg)
        if ui_log:
            try:
                ui_log(msg)
            except Exception:
                pass

    driver = None
    try:
        _log("🗳 [Auto] Launching browser..." + (" (visible)" if not headless else ""))
        try:
            driver = _create_driver(headless=headless)
        except ImportError as ie:
            import sys
            py = sys.executable
            _log(f"❌ [Auto] Import failed: {ie}")
            _log(f"   Python: {py}")
            _log(f"   In PowerShell, run:")
            _log(f'   & "{py}" -m pip install undetected-chromedriver selenium')
            _log(f"   Or in CMD:")
            _log(f'   "{py}" -m pip install undetected-chromedriver selenium')
            return False
        except Exception as exc:
            _log(f"❌ [Auto] Could not launch Chrome: {exc}")
            _log("   Make sure Chrome or Chromium is installed on this system.")
            return False

        # Step 1: Login to Discord via token injection
        _log("🗳 [Auto] Logging into Discord...")
        if not _inject_discord_token(driver, token):
            _log("❌ [Auto] Discord login failed — token may be invalid")
            return False

        # Step 2: Navigate to top.gg vote page (triggers OAuth)
        _log("🗳 [Auto] Navigating to top.gg vote page...")
        if not _navigate_to_vote(driver):
            _log("⚠ [Auto] Could not reach vote page — trying direct URL...")
            driver.get(VOTE_URL)
            time.sleep(PAGE_LOAD_WAIT)

        # Step 3: Click the vote button (waits for ad to finish, up to ~45s)
        _log("🗳 [Auto] Waiting for ad + clicking vote button...")
        if not _click_vote_button(driver):
            _log("⚠ [Auto] Could not find vote button — page may have changed")
            _log("   Check the vote_debug/ folder next to the .exe for screenshots")
            return False

        # Step 4: Handle captcha if present
        time.sleep(2)
        _log("🗳 [Auto] Handling captcha...")
        captcha_ok = _handle_captcha(driver)
        if not captcha_ok:
            _log("⚠ [Auto] Captcha challenge may require manual intervention")
            # Don't return False — it may still have worked

        # Step 5: Check for success
        success = _check_success(driver)
        if success:
            _log("✅ [Auto] Vote completed successfully!")
        else:
            _log("⚠ [Auto] Vote may have completed — could not confirm")

        return True

    except Exception as exc:
        _log(f"❌ [Auto] Vote pipeline error: {exc}")
        import traceback
        log.error(traceback.format_exc())
        return False

    finally:
        if driver:
            if not headless:
                # In visible mode, pause so user can inspect the browser
                _log("🔍 [Debug] Browser staying open 15s for inspection...")
                time.sleep(15)
            try:
                driver.quit()
                _log("🗳 [Auto] Browser closed")
            except Exception:
                pass
