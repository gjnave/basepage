import requests
import base64
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import yt_dlp
import os
import tempfile
import uuid
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
import time
import datetime
import collections # Added for collections.deque
import traceback # Added for detailed error printing

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

def get_raw_text_data(url, base_url=None):
    max_retries = 3
    retry_delay = 5
    for attempt in range(max_retries):
        try:
            headers = COMMON_HEADERS.copy()
            if base_url:
                headers['Referer'] = base_url
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"Error fetching raw text for {url} (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"All retries failed for {url}.")
                return None
    return None

def get_base64_data(url, base_url=None, downloaded_resources=None):
    if downloaded_resources is not None and url in downloaded_resources:
        return downloaded_resources[url]

    max_retries = 3
    retry_delay = 5
    for attempt in range(max_retries):
        try:
            headers = COMMON_HEADERS.copy()
            if base_url:
                headers['Referer'] = base_url
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').split(';')[0]
            base64_content = base64.b64encode(response.content).decode('utf-8')
            result = f"data:{content_type};base64,{base64_content}"
            if downloaded_resources is not None:
                downloaded_resources[url] = result
            return result
        except requests.exceptions.RequestException as e:
            print(f"Error fetching base64 data for {url} (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"All retries failed for {url}.")
                return None
    return None

def download_video(url, base_url=None, downloaded_resources=None):
    if downloaded_resources is not None and url in downloaded_resources:
        return downloaded_resources[url]

    temp_dir = tempfile.gettempdir()
    unique_id = uuid.uuid4().hex
    temp_filename_template = os.path.join(temp_dir, f"temp_video_{unique_id}")
    # We will try to find the actual downloaded file extension later
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': temp_filename_template + '.%(ext)s', # yt-dlp adds the extension
        'http_headers': {'User-Agent': COMMON_HEADERS['User-Agent']},
        'noplaylist': True,
        'quiet': True,
        'verbose': False,
    }

    actual_downloaded_file = None # Keep track of the file that was actually created
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Try to find the downloaded file, preferring mp4
        possible_extensions = ['mp4', 'webm', 'mkv', 'flv', 'avi', 'mov']
        for ext in possible_extensions:
            potential_file = temp_filename_template + '.' + ext
            if os.path.exists(potential_file):
                actual_downloaded_file = potential_file
                if ext != 'mp4':
                    print(f"Note: Video downloaded as {ext} instead of mp4 for {url}")
                break
        
        if not actual_downloaded_file:
            print(f"Error: yt_dlp did not download video {url} to a known file format based on template {temp_filename_template}")
            return None

        with open(actual_downloaded_file, 'rb') as video_file:
            video_content = video_file.read()
        
        file_ext_for_type = os.path.splitext(actual_downloaded_file)[1].lower()
        content_type = f"video/{file_ext_for_type[1:]}" if file_ext_for_type else "video/mp4" # Default to mp4 if somehow no ext

        base64_video_data = f"data:{content_type};base64,{base64.b64encode(video_content).decode('utf-8')}"
        if downloaded_resources is not None:
            downloaded_resources[url] = base64_video_data
        return base64_video_data
    except Exception as e:
        print(f"Error downloading video {url} with yt_dlp: {e}")
        traceback.print_exc() # Print stack trace for ydlp errors
        return None
    finally:
        # Cleanup: remove the temporary file if it exists, trying all known extensions
        if actual_downloaded_file and os.path.exists(actual_downloaded_file) : # If we know the exact file
             try:
                os.remove(actual_downloaded_file)
             except OSError as oe:
                print(f"Error removing temporary video file {actual_downloaded_file}: {oe}")
        else: # If we don't know the exact file, try to clean up based on template
            possible_extensions_cleanup = ['mp4', 'webm', 'mkv', 'flv', 'avi', 'mov', 'part']
            for ext in possible_extensions_cleanup:
                potential_file = temp_filename_template + '.' + ext
                if os.path.exists(potential_file):
                    try:
                        os.remove(potential_file)
                    except OSError as oe:
                        print(f"Error removing temporary video file {potential_file}: {oe}")


def process_page_data(current_url, driver, downloaded_resources):
    try:
        print(f"Processing page with Selenium: {current_url}")
        driver.get(current_url)
        # Basic wait for initial load, Selenium's get should handle this for document.readyState 'complete'
        # For very dynamic pages, explicit waits for certain elements might be better than fixed time.sleep
        time.sleep(1) # Small wait for any immediate JS redirects or basic setup
        
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(3): # Scroll up to 3 times
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            print(f"Scrolled ({i+1}/3) on {current_url}")
            time.sleep(2) # Wait for content to load after scroll
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print(f"Page height stabilized on {current_url}")
                break
            last_height = new_height
        page_html = driver.page_source
        print(f"Page source length for {current_url}: {len(page_html)}")
    except Exception as e:
        print(f"Selenium error loading page {current_url}: {e}")
        traceback.print_exc()
        return None

    soup = BeautifulSoup(page_html, 'html.parser')

    # CSS processing
    for link_tag in soup.find_all('link', rel='stylesheet'):
        if 'href' in link_tag.attrs and is_essential_resource(link_tag['href']):
            css_url = urljoin(current_url, link_tag['href'])
            css_text_content = get_raw_text_data(css_url, base_url=current_url)
            if css_text_content:
                new_style_tag = soup.new_tag('style')
                new_style_tag.string = css_text_content
                link_tag.replace_with(new_style_tag)

    # Image, Audio, Video (direct tags) processing
    for tag_name in ['img', 'audio', 'video']:
        for tag in soup.find_all(tag_name):
            # Handle src attribute
            src_attr = tag.get('src')
            if src_attr and not src_attr.startswith('data:') and is_essential_resource(src_attr):
                full_url = urljoin(current_url, src_attr)
                if tag_name == 'img' or tag_name == 'audio':
                    base64_data = get_base64_data(full_url, base_url=current_url, downloaded_resources=downloaded_resources)
                    if base64_data: tag['src'] = base64_data
                elif tag_name == 'video':
                    base64_data = download_video(full_url, base_url=current_url, downloaded_resources=downloaded_resources)
                    if base64_data: tag['src'] = base64_data
            
            # Handle poster attribute for video tags
            if tag_name == 'video':
                poster_attr = tag.get('poster')
                if poster_attr and not poster_attr.startswith('data:') and is_essential_resource(poster_attr):
                    full_poster_url = urljoin(current_url, poster_attr)
                    base64_poster_data = get_base64_data(full_poster_url, base_url=current_url, downloaded_resources=downloaded_resources)
                    if base64_poster_data: tag['poster'] = base64_poster_data

            # Process <source> tags within <audio> and <video>
            if tag_name in ['audio', 'video']:
                for source_tag in tag.find_all('source'):
                    src_attr_source = source_tag.get('src')
                    if src_attr_source and not src_attr_source.startswith('data:') and is_essential_resource(src_attr_source):
                        full_source_url = urljoin(current_url, src_attr_source)
                        if tag_name == 'audio':
                             base64_data = get_base64_data(full_source_url, base_url=current_url, downloaded_resources=downloaded_resources)
                        else: # video
                             base64_data = download_video(full_source_url, base_url=current_url, downloaded_resources=downloaded_resources)
                        if base64_data: source_tag['src'] = base64_data
    
    # YouTube iframe processing
    for iframe_tag in soup.find_all('iframe'):
        src_attr = iframe_tag.get('src')
        if src_attr and 'youtube.com' in src_attr and is_essential_resource(src_attr):
            video_url = src_attr 
            base64_data = download_video(video_url, base_url=current_url, downloaded_resources=downloaded_resources)
            if base64_data:
                new_video_tag = soup.new_tag('video', controls=True)
                new_video_tag['src'] = base64_data
                # Attempt to preserve some dimensions if specified, but this can be tricky
                width = iframe_tag.get('width')
                height = iframe_tag.get('height')
                if width: new_video_tag['width'] = width
                if height: new_video_tag['height'] = height
                iframe_tag.replace_with(new_video_tag)

    # Remove script tags
    for script_tag in soup.find_all('script'):
        script_tag.decompose()

    return soup

def crawl_site(start_url, max_depth=2):
    driver = None
    processed_pages_content = {}
    downloaded_resources = {} # Cache for all base64 encoded resources
    urls_to_visit = collections.deque([(start_url, 1)])
    visited_urls = set()
    
    # Determine the domain of the start_url to stay on the same domain
    try:
        start_domain = urlparse(start_url).netloc
        if not start_domain:
            print(f"Could not determine domain for start URL: {start_url}. Aborting.")
            return {}, {}
    except ValueError as e:
        print(f"Invalid start URL {start_url}: {e}. Aborting.")
        return {}, {}

    try:
        # WebDriver Initialization
        try:
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu") # Often recommended for headless
            chrome_options.add_argument("--window-size=1920,1080") # Can help with responsive sites
            chrome_options.add_argument(f"user-agent={COMMON_HEADERS['User-Agent']}")
            # Suppress logs, be careful with this as it hides useful info
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            driver = webdriver.Chrome(options=chrome_options)
            print("Using Chrome WebDriver.")
        except Exception as e_chrome:
            print(f"Chrome WebDriver initialization failed: {e_chrome}. Trying Firefox...")
            traceback.print_exc()
            try:
                firefox_options = FirefoxOptions()
                firefox_options.add_argument("--headless")
                firefox_options.add_argument(f"user-agent={COMMON_HEADERS['User-Agent']}")
                driver = webdriver.Firefox(options=firefox_options)
                print("Using Firefox WebDriver.")
            except Exception as e_firefox:
                print(f"Firefox WebDriver initialization failed: {e_firefox}")
                traceback.print_exc()
                print("Please ensure a compatible WebDriver (chromedriver or geckodriver) is in your PATH.")
                return {}, {}

        if not driver:
            print("WebDriver could not be initialized.")
            return {}, {}

        # Main crawling loop
        while urls_to_visit:
            current_url, depth = urls_to_visit.popleft()

            if current_url in visited_urls:
                print(f"Already visited: {current_url}. Skipping.")
                continue
            
            # Check domain again before processing (in case of redirects not caught by Selenium)
            current_domain = urlparse(current_url).netloc
            if current_domain != start_domain:
                print(f"Skipping {current_url} as it's on a different domain ({current_domain}) than start domain ({start_domain}).")
                continue

            visited_urls.add(current_url)
            print(f"Processing [Depth: {depth}/{max_depth}]: {current_url}")
            
            page_soup = process_page_data(current_url, driver, downloaded_resources)

            if page_soup:
                processed_pages_content[current_url] = page_soup
                if depth < max_depth:
                    for link_tag in page_soup.find_all('a', href=True):
                        href = link_tag['href']
                        abs_url = urljoin(current_url, href).split('#')[0]

                        if not abs_url.startswith(('http://', 'https://')):
                            continue # Skip non-http links (mailto, javascript:, etc.)
                        
                        # Check domain of the absolute URL
                        linked_domain = urlparse(abs_url).netloc
                        if linked_domain != start_domain:
                            # print(f"Skipping external link found on {current_url}: {abs_url}")
                            continue

                        if abs_url not in visited_urls:
                            # Avoid adding to queue if already there
                            in_queue = any(item[0] == abs_url for item in urls_to_visit)
                            if not in_queue:
                                print(f"Queueing [Depth {depth+1}]: {abs_url} (from {current_url})")
                                urls_to_visit.append((abs_url, depth + 1))
                            # else:
                                # print(f"Already in queue: {abs_url}")
            else:
                print(f"Failed to process page soup for: {current_url}")
                
    except Exception as e:
        print(f"Major error during site crawling: {e}")
        traceback.print_exc()
    finally:
        if driver:
            driver.quit()
            print("WebDriver closed.")

    return processed_pages_content, downloaded_resources


if __name__ == "__main__":
    try:
        page_url_input = input("Enter the URL of the webpage you want to crawl (max 2 levels deep, same domain): ")
        if not (page_url_input.startswith('http://') or page_url_input.startswith('https://')):
            if "://" not in page_url_input: # Basic check if scheme is missing
                page_url_input = "https://" + page_url_input
            else: # Some other scheme or malformed
                print(f"Warning: URL scheme may not be http/https: {page_url_input}. Proceeding with caution.")
        
        print(f"Starting crawl for: {page_url_input}")
        
        processed_pages_map, site_downloaded_resources = crawl_site(page_url_input, max_depth=2)
        
        main_page_soup = processed_pages_map.get(page_url_input)

        if main_page_soup:
            print("Starting re-linking process for the main page...")
            for link_tag in main_page_soup.find_all('a', href=True):
                original_href = link_tag['href']
                # Ensure page_url_input is the base for resolving relative links from the main page
                abs_original_href = urljoin(page_url_input, original_href).split('#')[0] 

                if abs_original_href in processed_pages_map and abs_original_href != page_url_input: # Don't re-link to self
                    linked_page_soup = processed_pages_map[abs_original_href]
                    linked_page_html = linked_page_soup.prettify()
                    # Ensure proper encoding before base64 conversion
                    linked_page_base64 = base64.b64encode(linked_page_html.encode('utf-8')).decode('utf-8')
                    link_tag['href'] = f"data:text/html;charset=utf-8;base64,{linked_page_base64}"
                    print(f"Re-linked internal link '{original_href}' to embedded HTML of '{abs_original_href}'")
                elif abs_original_href in site_downloaded_resources:
                    link_tag['href'] = site_downloaded_resources[abs_original_href]
                    print(f"Re-linked resource link '{original_href}' to its base64 data from '{abs_original_href}'")
                else:
                    # Optional: could set href to '#' for links not processed or found in resources
                    # print(f"Link '{original_href}' (abs: '{abs_original_href}') not found in processed pages or downloaded resources. Leaving as is or consider making it dead.")
                    pass # Leaving as is for now

            # Generate filename for the main page
            parsed_main_url = urlparse(page_url_input)
            domain_main = parsed_main_url.netloc.replace('.', '_').replace(':', '_') # Sanitize
            timestamp_main = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename_main = f"crawled_{domain_main}_{timestamp_main}_main_linked.html" # New suffix
            
            with open(output_filename_main, 'w', encoding='utf-8') as f:
                f.write(main_page_soup.prettify()) # main_page_soup is now modified
            print(f"Crawling and re-linking complete. Main page saved to {output_filename_main}")
            print(f"Total unique resources downloaded and cached: {len(site_downloaded_resources)}")
            print(f"Total pages processed: {len(processed_pages_map)}")
        else:
            print(f"Crawling failed or produced no content for the main page: {page_url_input}")

    except Exception as e_main:
        print(f"An unexpected error occurred in main execution: {e_main}")
        traceback.print_exc()
