import httplib2
import urllib.request
from bs4 import BeautifulSoup, SoupStrainer
import os
import progressbar

url = 'https://myrient.erista.me/files/Redump/Sony%20-%20PlayStation%20Portable/'

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



for link in BeautifulSoup(content, features="html.parser").find_all('a', href=True):
    links.append(link['href'])

for link in links:
    fileName = urllib.parse.unquote(link, encoding='utf-8', errors='replace')
    if '%28USA%29' in link and '%28Demo%29' not in link and '%28Beta%29' not in link:
        # print(fileName)
        if os.path.exists(cwd + '\\' + fileName):
            print(fileName + ' Already Downloaded')
        else:
            # if 'Yggdra%20Union%20%28USA%29.zip' == link:
            print(fileName)
            urllib.request.urlretrieve(url + link, fileName, show_progress)
