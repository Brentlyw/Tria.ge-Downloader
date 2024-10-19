import os
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from rich.console import Console
from rich.panel import Panel

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
CONFIG_FILE = "config.json"
MIN_FILE_SIZE = 1024
DOWNLOAD_DELAY = 0.1

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as file:
            try:
                config = json.load(file)
                logging.info("Configuration loaded successfully.")
                return config
            except json.JSONDecodeError:
                logging.error("Config file is not a valid JSON.")
                return {}
    logging.info("Config file does not exist.")
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as file:
        json.dump(config, file, indent=4)
    logging.info(f"Configuration saved to {CONFIG_FILE}.")

def get_cookies(config):
    auth_cookie = config.get("auth_cookie")
    csrf_cookie = config.get("csrf_cookie")
    
    if not auth_cookie:
        console.print("[bold yellow]Auth cookie not found in config.[/bold yellow]")
        auth_cookie = console.input("Enter your 'auth' cookie value: ").strip()
        config["auth_cookie"] = auth_cookie
        logging.info("Auth cookie obtained.")
    
    if not csrf_cookie:
        console.print("[bold yellow]_csrf cookie not found in config.[/bold yellow]")
        csrf_cookie = console.input("Enter your '_csrf' cookie value: ").strip()
        config["csrf_cookie"] = csrf_cookie
        logging.info("_csrf cookie obtained.")
    
    if not config.get("auth_cookie") or not config.get("csrf_cookie"):
        save_config(config)
    
    return auth_cookie, csrf_cookie

def get_user_input():
    family = console.input("[bold green]Enter the Family name:[/bold green] ").strip()
    logging.info(f"Family name entered: {family}")
    return family

def construct_search_url(family):
    encoded_family = quote(family)
    search_url = f"https://tria.ge/s?q=family%3A{encoded_family}&limit=500"
    logging.info(f"Constructed search URL: {search_url}")
    return search_url

def fetch_search_page(session, url):
    logging.info(f"Fetching search page: {url}")
    try:
        response = session.get(url)
        response.raise_for_status()
        logging.info(f"Search page fetched successfully with status code: {response.status_code}")
        return response.text
    except requests.RequestException as e:
        logging.error(f"Error fetching search page: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logging.debug("Redirect History:")
            for resp in e.response.history:
                logging.debug(f"{resp.status_code} -> {resp.url}")
        return None

def parse_sample_ids(html_content):
    logging.info("Parsing search page content to extract sample IDs.")
    soup = BeautifulSoup(html_content, 'html.parser')
    elements = soup.find_all(attrs={"data-sample-id": True})
    sample_ids = [element['data-sample-id'] for element in elements]
    logging.info(f"Extracted {len(sample_ids)} sample IDs.")
    return sample_ids

@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def download_sample(session, sample_id, download_dir):
    download_url = f"https://tria.ge/samples/{sample_id}/sample.zip"
    logging.info(f"Attempting to download: {download_url}")
    
    try:
        with session.get(download_url, stream=True, allow_redirects=True) as response:
            if response.status_code == 404:
                logging.error(f"Error downloading {sample_id}: 404 Not Found. Skipping.")
                return
            response.raise_for_status()
            
            if response.history:
                logging.info(f"Redirect History for {sample_id}:")
                for resp in response.history:
                    logging.info(f"{resp.status_code} -> {resp.url}")
            
            file_path = os.path.join(download_dir, f"{sample_id}_sample.zip")
            logging.info(f"Downloading to: {file_path}")
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            file_size = os.path.getsize(file_path)
            logging.info(f"Downloaded file size: {file_size} bytes.")
            if file_size <= MIN_FILE_SIZE:
                os.remove(file_path)
                logging.warning(f"Skipped invalid file (size: {file_size} bytes): {file_path}")
            else:
                logging.info(f"Successfully downloaded: {file_path} (size: {file_size} bytes)")
    except requests.TooManyRedirects as e:
        logging.error(f"Error downloading {sample_id}: Exceeded 30 redirects.")
        if e.response and e.response.history:
            logging.debug("Redirect History:")
            for resp in e.response.history:
                logging.debug(f"{resp.status_code} -> {resp.url}")
        raise e
    except requests.RequestException as e:
        if e.response and e.response.status_code == 404:
            logging.error(f"Error downloading {sample_id}: 404 Not Found. Skipping.")
        else:
            logging.error(f"Error downloading {sample_id}: {e}")
        raise e
    except OSError as e:
        logging.error(f"Error handling file for {sample_id}: {e}")

def automate_browser_and_extract_cookies():
    logging.info("Launching browser for manual authentication.")
    console.print(Panel("Please log in to [bold green]tria.ge[/bold green] in the browser window. Once logged in, return here and press Enter to continue.", title="Authentication Required"))
    
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    
    driver = webdriver.Chrome(service=ChromeService(), options=chrome_options)
    
    try:
        driver.get("https://tria.ge/")
        logging.info("Browser launched and navigated to https://tria.ge/")
        
        input("Once you have logged in, press Enter here to continue...")
        
        cookies = driver.get_cookies()
        logging.info(f"Cookies obtained from browser: {[cookie['name'] for cookie in cookies]}")
        
        config = load_config()
        config["cookies"] = {cookie['name']: cookie['value'] for cookie in cookies}
        save_config(config)
        
        console.print("[bold green]Authentication successful. Cookies have been saved.[/bold green]")
    except Exception as e:
        logging.error(f"An error occurred during browser automation: {e}")
    finally:
        driver.quit()
        logging.info("Browser closed.")

def load_cookies_into_session(session):
    if not os.path.exists(CONFIG_FILE):
        logging.warning("Config file not found. Initiating browser automation to obtain cookies.")
        automate_browser_and_extract_cookies()
    
    with open(CONFIG_FILE, 'r') as file:
        config = json.load(file)
    
    cookies = config.get("cookies", {})
    if not cookies:
        logging.error("No cookies found in config. Please ensure you are logged in.")
        return False
    
    for name, value in cookies.items():
        session.cookies.set(name, value, domain="tria.ge")
        logging.debug(f"Set cookie: {name}={value[:10]}...")
    
    logging.info("All cookies have been loaded into the session.")
    return True

def main():
    session = requests.Session()
    
    if not load_cookies_into_session(session):
        console.print("[bold red]Failed to load cookies into the session. Exiting.[/bold red]")
        return
    
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/89.0.4389.82 Safari/537.36",
        "Referer": "https://tria.ge/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    logging.info("Session headers updated to mimic a real browser.")
    
    family = get_user_input()
    if not family:
        logging.error("Family name cannot be empty. Exiting.")
        return
    
    search_url = construct_search_url(family)
    
    html_content = fetch_search_page(session, search_url)
    if not html_content:
        console.print("[bold red]Failed to retrieve search results. Exiting.[/bold red]")
        return
    
    sample_ids = parse_sample_ids(html_content)
    if not sample_ids:
        console.print("[bold yellow]No samples found for the given family. Exiting.[/bold yellow]")
        return
    
    console.print(f"[bold green]Found {len(sample_ids)} samples. Starting download...[/bold green]\n")
    
    download_dir = os.path.join("downloads", family)
    os.makedirs(download_dir, exist_ok=True)
    logging.info(f"Download directory set to: {download_dir}")
    
    for sample_id in sample_ids:
        logging.info(f"Starting download for sample ID: {sample_id}")
        try:
            download_sample(session, sample_id, download_dir)
        except requests.TooManyRedirects:
            console.print(f"[bold red]Error downloading {sample_id}: Exceeded 30 redirects.[/bold red]")
        except requests.RequestException as e:
            if isinstance(e, requests.HTTPError) and e.response.status_code == 404:
                console.print(f"[bold red]Error downloading {sample_id}: 404 Not Found. Skipping.[/bold red]")
            else:
                console.print(f"[bold red]Error downloading {sample_id}: {e}[/bold red]")
        except Exception as e:
            console.print(f"[bold red]Unexpected error downloading {sample_id}: {e}[/bold red]")
        
        logging.info(f"Completed download attempt for sample ID: {sample_id}")
        time.sleep(DOWNLOAD_DELAY)
    
    console.print("\n[bold green]All downloads completed successfully![/bold green]")

if __name__ == "__main__":
    main()
