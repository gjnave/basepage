import requests
import base64
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import yt_dlp
import os
import tempfile
import uuid
import time # For potential explicit waits if needed
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
# Potentially add: from selenium.webdriver.common.by import By
# Potentially add: from selenium.webdriver.support.ui import WebDriverWait
# Potentially add: from selenium.webdriver.support import expected_conditions as EC
import datetime # ADD THIS

COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

def is_essential_resource(url):
    excluded_domains = ['googlesyndication', 'googleadservices', 'doubleclick', 'analytics']
    parsed_url = urlparse(url)
    return not any(domain in parsed_url.netloc for domain in excluded_domains)

def get_base64_data(url, base_url=None):
    max_retries = 3
    retry_delay = 5  # seconds
    for attempt in range(max_retries):
        try:
            headers = COMMON_HEADERS.copy()
            if base_url:
                headers['Referer'] = base_url
            response = requests.get(url, headers=headers, timeout=15) 
            response.raise_for_status() # Raise an exception for bad status codes
            content_type = response.headers.get('Content-Type', '').split(';')[0]
            base64_content = base64.b64encode(response.content).decode('utf-8')
            return f"data:{content_type};base64,{base64_content}"
        except requests.exceptions.RequestException as e:
            print(f"Error fetching base64 data for {url} (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                # Optional: retry_delay *= 2 # Exponential backoff
            else:
                print(f"All retries failed for {url} (base64 data).")
                return None
    return None # Fallback, should be unreachable

def get_raw_text_data(url, base_url=None):
    max_retries = 3
    retry_delay = 5  # seconds
    for attempt in range(max_retries):
        try:
            headers = COMMON_HEADERS.copy()
            if base_url:
                headers['Referer'] = base_url
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            # It's good to respect original charset if provided, but often UTF-8 is a safe bet for text.
            # response.encoding = response.apparent_encoding # Or some other logic to get correct encoding
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"Error fetching raw text for {url} (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                # Optional: retry_delay *= 2 # Exponential backoff
            else:
                print(f"All retries failed for {url} (raw text).")
                return None
    return None # Fallback, should be unreachable

def download_video(url, base_url=None):
    # Generate a unique temporary filename in the system's temp directory
    # Ensure the directory part does not have '.%(ext)s'
    temp_dir = tempfile.gettempdir()
    unique_id = uuid.uuid4().hex
    # yt-dlp needs a template for the filename, not the full path for outtmpl if using format specific extensions
    # So, we will construct the full path after download for reading.
    temp_filename_template = os.path.join(temp_dir, f"temp_video_{unique_id}") # No extension here yet
    
    # The actual downloaded file will have an extension like .mp4, .webm etc.
    # We'll need to find it or make assumptions. Forcing mp4.
    downloaded_file_path = temp_filename_template + ".mp4" # Assuming mp4 due to format selection

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', # More robust format selection
        'outtmpl': temp_filename_template + '.%(ext)s', # yt-dlp will add the extension
        'http_headers': {'User-Agent': COMMON_HEADERS['User-Agent']},
        'noplaylist': True,
        'quiet': True,
        'verbose': False,
        # 'ignoreerrors': True, # Decide if you want to try to recover or fail hard
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Check if the specific MP4 file (or best format) exists
        # Since outtmpl now includes the directory, this check should be on downloaded_file_path
        if not os.path.exists(downloaded_file_path):
            # Try to find any downloaded file if mp4 wasn't created (e.g. webm)
            # This is a bit more complex; for now, stick to expecting mp4
            print(f"Error: yt_dlp did not download video {downloaded_file_path} from {url}")
            return None

        with open(downloaded_file_path, 'rb') as video_file:
            video_content = video_file.read()
        
        base64_content = base64.b64encode(video_content).decode('utf-8')
        return f"data:video/mp4;base64,{base64_content}"
    except Exception as e:
        print(f"Error downloading video {url} with yt_dlp: {e}")
        return None
    finally:
        # Cleanup: remove the temporary file if it exists
        if os.path.exists(downloaded_file_path):
            try:
                os.remove(downloaded_file_path)
            except OSError as oe: # To catch potential errors during deletion (e.g. file in use)
                print(f"Error removing temporary video file {downloaded_file_path}: {oe}")
        # Also attempt to remove if yt-dlp used a different extension (e.g. .webm)
        # This part is tricky if the extension isn't known.
        # A more robust way would be to list files matching "temp_video_{unique_id}.*"
        # For now, the primary target is downloaded_file_path.


def crawl_page(url):
    driver = None  # Initialize driver to None for the finally block
    page_html = None
    try:
        # --- Try Chrome first ---
        try:
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox") # Often needed in restricted environments
            chrome_options.add_argument("--disable-dev-shm-usage") # Overcome limited resource problems
            chrome_options.add_argument(f"user-agent={COMMON_HEADERS['User-Agent']}") # Set user agent for Selenium
            
            # For development, you might want to specify the driver path if not in PATH
            # driver = webdriver.Chrome(executable_path='/path/to/chromedriver', options=chrome_options)
            driver = webdriver.Chrome(options=chrome_options)
            print("Using Chrome WebDriver.")
        except Exception as e_chrome:
            print(f"Chrome WebDriver initialization failed: {e_chrome}")
            # --- Fallback to Firefox ---
            try:
                firefox_options = FirefoxOptions()
                firefox_options.add_argument("--headless")
                firefox_options.add_argument(f"user-agent={COMMON_HEADERS['User-Agent']}")

                # For development, you might want to specify the driver path
                # driver = webdriver.Firefox(executable_path='/path/to/geckodriver', options=firefox_options)
                driver = webdriver.Firefox(options=firefox_options)
                print("Using Firefox WebDriver.")
            except Exception as e_firefox:
                print(f"Firefox WebDriver initialization failed: {e_firefox}")
                print("Please ensure a compatible WebDriver (chromedriver or geckodriver) is in your PATH or specified.")
                return "" # Or raise an error

        if not driver: # If both failed
             return ""

        driver.get(url)
        
        # Wait for dynamic content to load (simple approach)
        # A better way is to use WebDriverWait for specific elements if known
        time.sleep(5) # Wait 5 seconds for JavaScript execution

        page_html = driver.page_source
           
    except Exception as e:
        print(f"Error during Selenium WebDriver operation for {url}: {e}")
        return "" # Return empty string or handle error as appropriate
    finally:
        if driver:
            driver.quit()

    if not page_html:
        print(f"Failed to fetch page HTML with Selenium for {url}")
        return ""

    # The rest of the function remains the same, using page_html instead of response.content
    soup = BeautifulSoup(page_html, 'html.parser')

    # Handle external stylesheets
    for link in soup.find_all('link', rel='stylesheet'):
        if 'href' in link.attrs and is_essential_resource(link['href']): # ensure href exists
            css_url = urljoin(url, link['href'])
            css_text_content = get_raw_text_data(css_url, base_url=url) # New function
            if css_text_content:
                new_style = soup.new_tag('style')
                new_style.string = css_text_content # Direct text content
                link.replace_with(new_style)

    # Handle images, audio, and video
    for tag in soup.find_all(['img', 'audio', 'video', 'source', 'iframe']):
        src_attr = tag.get('src')
        if not src_attr: # Skip tags without a src attribute
            continue

        if tag.name == 'iframe' and 'youtube.com' in src_attr:
            # yt_dlp is good with YouTube URLs, complex parsing of video ID might not be needed
            # video_id = src_attr.split('/')[-1].split('?')[0] 
            # video_url = f"https://youtu.be/{video_id}" 
            video_url = src_attr # Pass the original iframe src directly to yt_dlp
            print(f"Downloading YouTube video: {video_url}")
            base64_data = download_video(video_url, base_url=url)
            if base64_data:
                new_video = soup.new_tag('video', controls=True)
                new_video['src'] = base64_data
                tag.replace_with(new_video)
        elif is_essential_resource(src_attr):
            full_url = urljoin(url, src_attr)
            if tag.name in ['video', 'source'] or (tag.name == 'iframe' and 'youtube.com' not in src_attr): # General video or other iframes
                print(f"Downloading video/media from {full_url}")
                # Using download_video for general videos as well, assuming yt_dlp can handle them
                base64_data = download_video(full_url, base_url=url) 
            else: # Images, audio
                base64_data = get_base64_data(full_url, base_url=url)
            
            if base64_data:
                tag['src'] = base64_data

    # Remove scripts
    for script in soup.find_all('script'):
        script.decompose()

    return soup.prettify()

# Get URL input from user
# It's better to handle potential errors during input or processing
if __name__ == "__main__":
    try:
        page_url = input("Enter the URL of the webpage you want to crawl: ")
        if not (page_url.startswith('http://') or page_url.startswith('https://')):
            # Simple heuristic for adding https if scheme is missing
            if "://" not in page_url:
                 page_url = "https://" + page_url
            else: # Scheme is something else (e.g. ftp), or malformed. Let it try.
                 print(f"Warning: URL scheme is not http or https: {page_url}")


        html_content = crawl_page(page_url)

        if html_content:
            # Generate unique filename
            parsed_url = urlparse(page_url)
            domain = parsed_url.netloc.replace('.', '_').replace(':', '_') # Sanitize for filename
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"{domain}_{timestamp}.html"
            
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"Crawling complete. The result has been saved to {output_filename}")
        else:
            print("Crawling failed or produced no content.")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
