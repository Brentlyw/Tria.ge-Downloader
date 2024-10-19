import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as file:
            try:
                config = json.load(file)
                return config
            except json.JSONDecodeError:
                print("Error: Config file is not JSON..?")
                return {}
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as file:
        json.dump(config, file, indent=4)
    print(f"Configuration saved to {CONFIG_FILE}.")

def get_auth_token(config):
    auth_token = config.get("auth_token")
    if not auth_token:
        auth_token = input("Auth/Session Token?: ").strip()
        config["auth_token"] = auth_token
        save_config(config)
    return auth_token

def get_user_input():
    family = input("Family?: ").strip()
    return family

def construct_search_url(family):
    encoded_family = quote(family)
    search_url = f"https://tria.ge/s?q=family%3A{encoded_family}&limit=500"
    return search_url

def fetch_search_page(url, headers):
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error fetching search page: {e}")
        return None

def parse_sample_ids(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    elements = soup.find_all(attrs={"data-sample-id": True})
    sample_ids = [element['data-sample-id'] for element in elements]
    return sample_ids

def download_sample(sample_id, headers, download_dir):
    download_url = f"https://tria.ge/samples/{sample_id}/sample.zip"
    try:
        response = requests.get(download_url, headers=headers, stream=True)
        response.raise_for_status()
        file_path = os.path.join(download_dir, f"{sample_id}_sample.zip")
        with open(file_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
        print(f"Downloaded: {file_path}")
    except requests.RequestException as e:
        print(f"Error downloading {sample_id}: {e}")

def main():
    config = load_config()
    auth_token = get_auth_token(config)
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "User-Agent": "Python Script"
    }
    family = get_user_input()
    if not family:
        print("Family name cannot be empty.")
        return
    search_url = construct_search_url(family)
    print(f"Searching for family '{family}' at {search_url}...")
    html_content = fetch_search_page(search_url, headers)
    if not html_content:
        print("Failed to retrieve search results.")
        return
    sample_ids = parse_sample_ids(html_content)
    if not sample_ids:
        print("No samples found for the given family.")
        return
    print(f"Found {len(sample_ids)} samples. Starting download...")
    download_dir = os.path.join("downloads", family)
    os.makedirs(download_dir, exist_ok=True)
    for idx, sample_id in enumerate(sample_ids, 1):
        print(f"Downloading sample {idx}/{len(sample_ids)}: {sample_id}")
        download_sample(sample_id, headers, download_dir)
    print("All downloads completed!!")

if __name__ == "__main__":
    main()
