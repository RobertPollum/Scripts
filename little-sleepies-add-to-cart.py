import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


# TODO: update these products to your own links/sizes
PRODUCTS = [
    {
        "url": "https://littlesleepies.com/collections/two-piece-sets/products/twinkling-trees-two-piece-pajama-set",
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


def wait_and_click_size(driver, size_text, timeout=10):
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


def wait_and_click_add_to_cart(driver, timeout=10):
    """Wait for the Add to Cart button to be enabled, then click it.

    Button example:

        <button data-cy="add-to-cart" ... type="submit" name="add" ...>Add to Cart</button>

    The button is disabled until a size is selected. This function assumes
    size has already been chosen and waits until the button is clickable.
    """
    wait = WebDriverWait(driver, timeout)

    # Precise selector for the add-to-cart button
    selector = "button[data-cy='add-to-cart'][name='add'][type='submit']"

    try:
        btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
        )
    except TimeoutException:
        return False

    # Ensure it's not marked unavailable if that attribute is present
    try:
        wait.until(
            lambda d: btn.is_enabled()
            and (btn.get_attribute("data-product-unavailable") in (None, "false"))
        )
    except TimeoutException:
        return False

    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", btn
        )
        time.sleep(0.5)
        btn.click()
        return True
    except Exception:
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

    # Add it "quantity" times
    for i in range(quantity):
        if not wait_and_click_add_to_cart(driver):
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
