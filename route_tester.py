import threading
import re
import time
import requests
import random
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

# try to import a simple HTML renderer for Tkinter; if unavailable the
# application will still log responses as text.  This import is optional and
# may not be installed in the development environment, so we catch the
# ImportError and silence static‑analysis warnings.
# pyright: ignore[reportMissingImports]
try:
    # The import is optional; if the package is missing the exception will be
    # caught and the script will still function normally.
    from tkhtmlview import HTMLLabel, HTMLScrolledText, HTMLText  # type: ignore[reportMissingImports]
    HTML_AVAILABLE = True
except ImportError:
    HTML_AVAILABLE = False


# Import the Flask app to enumerate routes.  This will also perform
# application initialization; make sure the local server is running
# separately (e.g. via `python run.py`) before using the tester.
# check for Selenium support so we can drive a real browser window
# pyright: reportMissingImports=false
try:
    # optional library; silence missing-import diagnostics
    from selenium import webdriver  # type: ignore[reportMissingImports]
    from selenium.webdriver.chrome.options import Options  # type: ignore[reportMissingImports]
    from selenium.webdriver.common.by import By  # type: ignore[reportMissingImports]
    from selenium.webdriver.common.action_chains import ActionChains  # type: ignore[reportMissingImports]
    # WebDriverWait for page load
    from selenium.webdriver.support.ui import WebDriverWait  # type: ignore[reportMissingImports]
    from selenium.webdriver.support import expected_conditions as EC  # type: ignore[reportMissingImports]
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# Import the Flask app to enumerate routes.  This will also perform
# application initialization; import under a different name so we don't
# shadow it with the Tkinter application instance later.
from run import app as flask_app


class SiteTesterApp(tk.Tk):
    def __init__(self, base_url="http://localhost:8080"):
        super().__init__()
        self.title("Obsidian Scout Route Tester")
        self.geometry("800x600")
        self.base_url = base_url.rstrip('/')

        frm = tk.Frame(self)
        frm.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(frm, text="Base URL:").pack(side=tk.LEFT)
        self.url_entry = tk.Entry(frm)
        self.url_entry.insert(0, self.base_url)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.verify_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frm, text="Verify SSL", variable=self.verify_var).pack(side=tk.LEFT, padx=5)
        self.browser_var = tk.BooleanVar(value=False)
        tk.Checkbutton(frm, text="Open in external browser", variable=self.browser_var).pack(side=tk.LEFT, padx=5)
        tk.Button(frm, text="Start Tests", command=self.start).pack(side=tk.LEFT, padx=5)
        tk.Button(frm, text="Export URL map", command=self.export_urls).pack(side=tk.LEFT, padx=5)
        tk.Button(frm, text="Export 500s", command=self.export_500s).pack(side=tk.LEFT, padx=5)
        tk.Button(frm, text="Export 500 urls", command=self.export_500s_short).pack(side=tk.LEFT, padx=5)

        self.logbox = ScrolledText(self, state=tk.DISABLED, height=10)
        self.logbox.pack(fill=tk.BOTH, expand=False, padx=5, pady=5)

        if HTML_AVAILABLE:
            tk.Label(self, text="Browser view (HTML rendering):").pack(anchor=tk.W, padx=5)
            self.browser = HTMLLabel(self, html="<i>Browser not started</i>")
            self.browser.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        else:
            tk.Label(self, text="Last response content:").pack(anchor=tk.W, padx=5)
        # always create a response_box so show_response can be called from
        # fallbacks even when HTML_AVAILABLE is True
        self.response_box = ScrolledText(self, state=tk.DISABLED, height=15)
        self.response_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Session used for all requests so cookies / login persist
        self.session = requests.Session()
        # set to collect links seen in page bodies
        self.collected_urls = set()
        # collect server errors (500+) encountered during testing
        self.server_errors = []  # list of tuples (url, status, body)
        # default is to verify, but we will override per-request based on the
        # checkbox
        self.session.verify = True
        # Lock to avoid races between UI thread and worker thread
        self._lock = threading.Lock()

        # external browser module (import here so it's available even if
        # tkinter-webview packages are missing)
        import webbrowser
        self._webbrowser = webbrowser

        # Selenium driver (if running with browser automation)
        self.selenium_driver = None

    def log(self, msg: str):
        with self._lock:
            self.logbox.config(state=tk.NORMAL)
            self.logbox.insert(tk.END, msg + "\n")
            self.logbox.see(tk.END)
            self.logbox.config(state=tk.DISABLED)
            self.update_idletasks()

    def show_response(self, text: str):
        with self._lock:
            self.response_box.config(state=tk.NORMAL)
            self.response_box.delete('1.0', tk.END)
            self.response_box.insert(tk.END, text)
            self.response_box.see(tk.END)
            self.response_box.config(state=tk.DISABLED)
            self.update_idletasks()

    def _extract_csrf(self, html: str) -> str | None:
        """Return value of first hidden csrf_token field or None."""
        m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
        if m:
            return m.group(1)
        return None

    def start(self):
        # update base url from entry and kick off worker thread
        self.base_url = self.url_entry.get().rstrip('/')
        t = threading.Thread(target=self.run_tests, daemon=True)
        t.start()

    def _open_selenium(self):
        """Launch a Selenium browser if available and return it."""
        if not SELENIUM_AVAILABLE:
            self.log("Selenium not installed; skipping real-browser navigation")
            return None
        opts = Options()
        # allow insecure certificates if verification disabled
        if not self.verify_var.get():
            opts.add_argument('--ignore-certificate-errors')
            opts.add_argument('--allow-insecure-localhost')
        # create visible window (not headless)
        try:
            # use Edge instead of Chrome to satisfy request
            driver = webdriver.Edge(options=opts)
            return driver
        except Exception as e:
            self.log(f"Failed to start Selenium browser: {e}")
            return None

    def sanitize_path(self, rule):
        # Replace URL parameters (<int:id>, <string:name>, etc.) with a sample value
        path = rule.rule
        path = re.sub(r"<[^>]+>", "1", path)
        # collapse double slashes
        path = path.replace("//", "/")
        return path

    def enumerate_routes(self):
        # returns list of werkzeug.routing.Rule
        # use the imported flask app rather than the Tk object
        try:
            return list(flask_app.url_map.iter_rules())
        except Exception:
            # if flask_app has no url_map for some reason, return empty
            return []

    def run_tests(self):
        self.log(f"Beginning route enumeration against {self.base_url}")
        # first try to create a test account for team 5568 then log in
        self.log("Attempting to register account for team 5568")
        # update SSL verification state
        self.session.verify = self.verify_var.get()

        # reusable credentials
        # use simple numeric creds so it matches your request
        creds = {'username': '5568',
                 'password': '5568',
                 'team_number': '5568'}

        use_selenium = self.browser_var.get()
        if use_selenium:
            # launch a real browser window to visually show navigation/clicks
            self.selenium_driver = self._open_selenium()
            if self.selenium_driver:
                self.log("Selenium browser started")
                try:
                    d = self.selenium_driver
                    # register
                    d.get(self.base_url + "/auth/register")
                    time.sleep(0.5)  # allow JS to run
                    d.find_element(By.NAME, 'username').send_keys(creds['username'])
                    d.find_element(By.NAME, 'password').send_keys(creds['password'])
                    d.find_element(By.NAME, 'confirm_password').send_keys(creds['password'])
                    d.find_element(By.NAME, 'team_number').send_keys(creds['team_number'])
                    d.find_element(By.CSS_SELECTOR, 'button[type=submit]').click()
                    self.log("Registration attempted via browser")
                    # copy cookies back
                    try:
                        for c in d.get_cookies():
                            self.session.cookies.set(c['name'], c['value'], domain=c.get('domain'), path=c.get('path', '/'))
                    except Exception:
                        pass
                    # login: navigate explicitly and wait for the login form to appear
                    d.get(self.base_url + "/auth/login")
                    try:
                        WebDriverWait(d, 10).until(
                            EC.presence_of_element_located((By.NAME, 'username'))
                        )
                    except Exception:
                        self.log("Login page did not load properly")
                    d.find_element(By.NAME, 'username').send_keys(creds['username'])
                    d.find_element(By.NAME, 'password').send_keys(creds['password'])
                    d.find_element(By.NAME, 'team_number').send_keys(creds['team_number'])
                    d.find_element(By.CSS_SELECTOR, 'button[type=submit]').click()
                    self.log("Login attempted via browser")
                    try:
                        for c in d.get_cookies():
                            self.session.cookies.set(c['name'], c['value'], domain=c.get('domain'), path=c.get('path', '/'))
                    except Exception:
                        pass
                    # verify login via session
                    try:
                        chk = self.session.get(self.base_url, timeout=10)
                        if any(term in chk.text for term in ("Logout","Welcome","Sign Out")):
                            self.log("Login appears successful (selenium)")
                        else:
                            self.log("Login may have failed (selenium)")
                    except Exception:
                        pass
                except Exception as e:
                    self.log(f"Selenium registration/login failed: {e}")
            else:
                use_selenium = False

        if not use_selenium:
            try:
                # fetch registration page to get CSRF token
                reg_page = self.session.get(f"{self.base_url}/auth/register", timeout=10)
                token = self._extract_csrf(reg_page.text)
                data = creds.copy()
                if token:
                    data['csrf_token'] = token
                r = self.session.post(
                    f"{self.base_url}/auth/register",
                    data=data,
                    timeout=10,
                    allow_redirects=True,
                )
                self.log(f"Registration status {r.status_code} ({r.url})")
            except Exception as e:
                self.log(f"Registration request failed: {e}")
            # perform login via requests
            try:
                login_page = self.session.get(f"{self.base_url}/auth/login", timeout=10)
                token2 = self._extract_csrf(login_page.text)
                login_data = creds.copy()
                if token2:
                    login_data['csrf_token'] = token2
                r2 = self.session.post(
                    f"{self.base_url}/auth/login",
                    data=login_data,
                    timeout=10,
                    allow_redirects=True,
                )
                self.log(f"Login status {r2.status_code} ({r2.url})")
            except Exception as e:
                self.log(f"Login request failed: {e}")
            # simple check to see if login succeeded
            try:
                chk = self.session.get(self.base_url, timeout=10)
                if any(term in chk.text for term in ("Logout","Welcome","Sign Out")):
                    self.log("Login appears successful")
                else:
                    self.log("Login may have failed (no logout link detected)")
            except Exception:
                pass

        rules = self.enumerate_routes()
        self.log(f"Discovered {len(rules)} routes")
        # add them to custom list so they can be exported as a map
        for rule in rules:
            path = self.sanitize_path(rule)
            # skip explicit logout route to avoid being logged out
            if 'logout' in path.lower():
                continue
            self.collected_urls.add(self.base_url + path)

        self.visited = set()
        # also track URLs found through HTML parsing
        # collected_urls already has the route map; we'll append additional
        # links we parse from responses as they arrive
        for rule in rules:
            # skip the built-in static endpoint and websocket/other non-HTTP
            if rule.endpoint == 'static':
                continue

            url = self.base_url + self.sanitize_path(rule)
            methods = rule.methods or []
            if self.selenium_driver:
                try:
                    self.log(f"Browser navigating to {url}")
                    self.selenium_driver.get(url)
                    # close any extra windows/tabs that may have opened
                    try:
                        handles = self.selenium_driver.window_handles
                        for h in handles[1:]:
                            try:
                                self.selenium_driver.switch_to.window(h)
                                self.selenium_driver.close()
                            except Exception:
                                pass
                        # always switch back to first window
                        if handles:
                            self.selenium_driver.switch_to.window(handles[0])
                    except Exception:
                        pass
                    # inject highlight into page body to indicate visit
                    try:
                        self.selenium_driver.execute_script("document.body.style.border='5px solid red';")
                    except Exception:
                        pass
                    # simulate cursor movement to a random clickable element (Edge only)
                    try:
                        if self.selenium_driver.name and 'edge' in self.selenium_driver.name.lower():
                            elems = self.selenium_driver.find_elements(By.CSS_SELECTOR,'a,button,input,select,textarea')
                            if elems:
                                elem = random.choice(elems)
                                ActionChains(self.selenium_driver).move_to_element(elem).pause(0.5).perform()
                            else:
                                # no elements found, just move small offset
                                ActionChains(self.selenium_driver).move_by_offset(10,10).perform()
                    except Exception:
                        pass
                except Exception as e:
                    self.log(f"Selenium navigation error for {url}: {e}")


            # we only try GET and POST with no payload; complex routes are
            # likely to error but that's fine as long as we log the traceback.
            if 'GET' in methods:
                try:
                    self.log(f"Clicking {url}")
                    self.visited.add(url)
                    r = self.session.get(url, timeout=10, allow_redirects=True)
                    self.log(f"GET {url} -> {r.status_code}")
                    # always show last response content so user can see what the
                    # site returned in real time
                    self.show_html(r.text, base=url)
                    # try to submit any forms automatically
                    try:
                        self._submit_forms(r.text, url)
                    except Exception:
                        pass
                    if self.browser_var.get() and not self.selenium_driver:
                        try:
                            self._webbrowser.open(url, new=2)
                        except Exception:
                            pass
                    if r.status_code >= 500:
                        self.log("----- server error body start -----")
                        self.log(r.text)
                        self.log("------ server error body end ------")
                        self.server_errors.append((url, r.status_code, r.text))
                except Exception as e:
                    self.log(f"Exception during GET {url}: {e}")
            if 'POST' in methods and rule.rule not in ['/auth/register', '/auth/login']:
                # we already did register; don't spam login with empty data
                try:
                    self.log(f"Posting to {url}")
                    self.visited.add(url)
                    r = self.session.post(url, timeout=10)
                    self.log(f"POST {url} -> {r.status_code}")
                    self.show_html(r.text, base=url)
                    if self.browser_var.get():
                        try:
                            self._webbrowser.open(url, new=2)
                        except Exception:
                            pass
                    if r.status_code >= 500:
                        self.log(r.text)
                        self.server_errors.append((url, r.status_code, r.text))
                except Exception as e:
                    self.log(f"Exception during POST {url}: {e}")

            # tiny pause to avoid overwhelming the server
            time.sleep(0.1)

        self.log("Route testing complete")
        self.log(f"Collected {len(self.collected_urls)} unique URLs")
        if self.server_errors:
            self.log(f"Encountered {len(self.server_errors)} server errors (500s)")

    def export_500s(self):
        import tkinter.filedialog as fd
        path = fd.asksaveasfilename(defaultextension='.txt',
                                     filetypes=[('Text files','*.txt'),('All','*.*')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    for url, status, body in self.server_errors:
                        f.write(f"{status} {url}\n")
                        f.write(body)
                        f.write("\n---\n")
                self.log(f"500 error log exported to {path}")
            except Exception as e:
                self.log(f"Failed to export 500s: {e}")

    def export_500s_short(self):
        import tkinter.filedialog as fd
        path = fd.asksaveasfilename(defaultextension='.txt',
                                     filetypes=[('Text files','*.txt'),('All','*.*')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    for url, status, body in self.server_errors:
                        f.write(f"{status} {url}\n")
                self.log(f"Short 500 log exported to {path}")
            except Exception as e:
                self.log(f"Failed to export short 500s: {e}")

    def export_urls(self):
        # prompt user for file path and write collected URLs
        import tkinter.filedialog as fd
        path = fd.asksaveasfilename(defaultextension='.txt',
                                     filetypes=[('Text files','*.txt'),('All','*.*')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    for u in sorted(self.collected_urls):
                        f.write(u + '\n')
                self.log(f"URL map exported to {path}")
            except Exception as e:
                self.log(f"Failed to export URLs: {e}")

    def show_html(self, html: str, base: str = ""):
        # parse out hyperlinks from the response so we can build a custom map
        for match in re.findall(r'href=["\']([^"\']+)["\']', html):
            # only include http(s) or absolute relative paths
            if match.startswith('http'):
                self.collected_urls.add(match)
            elif match.startswith('/'):
                self.collected_urls.add(self.base_url.rstrip('/') + match)
        # optionally highlight links we've clicked
        for v in self.visited:
            html = html.replace(f'href="{v}"', f'href="{v}" style="background:yellow;"')
        if HTML_AVAILABLE:
            try:
                # HTMLLabel can load a string, base used for resolving relative links
                self.browser.set_html(html, baseurl=base)
            except Exception:
                # fallback to plain logger
                self.show_response(html)
        else:
            self.show_response(html)

    def _submit_forms(self, html: str, base: str):
        """Find <form> tags in HTML, fill inputs with sample data, and POST.
        Also include any csrf_token hidden field in the submission so that
        protected forms succeed."""
        forms = re.findall(r'<form[^>]*>(.*?)</form>', html, flags=re.S|re.I)
        for form in forms:
            # find action
            m = re.search(r'action=["\']([^"\']+)["\']', form)
            action = m.group(1) if m else ''
            if action.startswith('/'):
                if 'logout' in url.lower():
                    continue
                url = self.base_url.rstrip('/') + action
            # avoid submitting logout forms
                if 'logout' in url.lower():
                    continue
            if 'logout' in url.lower():
                continue
            elif action.startswith('http'):
                url = action
            else:
                url = base.rstrip('/') + '/' + action
            # collect inputs
            data = {}
            # if a csrf_token hidden field exists, include it automatically
            if 'csrf_token' in form:
                tokenm = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', form)
                if tokenm:
                    data['csrf_token'] = tokenm.group(1)
            for inp in re.findall(r'<input[^>]*>', form, flags=re.I):
                name_match = re.search(r'name=["\']([^"\']+)["\']', inp)
                if not name_match:
                    continue
                name = name_match.group(1)
                type_match = re.search(r'type=["\']([^"\']+)["\']', inp)
                itype = type_match.group(1).lower() if type_match else 'text'
                # choose a value
                if itype in ('text','email','search','hidden'):
                    data[name] = 'test'
                elif itype in ('password',):
                    data[name] = 'password'
                elif itype in ('number','range'):
                    data[name] = '1'
                elif itype in ('checkbox','radio'):
                    data[name] = 'on'
                else:
                    data[name] = 'test'
            # select elements
            for sel in re.findall(r'<select[^>]*name=["\']([^"\']+)["\'][^>]*>(.*?)</select>', form, flags=re.S|re.I):
                name, inner = sel
                opt = re.search(r'<option[^>]*value=["\']([^"\']+)["\']', inner)
                if opt:
                    data[name] = opt.group(1)
                else:
                    # maybe text-only options
                    txt = re.search(r'>([^<]+)<', inner)
                    data[name] = txt.group(1).strip() if txt else '1'
            if data:
                try:
                    r = self.session.post(url, data=data, timeout=10)
                    self.log(f"Auto-submitted form to {url}, got {r.status_code}")
                except Exception as e:
                    self.log(f"Form submission error to {url}: {e}")


if __name__ == '__main__':
    tester = SiteTesterApp()
    tester.mainloop()
