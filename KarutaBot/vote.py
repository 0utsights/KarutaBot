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

import logging
import os
import platform
import re
import shutil
import subprocess
import time

log = logging.getLogger("aeyori.vote")

# Karuta's bot ID on top.gg
KARUTA_BOT_ID = "646937666251915264"
VOTE_URL = f"https://top.gg/bot/{KARUTA_BOT_ID}/vote"

# ── Timeouts & retries ──
PAGE_LOAD_WAIT   = 12      # seconds to wait for pages to load
TOKEN_INJECT_WAIT = 4     # seconds after token inject before reload
OAUTH_FLOW_WAIT  = 18     # seconds for Discord→top.gg OAuth redirect chain
VOTE_BTN_WAIT    = 45     # seconds to poll for vote button (includes ad wait)
CAPTCHA_WAIT     = 8      # seconds to wait for captcha to resolve after click
SUCCESS_WAIT     = 6      # seconds to check for success confirmation


def _parse_browser_major(version_text):
    match = re.search(r"(\d+)\.", version_text or "")
    return int(match.group(1)) if match else None


def _iter_browser_candidates():
    """Yield browser executables in priority order for the current OS."""
    env_bin = os.environ.get("AEYORI_CHROME_BIN")
    if env_bin:
        yield env_bin

    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "microsoft-edge",
        "microsoft-edge-stable",
        "chrome",
    ):
        path = shutil.which(name)
        if path:
            yield path

    system = platform.system()
    if system == "Windows":
        for path in (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Chromium\Application\chrome.exe",
            r"C:\Program Files (x86)\Chromium\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ):
            yield path
    elif system == "Darwin":
        for path in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ):
            yield path


def _detect_browser():
    """Return (browser_path, major_version) when a compatible browser is found."""
    seen = set()
    env_ver = os.environ.get("AEYORI_CHROME_VERSION")

    for candidate in _iter_browser_candidates():
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)

        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            continue

        version_text = (result.stdout or result.stderr or "").strip()
        if result.returncode != 0 or not version_text:
            continue

        major = _parse_browser_major(version_text)
        if major:
            return candidate, major

    if env_ver and env_ver.isdigit():
        return os.environ.get("AEYORI_CHROME_BIN"), int(env_ver)

    return None, None


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
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--mute-audio")
    options.add_argument("--no-first-run")
    # Disable images on non-vote pages to speed up Discord login
    # (images re-enable automatically — this just cuts load time)
    options.add_argument("--blink-settings=imagesEnabled=false")

    # Detect installed Chrome/Chromium version so we download the matching
    # driver. undetected-chromedriver can guess wrong on some systems.
    browser_path = None
    chrome_ver = None
    try:
        # Windows: query registry for Chrome version
        result = subprocess.run(
            ['reg', 'query',
             r'HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon',
             '/v', 'version'],
            capture_output=True, text=True, timeout=5
        )
        major = _parse_browser_major(result.stdout)
        if major:
            chrome_ver = major
            log.info(f"Detected Chrome version: {chrome_ver}")
    except Exception:
        pass

    detected_path, detected_ver = _detect_browser()
    if detected_path:
        browser_path = detected_path
        log.info(f"Detected browser executable: {browser_path}")
    if not chrome_ver and detected_ver:
        chrome_ver = detected_ver
        log.info(f"Detected browser major version: {chrome_ver}")

    kwargs = dict(options=options, use_subprocess=True)
    if browser_path:
        options.binary_location = browser_path
        kwargs["browser_executable_path"] = browser_path
    if chrome_ver:
        kwargs["version_main"] = chrome_ver
        log.info(f"Requesting ChromeDriver for Chrome {chrome_ver}")

    driver = uc.Chrome(**kwargs)
    driver.set_page_load_timeout(60)
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
    """Navigate to the top.gg vote page and ensure we're logged in.

    Flow:
      1. Go to top.gg vote page
      2. Wait for any redirects (OAuth, login, etc.)
      3. If we end up on Discord OAuth → click Authorize
      4. If we end up on Discord login → wait for auto-login from token
      5. Once back on top.gg → check for login button, click if needed
      6. Ensure we're on the vote page
    """
    from selenium.webdriver.common.by import By

    log.info(f"Navigating to vote page: {VOTE_URL}")
    try:
        driver.get(VOTE_URL)
    except Exception as _e:
        # Timeout on page load is common with heavy pages — partial loads still work
        log.info(f"Page load timeout (non-fatal, continuing): {_e}")
    time.sleep(PAGE_LOAD_WAIT)

    # ── Handle redirects — top.gg may bounce us through Discord OAuth ──
    # We may need multiple passes since it can chain:
    #   top.gg → discord login → discord oauth → top.gg
    for attempt in range(3):
        current = driver.current_url
        log.info(f"[attempt {attempt+1}] URL: {current}")

        if "discord.com/login" in current:
            log.info("On Discord login page — waiting for token auto-login...")
            time.sleep(PAGE_LOAD_WAIT + 4)
            continue

        if "discord.com/oauth2" in current:
            log.info("On Discord OAuth page — clicking Authorize...")
            _click_authorize(driver)
            time.sleep(OAUTH_FLOW_WAIT)
            continue

        if "top.gg" in current:
            # We're on top.gg — check if there's a visible login button
            # that we need to click (meaning we're not logged in yet)
            login_needed = _try_click_login_if_needed(driver)
            if login_needed == "clicked":
                log.info("Clicked login on top.gg — waiting for OAuth redirect...")
                time.sleep(OAUTH_FLOW_WAIT)
                continue  # will loop back to handle OAuth
            elif login_needed == "logged_in":
                log.info("Already logged into top.gg ✓")
                break
            else:
                # Ambiguous — just proceed, the vote button check will tell us
                log.info("Login status unclear — proceeding to vote button")
                break

    # ── Make sure we're on the vote page ──
    current = driver.current_url
    if "top.gg" in current:
        if "/vote" not in current:
            log.info("On top.gg but not vote page — navigating...")
            driver.get(VOTE_URL)
            time.sleep(PAGE_LOAD_WAIT)
        log.info(f"On vote page: {driver.current_url}")
        return True

    log.warning(f"Unexpected URL after login flow: {current}")
    return False


def _try_click_login_if_needed(driver):
    """Check if top.gg shows a login button and click it if so.

    Returns:
        'clicked'    — found and clicked a login button
        'logged_in'  — no login button found, appears logged in
        'unknown'    — can't tell
    """
    try:
        result = driver.execute_script("""
            // Search for visible login/sign-in buttons or links
            let loginEls = [];
            let all = document.querySelectorAll('a, button, [role="button"]');
            for (let el of all) {
                let text = (el.textContent || '').trim().toLowerCase();
                let href = (el.getAttribute('href') || '').toLowerCase();
                let r = el.getBoundingClientRect();
                if (r.height < 5 || r.width < 5) continue;
                if (getComputedStyle(el).display === 'none') continue;

                // Only match elements whose DIRECT text is login-related
                // (avoid matching large containers that happen to contain
                //  the word "login" somewhere deep in their children)
                let directText = '';
                for (let n of el.childNodes) {
                    if (n.nodeType === 3) directText += n.textContent;
                }
                directText = directText.trim().toLowerCase();

                let isLogin = false;
                if (directText === 'login' || directText === 'log in'
                    || directText === 'sign in'
                    || directText === 'login to vote'
                    || directText === 'log in to vote'
                    || directText === 'sign in to vote') {
                    isLogin = true;
                }
                // href-based: only if it's a small nav element, not the whole page
                if ((href.includes('/login') || href === '/api/auth/discord')
                    && text.length < 30) {
                    isLogin = true;
                }

                if (isLogin) {
                    loginEls.push({
                        tag: el.tagName, text: directText.substring(0, 40),
                        href: href.substring(0, 60), h: r.height, w: r.width
                    });
                    // Click the first clear login button
                    el.scrollIntoView({block: 'center'});
                    el.click();
                    return JSON.stringify({action: 'clicked',
                        tag: el.tagName, text: directText.substring(0, 40)});
                }
            }
            return JSON.stringify({action: 'no_login_found'});
        """)

        import json
        data = json.loads(result)
        if data["action"] == "clicked":
            log.info(f"Clicked login: <{data['tag']}> text={data['text']!r}")
            return "clicked"
        else:
            return "logged_in"

    except Exception as exc:
        log.warning(f"Login check error: {exc}")
        return "unknown"


def _click_authorize(driver):
    """Click the Authorize button on Discord's OAuth page."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    try:
        # Wait for page to fully load
        time.sleep(3)

        # Try WebDriverWait for the authorize button
        try:
            auth_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH,
                    "//button[contains(text(), 'Authorize') or "
                    "contains(text(), 'authorise') or "
                    "contains(@class, 'authorize') or "
                    "@type='submit']"
                ))
            )
            auth_btn.click()
            log.info("Clicked Authorize button via WebDriverWait")
            return True
        except Exception as exc:
            log.info(f"WebDriverWait for Authorize failed: {exc}")

        # JS fallback — search all buttons
        clicked = driver.execute_script("""
            let btns = document.querySelectorAll('button, [role="button"], input[type="submit"]');
            for (let b of btns) {
                let text = (b.textContent || '').trim().toLowerCase();
                if (text.includes('authorize') || text.includes('authorise')
                    || text.includes('allow') || text.includes('accept')) {
                    b.scrollIntoView({block: 'center'});
                    b.click();
                    return 'clicked: ' + b.tagName + ' text=' + text;
                }
            }
            // Also try submit buttons
            let submits = document.querySelectorAll('button[type="submit"], input[type="submit"]');
            for (let s of submits) {
                s.click();
                return 'clicked submit: ' + s.tagName;
            }
            return false;
        """)

        if clicked:
            log.info(f"Clicked Authorize via JS: {clicked}")
            return True

        log.warning("Could not find Authorize button")
        return False

    except Exception as exc:
        log.warning(f"Authorize click error: {exc}")
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
        if result == "ad_playing":
            log.info(f"Ad countdown active — waiting ({elapsed}s / {MAX_POLL}s)...")
            elapsed += POLL_INTERVAL
            time.sleep(POLL_INTERVAL)
            continue

        # Log what we see (first and last attempt only to avoid spam)
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
        'ad_playing'     — ad countdown is visible, vote button not ready
        None             — button not found / not yet ready
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    # Check page state using VISIBLE text only (page_source contains JS bundles
    # with strings like 'login to vote' that cause false matches)
    try:
        page_state = driver.execute_script("""
            let texts = [];
            let els = document.querySelectorAll('h1, h2, h3, h4, h5, p, span, div');
            for (let el of els) {
                let r = el.getBoundingClientRect();
                if (r.height < 5) continue;
                if (getComputedStyle(el).display === 'none') continue;
                if (getComputedStyle(el).visibility === 'hidden') continue;
                let t = '';
                for (let n of el.childNodes) {
                    if (n.nodeType === 3) t += n.textContent;
                }
                t = t.trim().toLowerCase();
                if (t.length > 3 && t.length < 200) texts.push(t);
            }
            return texts.join(' | ');
        """) or ""
    except Exception:
        page_state = ""

    # Check if we already voted
    already_voted_phrases = [
        "you have voted", "already voted", "come back in",
        "next vote in", "vote again in", "thanks for voting",
    ]
    for phrase in already_voted_phrases:
        if phrase in page_state:
            return "already_voted"

    # Check if ad is still playing — "You will be able to vote after this ad"
    if "after this ad" in page_state or "vote after this" in page_state:
        log.info("Ad is still playing — waiting for it to finish...")
        return "ad_playing"

    # Check if vote button should be visible — "You can vote now!"
    vote_ready = "you can vote now" in page_state
    if vote_ready:
        log.info("Page says 'You can vote now!' — looking for Vote button...")

    # ── Use JS to find the button, get its info ──
    try:
        result = driver.execute_script("""
            function directText(el) {
                let t = '';
                for (let n of el.childNodes) {
                    if (n.nodeType === 3) t += n.textContent;
                }
                return t.trim();
            }

            let candidates = [];
            let all = document.querySelectorAll('*');
            for (let el of all) {
                let dt = directText(el).toLowerCase();
                let ft = (el.textContent || '').trim().toLowerCase();
                let cls = (el.className && typeof el.className === 'string')
                          ? el.className.toLowerCase() : '';
                let tag = el.tagName;
                let rect = el.getBoundingClientRect();

                if (rect.height < 10 || rect.width < 30) continue;
                if (getComputedStyle(el).display === 'none') continue;
                if (getComputedStyle(el).visibility === 'hidden') continue;
                if (getComputedStyle(el).opacity === '0') continue;

                // Skip elements that say "voted", "unvote", etc
                if (dt.includes('voted') || dt.includes('unvote')) continue;
                if (ft === 'voted' || ft.includes('already voted')) continue;

                // IMPORTANT: Only match elements whose DIRECT text is exactly "Vote"
                // This avoids matching parent containers like the bar that says
                // "You can vote now!  Vote" (whose full text includes "vote" but
                // is really a container, not the button itself)
                let isVote = false;
                if (dt === 'vote' || dt === 'Vote') isVote = true;

                // Also match by class/data attrs (but only small elements)
                if (!isVote && ft === 'vote') isVote = true;
                if (!isVote) {
                    let dtest = el.getAttribute('data-testid') || '';
                    let aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (dtest === 'vote-button') isVote = true;
                    if (aria === 'vote' || aria === 'vote for this bot') isVote = true;
                }

                if (!isVote) continue;

                let score = 0;
                if (tag === 'BUTTON') score += 10;
                if (tag === 'A')      score += 8;
                if (el.getAttribute('role') === 'button') score += 7;
                if (tag === 'SPAN' || tag === 'DIV') score += 2;
                if (dt === 'Vote' || dt === 'vote') score += 5;
                if (!el.disabled && el.getAttribute('aria-disabled') !== 'true') score += 3;
                // Prefer the pink/red button-sized element (from screenshot: ~80px wide, ~35px tall)
                if (rect.width > 50 && rect.width < 200 && rect.height > 20 && rect.height < 80) {
                    score += 4;  // looks like a button shape
                }
                score += Math.min(rect.height, 100) / 20;

                let bg = getComputedStyle(el).backgroundColor;

                candidates.push({
                    score: score, tag: tag,
                    text: dt.substring(0, 40),
                    fulltext: ft.substring(0, 60),
                    dis: el.disabled || el.getAttribute('aria-disabled') === 'true',
                    cx: rect.x + rect.width / 2,
                    cy: rect.y + rect.height / 2,
                    w: rect.width, h: rect.height,
                    cls: cls.substring(0, 80),
                    bg: bg
                });
            }

            if (candidates.length === 0) return JSON.stringify({found: false});
            candidates.sort((a, b) => b.score - a.score);

            // Return ALL candidates for debugging
            return JSON.stringify({
                found: true,
                best: candidates[0],
                all: candidates.slice(0, 5)
            });
        """)

        if result:
            import json
            data = json.loads(result)

            if not data.get("found"):
                if vote_ready:
                    log.warning("Page says 'vote now' but no vote button found in DOM!")
                return None

            # Log all candidates for debugging
            for i, c in enumerate(data.get("all", [])):
                log.info(f"  candidate[{i}]: <{c['tag']}> direct={c['text']!r} "
                         f"full={c['fulltext']!r} score={c['score']} "
                         f"size={c['w']:.0f}x{c['h']:.0f} "
                         f"pos=({c['cx']:.0f},{c['cy']:.0f}) "
                         f"cls={c['cls']!r} bg={c['bg']!r} dis={c['dis']}")

            best = data["best"]

            if best["dis"]:
                log.info("Best candidate is disabled — will retry")
                return None

            # Now click it with Selenium ActionChains
            try:
                vote_el = driver.execute_script(
                    "return document.elementFromPoint(arguments[0], arguments[1]);",
                    best["cx"], best["cy"]
                )
                if vote_el:
                    # Log what elementFromPoint actually returned
                    actual_tag = driver.execute_script("return arguments[0].tagName;", vote_el)
                    actual_text = driver.execute_script(
                        "return (arguments[0].textContent || '').trim().substring(0, 40);", vote_el)
                    log.info(f"elementFromPoint returned: <{actual_tag}> text={actual_text!r}")

                    driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", vote_el)
                    time.sleep(0.5)

                    actions = ActionChains(driver)
                    actions.move_to_element(vote_el)
                    actions.pause(0.3)
                    actions.click()
                    actions.perform()

                    log.info(f"ActionChains click performed at ({best['cx']:.0f}, {best['cy']:.0f})")

                    # Wait and check if the page changed
                    time.sleep(3)
                    new_text = (driver.page_source or "").lower()

                    # Did "you can vote now" disappear? That means click worked
                    if "you can vote now" in page_state and "you can vote now" not in new_text:
                        log.info("'You can vote now' disappeared — vote click registered!")
                    # Did a success message appear?
                    for phrase in ["you have voted", "thanks for voting", "come back in",
                                   "next vote in"]:
                        if phrase in new_text and phrase not in page_state:
                            log.info(f"Success phrase appeared after click: '{phrase}'")

                    return "clicked"

            except Exception as exc:
                log.warning(f"ActionChains click failed: {exc}")

            # Fallback: dispatchEvent
            try:
                driver.execute_script("""
                    let el = document.elementFromPoint(arguments[0], arguments[1]);
                    if (el) {
                        el.scrollIntoView({block: 'center'});
                        ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(evt => {
                            el.dispatchEvent(new MouseEvent(evt, {
                                bubbles: true, cancelable: true,
                                view: window, button: 0
                            }));
                        });
                    }
                """, best["cx"], best["cy"])
                log.info("Fallback: dispatchEvent click performed")
                time.sleep(3)
                return "clicked"
            except Exception as exc:
                log.warning(f"dispatchEvent fallback failed: {exc}")

    except Exception as exc:
        log.warning(f"JS vote search error: {exc}")

    # ── Strategy B: Direct Selenium xpath selectors ──
    xpath_selectors = [
        "//button[normalize-space(text())='Vote']",
        "//a[normalize-space(text())='Vote']",
        "//*[@role='button'][normalize-space(text())='Vote']",
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
                    txt = (btn.text or "").strip()
                    if txt.lower() != "vote":
                        continue
                    if btn.get_attribute("disabled") or \
                       btn.get_attribute("aria-disabled") == "true":
                        return None

                    log.info(f"Clicking via Selenium xpath: {sel} text={txt!r} "
                             f"size={btn.size}")
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.3)
                    ActionChains(driver).move_to_element(btn).pause(0.3).click().perform()
                    time.sleep(3)
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
    """Handle Cloudflare Turnstile captcha if it appears.

    Top.gg uses Cloudflare Turnstile ("Verify you are human" checkbox).
    It lives inside an iframe. With undetected-chromedriver, clicking the
    checkbox usually auto-passes without image challenges.

    Returns True if captcha was handled or wasn't present.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    log.info("Checking for captcha...")
    time.sleep(2)

    # ── Check if captcha is even present ──
    # Look for "solve the captcha" or "verify you are human" in visible text
    try:
        has_captcha = driver.execute_script("""
            let els = document.querySelectorAll('h1, h2, h3, h4, h5, p, span, div');
            for (let el of els) {
                let r = el.getBoundingClientRect();
                if (r.height < 5) continue;
                if (getComputedStyle(el).display === 'none') continue;
                let t = (el.textContent || '').toLowerCase();
                if (t.includes('solve the captcha') || t.includes('verify you are human')
                    || t.includes('captcha to continue')) {
                    return true;
                }
            }
            return false;
        """)
        if not has_captcha:
            log.info("No captcha text found on page — captcha not present (good!)")
            return True
    except Exception:
        pass

    log.info("Captcha detected — looking for Cloudflare Turnstile iframe...")

    # ── Find the Turnstile iframe ──
    # Cloudflare Turnstile uses an iframe with src containing "challenges.cloudflare.com"
    # or with title containing "Cloudflare" or "Turnstile"
    captcha_frame = None
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        log.info(f"Found {len(iframes)} iframes on page")
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            title = iframe.get_attribute("title") or ""
            name = iframe.get_attribute("name") or ""
            w = iframe.size.get("width", 0)
            h = iframe.size.get("height", 0)
            log.info(f"  iframe: src={src[:100]!r} title={title!r} "
                     f"name={name[:50]!r} size={w}x{h}")

            if ("challenges.cloudflare.com" in src or
                "turnstile" in src.lower() or
                "cloudflare" in title.lower() or
                "turnstile" in title.lower() or
                "cf-turnstile" in name.lower()):
                captcha_frame = iframe
                log.info("  → This is the Turnstile iframe!")
                break

            # Also check for reCAPTCHA as fallback
            if "recaptcha" in src.lower() or "recaptcha" in title.lower():
                captcha_frame = iframe
                log.info("  → This is a reCAPTCHA iframe!")
                break

        if not captcha_frame:
            # Sometimes the iframe doesn't have an obvious src/title.
            # Look for any small iframe that could be a captcha checkbox
            for iframe in iframes:
                w = iframe.size.get("width", 0)
                h = iframe.size.get("height", 0)
                if 200 < w < 400 and 50 < h < 100 and iframe.is_displayed():
                    captcha_frame = iframe
                    log.info(f"  → Likely captcha iframe by size: {w}x{h}")
                    break

    except Exception as exc:
        log.warning(f"Error finding iframes: {exc}")

    if not captcha_frame:
        log.info("No captcha iframe found — trying direct checkbox click...")
        # Try clicking the checkbox without iframe switching
        return _try_direct_captcha_click(driver)

    # ── Click inside the Turnstile iframe ──
    try:
        log.info("Switching to captcha iframe...")
        driver.switch_to.frame(captcha_frame)
        time.sleep(1)

        # Turnstile has a checkbox/label element inside
        # Try to find and click it
        checkbox = None

        # Strategy 1: Find by common Turnstile selectors
        selectors = [
            "input[type='checkbox']",
            "#cf-turnstile-response",
            "[class*='checkbox']",
            "label",
            "[role='checkbox']",
        ]
        for sel in selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in elements:
                    if el.is_displayed():
                        checkbox = el
                        log.info(f"Found captcha checkbox via: {sel}")
                        break
            except Exception:
                continue
            if checkbox:
                break

        # Strategy 2: Click the body of the iframe (Turnstile often
        # just needs a click anywhere inside the iframe)
        if not checkbox:
            try:
                body = driver.find_element(By.TAG_NAME, "body")
                if body:
                    checkbox = body
                    log.info("Using iframe body as click target")
            except Exception:
                pass

        if checkbox:
            # Human-like click with slight delay
            actions = ActionChains(driver)
            actions.move_to_element(checkbox)
            actions.pause(0.3 + (time.time() % 1) * 0.3)
            actions.click()
            actions.perform()
            log.info("Clicked captcha checkbox")

        driver.switch_to.default_content()

    except Exception as exc:
        log.warning(f"Error clicking in captcha iframe: {exc}")
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

    # ── Wait for captcha to resolve ──
    log.info("Waiting for captcha to resolve...")
    time.sleep(CAPTCHA_WAIT)

    # ── Verify captcha was solved ──
    try:
        # Check if the captcha text is gone from the visible page
        still_captcha = driver.execute_script("""
            let els = document.querySelectorAll('h1, h2, h3, h4, h5, p, span, div');
            for (let el of els) {
                let r = el.getBoundingClientRect();
                if (r.height < 5) continue;
                if (getComputedStyle(el).display === 'none') continue;
                let t = (el.textContent || '').toLowerCase();
                if (t.includes('solve the captcha') || t.includes('verify you are human')
                    || t.includes('captcha to continue')) {
                    return true;
                }
            }
            return false;
        """)
        if not still_captcha:
            log.info("Captcha text gone — captcha solved!")
            return True
        else:
            log.warning("Captcha text still present — may not have been solved")
            return False
    except Exception:
        log.info("Could not verify captcha state — proceeding")
        return True


def _try_direct_captcha_click(driver):
    """Try clicking the captcha checkbox without iframe switching.

    Sometimes Turnstile renders in a shadow DOM or in a way that doesn't
    require iframe switching. This tries clicking the visible checkbox directly.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    try:
        result = driver.execute_script("""
            // Look for Turnstile widget container
            let containers = document.querySelectorAll(
                '[class*="turnstile" i], [class*="cf-turnstile" i], ' +
                '[id*="turnstile" i], [data-sitekey]'
            );
            for (let c of containers) {
                let r = c.getBoundingClientRect();
                if (r.height > 10 && r.width > 10) {
                    return JSON.stringify({
                        found: true, x: r.x + r.width/2, y: r.y + r.height/2,
                        w: r.width, h: r.height,
                        tag: c.tagName, cls: (c.className || '').substring(0, 60)
                    });
                }
            }
            return JSON.stringify({found: false});
        """)

        import json
        data = json.loads(result)
        if data.get("found"):
            log.info(f"Found Turnstile container: {data['tag']} {data['cls']!r} "
                     f"size={data['w']:.0f}x{data['h']:.0f}")

            # Click in the center of the Turnstile widget
            el = driver.execute_script(
                "return document.elementFromPoint(arguments[0], arguments[1]);",
                data["x"], data["y"]
            )
            if el:
                actions = ActionChains(driver)
                actions.move_to_element(el)
                actions.pause(0.4)
                actions.click()
                actions.perform()
                log.info("Clicked Turnstile container")

            time.sleep(CAPTCHA_WAIT)
            return True

    except Exception as exc:
        log.warning(f"Direct captcha click failed: {exc}")

    return True  # proceed anyway


def _check_success(driver):
    """Check if the vote was successful by looking for confirmation indicators."""
    time.sleep(SUCCESS_WAIT)

    # Use JS to get only VISIBLE text on the page — not hidden elements,
    # script tags, or React bundles that might contain false matches
    try:
        visible_text = driver.execute_script("""
            // Get visible text from the vote area, not the entire page
            // (the page source contains JS bundles with strings like 'login to vote')
            let texts = [];
            let els = document.querySelectorAll('h1, h2, h3, h4, h5, p, span, div, button, a');
            for (let el of els) {
                let r = el.getBoundingClientRect();
                if (r.height < 5 || r.width < 5) continue;
                if (getComputedStyle(el).display === 'none') continue;
                if (getComputedStyle(el).visibility === 'hidden') continue;
                // Get direct text only (not children)
                let t = '';
                for (let n of el.childNodes) {
                    if (n.nodeType === 3) t += n.textContent;
                }
                t = t.trim();
                if (t.length > 0 && t.length < 200) texts.push(t.toLowerCase());
            }
            return texts.join(' | ');
        """) or ""
    except Exception:
        visible_text = ""

    log.info(f"Visible page text (first 500 chars): {visible_text[:500]}")

    # Check for success indicators in VISIBLE text only
    success_indicators = [
        "you have voted",
        "thanks for voting",
        "successfully voted",
        "come back in",
        "next vote in",
        "vote again in",
    ]

    for indicator in success_indicators:
        if indicator in visible_text:
            log.info(f"Vote success confirmed: found '{indicator}' in visible text")
            return True

    # Check if "you can vote now" is still showing — means vote didn't work
    if "you can vote now" in visible_text:
        log.warning("'You can vote now' still visible — vote did NOT register")
        return False

    # Check if the vote button changed to "voted" state
    try:
        from selenium.webdriver.common.by import By
        result = driver.execute_script("""
            let found = [];
            let all = document.querySelectorAll('button, a, [role="button"], span, div');
            for (let el of all) {
                let direct = '';
                for (let n of el.childNodes) {
                    if (n.nodeType === 3) direct += n.textContent;
                }
                direct = direct.trim().toLowerCase();
                if (direct === 'voted' || direct === 'voted!' ||
                    direct === 'already voted') {
                    let r = el.getBoundingClientRect();
                    if (r.height > 5 && r.width > 5) {
                        found.push(el.tagName + ': ' + direct);
                    }
                }
            }
            return found;
        """)
        if result and len(result) > 0:
            log.info(f"Vote success confirmed: found voted elements: {result}")
            return True
    except Exception:
        pass

    log.info("Could not confirm vote success — may have worked anyway")
    return False



def auto_vote(token, ui_log=None, headless=True):
    """Execute the full automatic vote pipeline with retry.

    If the first attempt fails to confirm success (often due to Cloudflare
    captcha on first visit), automatically retries once — the captcha cookie
    persists so the second attempt usually goes through clean.

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

    # Try up to 2 times — first attempt may hit Cloudflare captcha,
    # second attempt benefits from the captcha cookie
    for attempt in range(1, 3):
        if attempt > 1:
            _log("🗳 [Auto] Retrying vote (attempt 2 — captcha cookie should persist)...")
            time.sleep(3)

        result = _do_vote_attempt(token, headless, _log, attempt)

        if result == "confirmed":
            return True
        if result == "likely":
            if attempt == 1:
                _log("🗳 [Auto] Vote unconfirmed — retrying to verify...")
                continue
            else:
                return True
        if result == "failed":
            if attempt == 1:
                continue
            return False

    return False


def _do_vote_attempt(token, headless, _log, attempt):
    """Single vote attempt. Returns 'confirmed', 'likely', or 'failed'."""
    driver = None
    try:
        _log("🗳 [Auto] Launching browser..." + (" (visible)" if not headless else ""))
        try:
            driver = _create_driver(headless=headless)
        except ImportError as ie:
            import sys
            py = sys.executable
            _log(f"❌ [Auto] Import failed: {ie}")
            _log(f'   Run: & "{py}" -m pip install undetected-chromedriver selenium')
            return "failed"
        except Exception as exc:
            _log(f"❌ [Auto] Could not launch Chrome: {exc}")
            _log("   Make sure Chrome or Chromium is installed on this system.")
            return "failed"

        # Step 1: Login to Discord via token injection
        _log("🗳 [Auto] Logging into Discord...")
        if not _inject_discord_token(driver, token):
            _log("❌ [Auto] Discord login failed — token may be invalid")
            return "failed"

        # Step 2: Navigate to top.gg vote page and log in via OAuth
        _log("🗳 [Auto] Navigating to top.gg + logging in...")
        nav_ok = _navigate_to_vote(driver)
        if not nav_ok:
            _log("⚠ [Auto] Navigation uncertain — trying vote page directly...")
            driver.get(VOTE_URL)
            time.sleep(PAGE_LOAD_WAIT)

        # Step 3: Click the vote button (waits for ad to finish, up to ~45s)
        _log("🗳 [Auto] Waiting for ad + clicking vote button...")
        if not _click_vote_button(driver):
            _log("⚠ [Auto] Could not find vote button — page may have changed")
            return "failed"

        # Step 3b: Wait for response
        _log("🗳 [Auto] Vote button clicked — waiting for response...")
        time.sleep(4)
        _dump_page_debug(driver, f"post_vote_click_attempt{attempt}")

        # Step 4: Handle captcha if present
        _log("🗳 [Auto] Checking for captcha...")
        captcha_ok = _handle_captcha(driver)
        if not captcha_ok:
            _log("⚠ [Auto] Captcha not solved — will retry")
            return "likely"

        # Step 5: Check for success
        time.sleep(3)
        success = _check_success(driver)
        if success:
            _log("✅ [Auto] Vote completed successfully!")
            return "confirmed"
        else:
            _log("⚠ [Auto] Vote may have completed — could not confirm")
            return "likely"

    except Exception as exc:
        _log(f"❌ [Auto] Vote pipeline error: {exc}")
        import traceback
        log.error(traceback.format_exc())
        return "failed"

    finally:
        _close_driver(driver, headless, _log)


def _close_driver(driver, headless, _log):
    """Safely close the browser and suppress undetected-chromedriver errors."""
    if not driver:
        return
    if not headless:
        _log("🔍 [Debug] Browser staying open 15s for inspection...")
        time.sleep(15)
    try:
        driver.quit()
        _log("🗳 [Auto] Browser closed")
    except OSError:
        pass
    except Exception:
        pass
    # Prevent undetected-chromedriver __del__ from double-quitting
    try:
        driver.service.process = None
    except Exception:
        pass
    try:
        driver._is_remote = False
    except Exception:
        pass
