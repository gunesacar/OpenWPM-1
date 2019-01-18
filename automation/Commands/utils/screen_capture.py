from os.path import join
from ...MPLogger import loggingclient

from time import sleep, time
from datetime import datetime
from urlparse import urlparse
import binascii
import base64
from selenium.common.exceptions import WebDriverException
from webdriver_extensions import click_to_element


def save_screenshot_b64(out_png_path, image_b64, logger):
    try:
        with open(out_png_path, 'wb') as f:
            f.write(base64.b64decode(image_b64.encode('ascii')))
    except Exception:
        logger.exception("Error while saving screenshot to %s"
                         % (out_png_path))
        return False
    return True


COMMON_JS = open('../common.js').read()
EXTRACT_ADD_TO_CART = open('../extract_add_to_cart.js').read()
EXTRACT_PRODUCT_OPTIONS = open('../extract_product_options.js').read()

PHASE_ON_PRODUCT_PAGE = 0
PHASE_SEARCHING_VIEW_CART = 1
PHASE_SEARCHING_CHECKOUT = 2
PHASE_ON_CHECKOUT_PAGE = 3

SLEEP_AFTER_CLICK = 3
SLEEP_AFTER_CHECKOUT_CLICK = 10
SLEEP_UNTIL_DIALOG_DISMISSAL = 15

MAX_PROD_ATTR_INTERACTION = 125 + 10


class ShopBot(object):

    def __init__(self, driver, visit_id, manager_params,
                 logger, landing_page):
        self.visit_id = visit_id
        self.driver = driver
        self.js = self.driver.execute_script
        self.manager_params = manager_params
        self.logger = logger
        self.reason_to_quit = ""
        self.is_play_attr_started = False
        self.time_play_attr_started = 0
        self.update_phase(PHASE_ON_PRODUCT_PAGE)
        self.landing_page = landing_page

    def is_play_attr_finished(self):
        timeout = (
            time() - self.time_play_attr_started) > MAX_PROD_ATTR_INTERACTION
        return timeout or self.js(
                "return localStorage['openwpm-playAttributesDone'];")

    def act(self, seconds_since_load):
        if seconds_since_load < SLEEP_UNTIL_DIALOG_DISMISSAL:
            return
        if self.phase == PHASE_ON_PRODUCT_PAGE:
            if not self.is_play_attr_started:
                self.time_play_attr_started = time()
                self.interact_with_product_attrs()
                self.is_play_attr_started = True
            elif self.is_play_attr_finished():
                self.logger.info(
                    "Product attribute interaction finished in %ds on %s Visit Id: %d" %
                    (int(time() - self.time_play_attr_started), self.landing_page, self.visit_id))
                self.click_add_to_cart()
            else:  # Waiting for the product attribute to finish
                pass
                # self.logger.info(
                #    "Waiting for the product attribute "
                #    "interaction to finish Visit Id: %d" % self.visit_id)
        elif self.phase == PHASE_SEARCHING_VIEW_CART:
            self.click_view_cart()
        elif self.phase == PHASE_SEARCHING_CHECKOUT:
            self.click_checkout()
        elif self.phase == PHASE_ON_CHECKOUT_PAGE:
            self.process_checkout()

    def can_execute_js(self):
        try:
            self.js(COMMON_JS + '\n' + EXTRACT_ADD_TO_CART +
                    ";return localStorage.keys")
            return True
        except WebDriverException as wexc:
            self.logger.error(
                "Exception while executing JS Visit Id: %d %s" % (
                    self.visit_id, wexc))
            self.reason_to_quit =\
                "Cannot execute JS from selenium (WebDriverException)"
            return False

    def is_product_page(self):
        try:
            return self.js(COMMON_JS + '\n' + EXTRACT_ADD_TO_CART +
                           ";return isProductPage();")
        except WebDriverException as wexc:
            self.logger.error(
                "Exception in isProductPage Visit Id: %d %s" % (
                    self.visit_id, wexc))
            self.reason_to_quit = "isProductPage error (WebDriverException)"
            return False

    def update_phase(self, phase):
        self.phase = phase
        self.js('localStorage.setItem("openwpm-phase", %s)' % phase)

    def click_add_to_cart(self):
        button = self.js(COMMON_JS + ';' + EXTRACT_ADD_TO_CART +
                         ";return getAddToCartButton();")
        if not button:
            self.reason_to_quit = "No add to cart button"
            return
        click_to_element(button)
        # move_to_and_click(self.driver, button)
        self.logger.info("Clicked to add to cart Visit Id: %d" % self.visit_id)
        sleep(SLEEP_AFTER_CLICK)
        self.update_phase(PHASE_SEARCHING_VIEW_CART)

    def click_view_cart(self):
        button = self.js(COMMON_JS + ';' + EXTRACT_ADD_TO_CART +
                         ";return getCartButton();")
        if not button:
            self.logger.warning("Cannot find view cart button, will try to "
                                "click checkout Visit Id: %d" % self.visit_id)
            return self.click_checkout()
            # self.reason_to_quit = "No view cart button"
        click_to_element(button)
        self.logger.info("Clicked to view cart Visit Id: %d" % self.visit_id)
        sleep(SLEEP_AFTER_CLICK)
        self.update_phase(PHASE_SEARCHING_CHECKOUT)

    def click_checkout(self):
        button = self.js(COMMON_JS + ';' + EXTRACT_ADD_TO_CART +
                         ";return getCheckoutButton();")
        if not button:
            self.reason_to_quit = "No checkout button"
            return
        click_to_element(button)
        self.logger.info("Clicked to checkout Visit Id: %d" % self.visit_id)
        sleep(SLEEP_AFTER_CLICK)
        self.update_phase(PHASE_ON_CHECKOUT_PAGE)

    def interact_with_product_attrs(self):
        self.logger.info("Will start interaction Visit Id: %d" % self.visit_id)
        self.js(COMMON_JS + ';' + EXTRACT_PRODUCT_OPTIONS +
                ";return playAttributes();")

    def process_checkout(self):
        sleep(SLEEP_AFTER_CHECKOUT_CLICK)
        self.reason_to_quit = "Success"


def capture_screenshots(visit_duration, **kwargs):
    """Capture screenshots every second."""
    driver = kwargs['driver']
    visit_id = kwargs['visit_id']
    manager_params = kwargs['manager_params']
    logger = loggingclient(*manager_params['logger_address'])
    landing_url = driver.current_url
    shop_bot = ShopBot(driver, visit_id, manager_params, logger, landing_url)

    if not shop_bot.can_execute_js():
        logger.warning(
            "Will quit. Reason: %s on %s Visit Id: %d"
            % (shop_bot.reason_to_quit, driver.current_url, visit_id))
        return False

    if not shop_bot.is_product_page():
        logger.warning(
            "Not a product page, will quit on %s Visit Id: %d"
            % (driver.current_url, visit_id))
        return False
    screenshot_dir = manager_params['screenshot_path']
    screenshot_base_path = join(screenshot_dir, "%d_%s" % (
        visit_id, urlparse(landing_url).hostname))
    last_image_crc = 0
    t_begin = time()
    for idx in xrange(0, visit_duration):
        t0 = time()
        shop_bot.act(t0-t_begin)
        if shop_bot.reason_to_quit:
            logger.info(
                "Received quit on %s Visit Id: %d "
                "Phase: %s Reason: %s landing_url: %s" %
                (driver.current_url, visit_id, shop_bot.phase,
                 shop_bot.reason_to_quit, landing_url))
            return

        # perform_interaction("ADD_TO_CART", driver, logger)
        """
        try:
            quit_selenium = driver.execute_script(
                "return localStorage['openwpm-quit-selenium'];")
            quit_reason = driver.execute_script(
                "return localStorage['openwpm-quit-reason'];")
            phase = driver.execute_script(
                "return localStorage['openwpm-phase'];")
        except WebDriverException as exc:
            logger.warning(
                "Error while reading localStorage on %s Visit Id: %d %s"
                % (driver.current_url, visit_id, exc))

        if quit_selenium or driver.current_url == "about:blank":
            logger.info(
                "Received quit on %s Visit Id: %d "
                "phase: %s reason: %s signal: %s landing_url: %s" %
                (driver.current_url, visit_id, phase,
                 quit_reason, quit_selenium, landing_url))
            return
        """
        try:
            img_b64 = driver.get_screenshot_as_base64()
        except Exception:
            logger.exception("Error while taking screenshot on %s Visit Id: %d"
                             % (driver.current_url, visit_id))
            sleep(max([0, 1-(time() - t0)]))  # try to spend 1s on each loop
            continue
        new_image_crc = binascii.crc32(img_b64)
        # check if the image has changed
        if new_image_crc == last_image_crc:
            sleep(max([0, 1-(time() - t0)]))  # try to spend 1s on each loop
            continue
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        out_png_path = "%s_%s_%d" % (screenshot_base_path,
                                     timestamp, idx)
        save_screenshot_b64(out_png_path, img_b64, logger)
        last_image_crc = new_image_crc
        loop_duration = time() - t0
        logger.info(
            "Saved screenshot on %s Visit Id: %d Loop: %d Phase: %s"
            % (driver.current_url,
               visit_id, idx, shop_bot.phase))

        sleep(max([0, 1-loop_duration]))
        if (time() - t_begin) > visit_duration:  # timeout
            logger.info("Timeout in capture_screenshots on %s "
                        "Visit Id: %d Loop: %d Phase: %s"
                        % (driver.current_url, visit_id, idx, shop_bot.phase))

            break
    else:
        logger.info("Loop is over on %s "
                    "Visit Id: %d Loop: %d Phase: %s"
                    % (driver.current_url, visit_id, idx, shop_bot.phase))
