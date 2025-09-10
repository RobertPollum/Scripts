import httplib2, os, time, progressbar
import urllib.request
from bs4 import BeautifulSoup, SoupStrainer

url = 'https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Nintendo%2064%20%28BigEndian%29/'
http = httplib2.Http()

response, content = http.request(url)

links=[]

cwd = os.getcwd()

pbar = None

def show_progress(block_num, block_size, total_size):
    global pbar
    if pbar is None:
        pbar = progressbar.ProgressBar(maxval=total_size)
        pbar.start()

    downloaded = block_num * block_size
    if downloaded < total_size:
        pbar.update(downloaded)
    else:
        pbar.finish()
        pbar = None

def download_with_retry(url, filename, max_retries=3, delay=5):
    retries = 0
    while retries < max_retries:
        try:
            urllib.request.urlretrieve(url, filename, show_progress)
            print(f"Downloaded '{url}' to '{filename}' successfully.")
            return True  # Indicate success
        except urllib.error.URLError as e:
            print(f"Error during download: {e}")
            print(f"Retrying in {delay} seconds...")
            time.sleep(delay)
            retries += 1
        except urllib.error.HTTPError as e:
            print(f"HTTP Error: {e}")
            print(f"Retrying in {delay} seconds...")
            time.sleep(delay)
            retries += 1
    print(f"Failed to download '{url}' after {max_retries} retries.")
    return False  # Indicate failure

for link in BeautifulSoup(content, features="html.parser").find_all('a', href=True):
    links.append(link['href'])

for link in links:
    fileName = urllib.parse.unquote(link, encoding='utf-8', errors='replace')
    if ('%28USA%29' in link or '%28World%29' in link) and '%28Demo%29' not in link and '%28Beta%29' not in link:
        # print(fileName)
        if os.path.exists(cwd + '\\' + fileName):
            print(fileName + ' Already Downloaded')
        else:
            # if 'Yggdra%20Union%20%28USA%29.zip' == link:
            print(fileName)
            if download_with_retry(url + link, fileName) :
                print("Download complete.")
            else:
                print("Download failed.")
            
