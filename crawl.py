import requests
import base64
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import yt_dlp
import os

def is_essential_resource(url):
    excluded_domains = ['googlesyndication', 'googleadservices', 'doubleclick', 'analytics']
    parsed_url = urlparse(url)
    return not any(domain in parsed_url.netloc for domain in excluded_domains)

def get_base64_data(url):
    try:
        response = requests.get(url)
        content_type = response.headers.get('Content-Type', '').split(';')[0]
        base64_content = base64.b64encode(response.content).decode('utf-8')
        return f"data:{content_type};base64,{base64_content}"
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def download_video(url):
    ydl_opts = {
        'format': 'best[ext=mp4]',
        'outtmpl': 'temp_video.%(ext)s'
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    with open('temp_video.mp4', 'rb') as video_file:
        video_content = video_file.read()
    
    os.remove('temp_video.mp4')
    
    base64_content = base64.b64encode(video_content).decode('utf-8')
    return f"data:video/mp4;base64,{base64_content}"

def crawl_page(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Handle external stylesheets
    for link in soup.find_all('link', rel='stylesheet'):
        if is_essential_resource(link['href']):
            css_url = urljoin(url, link['href'])
            css_content = get_base64_data(css_url)
            if css_content:
                new_style = soup.new_tag('style')
                new_style.string = f"@import url('{css_content}');"
                link.replace_with(new_style)

    # Handle images, audio, and video
    for tag in soup.find_all(['img', 'audio', 'video', 'source', 'iframe']):
        if tag.name == 'iframe' and 'youtube.com' in tag.get('src', ''):
            video_id = tag['src'].split('/')[-1].split('?')[0]
            video_url = f"https://youtu.be/{video_id}"
            print(f"Downloading YouTube video: {video_url}")
            base64_data = download_video(video_url)
            if base64_data:
                new_video = soup.new_tag('video', controls=True)
                new_video['src'] = base64_data
                tag.replace_with(new_video)
        elif 'src' in tag.attrs and is_essential_resource(tag['src']):
            full_url = urljoin(url, tag['src'])
            if tag.name in ['video', 'source']:
                print(f"Downloading video from {full_url}")
                base64_data = download_video(full_url)
            else:
                base64_data = get_base64_data(full_url)
            if base64_data:
                tag['src'] = base64_data

    # Remove scripts
    for script in soup.find_all('script'):
        script.decompose()

    return soup.prettify()

# Get URL input from user
url = input("Enter the URL of the webpage you want to crawl: ")

html_content = crawl_page(url)

# Save the self-contained HTML file
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html_content)

print("Crawling complete. The result has been saved to index.html")