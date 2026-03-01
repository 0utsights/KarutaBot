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
VOTE_BTN_WAIT    = 15     # seconds to wait for vote button to appear
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

    driver = uc.Chrome(options=options, use_subprocess=True)
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


def _click_vote_button(driver):
    """Find and click the vote button on the top.gg vote page.

    The vote button is typically a large button with text like "Vote"
    or an element with a data-testid or class containing 'vote'.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    log.info("Looking for vote button...")

    # Strategy 1: Look for button/anchor with "Vote" text
    vote_selectors = [
        "//button[contains(translate(text(), 'VOTE', 'vote'), 'vote')]",
        "//a[contains(translate(text(), 'VOTE', 'vote'), 'vote')]",
        "//*[contains(@class, 'vote')]//button",
        "//*[contains(@class, 'vote')]//a",
        "//button[contains(@class, 'vote')]",
        "//a[contains(@class, 'vote')]",
        "//*[@data-testid='vote-button']",
        "//button[contains(@aria-label, 'vote') or contains(@aria-label, 'Vote')]",
    ]

    for selector in vote_selectors:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, selector))
            )
            # Avoid clicking tiny hidden elements
            if btn.is_displayed() and btn.size.get("height", 0) > 10:
                log.info(f"Found vote button via: {selector}")
                # Scroll into view and click
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(0.5)
                btn.click()
                log.info("Clicked vote button")
                return True
        except Exception:
            continue

    # Strategy 2: JS-based search for any clickable element with "vote" in text
    log.info("Trying JS fallback to find vote button...")
    try:
        clicked = driver.execute_script("""
            let elements = document.querySelectorAll('button, a, [role="button"]');
            for (let el of elements) {
                let text = (el.textContent || '').trim().toLowerCase();
                if (text.includes('vote') && !text.includes('voted') &&
                    el.offsetHeight > 10 && !el.disabled) {
                    el.scrollIntoView({block: 'center'});
                    el.click();
                    return true;
                }
            }
            return false;
        """)
        if clicked:
            log.info("Clicked vote button via JS fallback")
            return True
    except Exception as exc:
        log.warning(f"JS fallback failed: {exc}")

    log.warning("Could not find vote button")
    return False


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


def auto_vote(token, ui_log=None):
    """Execute the full automatic vote pipeline.

    Args:
        token:  Discord user token (the same one used for the bot).
        ui_log: Optional callback like app.ui_log for status updates.

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
        _log("🗳 [Auto] Launching browser...")
        try:
            driver = _create_driver(headless=True)
        except ImportError:
            _log("❌ [Auto] undetected-chromedriver not installed. "
                 "Run: pip install undetected-chromedriver")
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

        # Step 3: Click the vote button
        _log("🗳 [Auto] Clicking vote button...")
        if not _click_vote_button(driver):
            _log("⚠ [Auto] Could not find vote button — page may have changed")
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
            try:
                driver.quit()
                _log("🗳 [Auto] Browser closed")
            except Exception:
                pass
