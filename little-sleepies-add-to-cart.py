import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException


# TODO: update these products to your own links/sizes
PRODUCTS = [
    {
        "url": "https://littlesleepies.com/products/twinkling-trees-two-piece-pajama-set",
        "size": "2T",
        "quantity": 1,
    },
    {
        "url": "https://littlesleepies.com/products/secret-garden-womens-bamboo-viscose-pajama-pants",
        "size": "XS",
        "quantity": 1
    }
]


# If chromedriver is not on PATH, put its full path below:
CHROMEDRIVER_PATH = None  # e.g. r"C:\path\to\chromedriver.exe"


def create_driver():
    options = webdriver.ChromeOptions()
    # Comment this out if you want to see the browser
    # options.add_argument("--headless=new")

    if CHROMEDRIVER_PATH:
        driver = webdriver.Chrome(executable_path=CHROMEDRIVER_PATH, options=options)
    else:
        driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def wait_and_click_size(driver, size_text, timeout=5):
    """Select the size label whose data-size-variant-button matches size_text.

    On Little Sleepies product pages, size options are rendered as labels
    like:

        <label data-cy="product-variant" ... data-size-variant-button="2T">2T ...</label>

    We match using the data-size-variant-button attribute so we don't depend
    on the exact inner text formatting.
    """
    wait = WebDriverWait(driver, timeout)

    try:
        labels = wait.until(
            EC.presence_of_all_elements_located(
                (
                    By.CSS_SELECTOR,
                    "form[id^='product_form'] label[data-cy='product-variant']",
                )
            )
        )
    except TimeoutException:
        return False

    target = None
    for label in labels:
        try:
            data_val = label.get_attribute("data-size-variant-button") or ""
        except Exception:
            continue

        if data_val.strip().lower() == size_text.strip().lower():
            target = label
            break

    if target is None:
        return False

    # Scroll into view and click the label (acts as the radio control)
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});", target
    )
    time.sleep(0.5)
    try:
        target.click()
    except Exception:
        try:
            input_el = target.find_element(By.CSS_SELECTOR, "input[type='radio']")
            input_el.click()
        except NoSuchElementException:
            return False

    return True


def wait_and_click_add_to_cart(driver, timeout=5):
    """Wait for the main PDP Add to Cart button to be enabled, then click it.

    Strategy:
    - Scope to the main product form: form[action="/cart/add"][id^="product_form"]
    - Inside that form, find the button that:
        * has name="add" and/or data-cy="add-to-cart"
        * OR has visible text containing "add to cart"
    - Wait until it's visible, enabled, and not data-product-unavailable="true"
    - Scroll into view and click.
    """
    wait = WebDriverWait(driver, timeout)

    # 1) Wait for the main product form to exist
    try:
        form = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "form[action='/cart/add'][id^='product_form'].pdp-product-form")
            )
        )
    except TimeoutException:
        print("  [WARN] Product form not found.")
        return False

    def find_candidate_button():
        """Find the most likely Add to Cart button inside the product form."""
        buttons = form.find_elements(By.TAG_NAME, "button")
        for b in buttons:
            try:
                name = (b.get_attribute("name") or "").lower()
                data_cy = (b.get_attribute("data-cy") or "").lower()
                text = (b.text or "").strip().lower()
            except Exception:
                continue

            # Heuristics for the main PDP button
            if (
                data_cy == "add-to-cart"
                or name == "add"
                or "add to cart" in text
            ):
                return b
        return None

    # 2) Repeatedly try to get a valid, enabled Add to Cart button
    end_time = time.time() + timeout
    candidate = None

    while time.time() < end_time:
        try:
            if candidate is None:
                candidate = find_candidate_button()
                if candidate is None:
                    time.sleep(0.5)
                    continue

            # Must be displayed & enabled
            if not candidate.is_displayed() or not candidate.is_enabled():
                time.sleep(0.5)
                candidate = None
                continue

            # Respect data-product-unavailable if present
            unavailable = candidate.get_attribute("data-product-unavailable")
            if unavailable and unavailable.lower() == "true":
                time.sleep(0.5)
                candidate = None
                continue

            # Looks good: scroll into view and click
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", candidate
            )
            time.sleep(0.5)
            candidate.click()
            return True

        except StaleElementReferenceException:
            # Form re-rendered; refetch within loop
            candidate = None
            continue
        except Exception:
            # Any transient click interception; retry until timeout
            candidate = None
            time.sleep(0.5)
            continue

    print("  [WARN] Timed out waiting for Add to Cart button to be clickable.")
    return False


def close_sale_popup_if_present(driver, timeout=3):
    """Attempt to close or hide the full-screen sale popup iframe.

    The error stacktrace shows an iframe with id 'attentive_creative' that
    covers the page and intercepts clicks. This helper tries two approaches:
    1) Switch into the iframe and click a close button if found.
    2) If that fails, hide the iframe via JavaScript.
    """
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, "attentive_creative"))
        )
    except TimeoutException:
        return  # no popup iframe detected

    try:
        iframe = driver.find_element(By.ID, "attentive_creative")
    except NoSuchElementException:
        return

    # Try to click a close button inside the iframe
    try:
        driver.switch_to.frame(iframe)
        # Common close selectors inside marketing modals; adjust if needed.
        possible_close_selectors = [
            "button[aria-label='Close']",
            "button[aria-label='Dismiss']",
            "button[class*='close']",
            "[data-test='close-button']",
        ]
        for sel in possible_close_selectors:
            try:
                close_btn = WebDriverWait(driver, 2).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                close_btn.click()
                break
            except TimeoutException:
                continue
            except Exception:
                continue
    except Exception:
        pass
    finally:
        # Always switch back to the main document
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

    # As a fallback, hide the iframe completely so it can't intercept clicks
    try:
        driver.execute_script(
            "var el = document.getElementById('attentive_creative');"
            "if (el) { el.style.display = 'none'; el.style.visibility = 'hidden'; }"
        )
    except Exception:
        pass


def add_product(driver, url, size, quantity=1):
    print(f"Adding: {url} | size={size} | qty={quantity}")
    driver.get(url)

    # Wait for page to load product content
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(2)  # small extra wait in case of lazy JS

    # Close sale popup if it is covering the page
    close_sale_popup_if_present(driver)

    # Select size
    if size:
        if not wait_and_click_size(driver, size):
            print(f"  [WARN] Could not find size '{size}' on page.")
            return

    # print(driver.current_url)
    # btns = driver.find_elements(By.TAG_NAME, "button")
    # print(f"Found {len(btns)} buttons")
    # for b in btns:
    #     try:
    #         print("BTN:", (b.text or "").strip(), "| attrs:", b.get_attribute("data-cy"), b.get_attribute("name"), b.get_attribute("type"))
    #     except Exception:
    #         pass

    # Add it "quantity" times
    for i in range(quantity):
        if not wait_and_click_add_to_cart(driver, 3):
            print("  [WARN] Could not find Add to Cart button.")
            return
        print(f"  Added {i + 1}/{quantity}")
        # Short delay so the site has time to update the cart
        time.sleep(2)


def main():
    driver = create_driver()
    try:
        for item in PRODUCTS:
            add_product(
                driver,
                url=item["url"],
                size=item.get("size"),
                quantity=item.get("quantity", 1),
            )

        print("Done. Check your cart in the browser.")
        # Keep browser open so you can verify cart
        input("Press Enter to close the browser...")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
